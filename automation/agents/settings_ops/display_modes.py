"""Read-only DXGI mode catalogue; candidates are not approved desktop changes.

ABI: Microsoft SDK shared/dxgi.h and shared/dxgi1_2.h. No swap chain,
ownership, window association or display-setting method is called.
"""
import ctypes as ct
from contextlib import contextmanager
from fractions import Fraction
import os
import uuid

from . import ActionError
from .display_config import Rational

U32, PTR = ct.c_uint32, ct.c_void_p
FORMAT = 28  # DXGI_FORMAT_R8G8B8A8_UNORM; this does not infer desktop HDR/depth.
NOT_FOUND, MORE_DATA = 0x887a0002, 0x887a0003


class Guid(ct.Structure):
    _fields_ = [('data1',U32),('data2',ct.c_uint16),('data3',ct.c_uint16),('data4',ct.c_ubyte*8)]


class OutputDesc(ct.Structure):
    _fields_ = [('name',ct.c_wchar*32),('rect',ct.c_int32*4),
                ('attached',ct.c_int32),('rotation',U32),('monitor',PTR)]


class Mode(ct.Structure):
    _fields_ = [('width',U32),('height',U32),('refresh',Rational),('format',U32),
                ('scanline',U32),('scaling',U32),('stereo',ct.c_int32)]


def _success(code):
    if code & 0x80000000:
        raise ActionError(f'Precise alternate-mode query failed (DXGI 0x{code & 0xffffffff:08x}).')


class WindowsModeCatalogue:
    def __init__(self):
        if os.name != 'nt' or ct.sizeof(Guid) != 16 or ct.sizeof(Mode) != 32 or ct.sizeof(OutputDesc) != 88+ct.sizeof(PTR):
            raise ActionError('Precise alternate-mode inspection requires a supported Windows layout.')
        self.api = ct.WinDLL('dxgi')
        self.api.CreateDXGIFactory1.argtypes = [ct.POINTER(Guid),ct.POINTER(PTR)]
        self.api.CreateDXGIFactory1.restype = ct.c_int32

    def call(self, pointer, slot, types, *args):
        table = ct.cast(pointer,ct.POINTER(ct.POINTER(PTR))).contents
        return ct.WINFUNCTYPE(ct.c_int32,PTR,*types)(table[slot])(pointer,*args)

    @contextmanager
    def reference(self, create):
        pointer = PTR()
        try:
            code = create(ct.byref(pointer)) & 0xffffffff
            if code == NOT_FOUND:
                yield None
            else:
                _success(code)
                if not pointer:raise ActionError('DXGI returned an empty interface.')
                yield pointer
        finally:
            if pointer:self.call(pointer,2,[])  # IUnknown::Release, including on cancellation.

    def factory(self):
        guid = Guid.from_buffer_copy(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
        return self.reference(lambda out:self.api.CreateDXGIFactory1(ct.byref(guid),out))

    def child(self, parent, index):
        # IDXGIFactory::EnumAdapters and IDXGIAdapter::EnumOutputs both occupy slot 7.
        return self.reference(lambda out:self.call(parent,7,[U32,ct.POINTER(PTR)],index,out))

    def output1(self, output):
        guid = Guid.from_buffer_copy(uuid.UUID('00cddea8-939b-4b83-a340-a685226666cc').bytes_le)
        return self.reference(lambda out:self.call(output,0,[ct.POINTER(Guid),ct.POINTER(PTR)],ct.byref(guid),out))

    def description(self, output):
        value = OutputDesc()
        _success(self.call(output,7,[ct.POINTER(OutputDesc)],ct.byref(value)))
        return value

    def modes(self, output, count, values):
        return self.call(output,19,[U32,U32,ct.POINTER(U32),ct.POINTER(Mode)],FORMAT,0,ct.byref(count),values)

    def current(self, factory):
        return bool(self.call(factory,13,[]))  # IDXGIFactory1::IsCurrent


def _read_modes(api, output, check):
    for _ in range(3):
        check()
        count = U32()
        code = api.modes(output,count,None) & 0xffffffff
        if code == MORE_DATA:continue
        _success(code)
        if count.value > 4096:raise ActionError('DXGI mode count exceeds its supported bound.')
        if not count.value:return []
        values = (Mode*count.value)()
        check()
        code = api.modes(output,count,values) & 0xffffffff
        if code == MORE_DATA:continue
        _success(code)
        if count.value > len(values):raise ActionError('DXGI returned an invalid mode count.')
        result = {}
        for mode in values[:count.value]:
            check()
            if not mode.width or not mode.height or not mode.refresh.numerator or not mode.refresh.denominator:
                raise ActionError('DXGI returned an incomplete mode or refresh fraction.')
            if mode.format != FORMAT or mode.stereo or mode.scanline not in (0,1) or mode.scaling not in (0,1,2):
                raise ActionError('DXGI returned a mode outside the requested format/scanline/stereo scope.')
            rate = Fraction(mode.refresh.numerator,mode.refresh.denominator)
            key = (mode.width,mode.height,rate,mode.scanline,mode.scaling)
            result[key] = {'width':mode.width,'height':mode.height,
                           'refresh':{'numerator':rate.numerator,'denominator':rate.denominator,'hz':round(float(rate),6)},
                           'format':FORMAT,'scanline':mode.scanline,'scaling':mode.scaling,'stereo':False}
        return [result[key] for key in sorted(result)]
    raise ActionError('DXGI mode choices kept changing; inspect again once stable.')


def read_catalogue(check, *, api=None):
    api = api or WindowsModeCatalogue()
    result = []
    total_modes = 0
    with api.factory() as factory:
        if factory is None:raise ActionError('DXGI did not expose a factory.')
        for adapter_index in range(33):
            check()
            with api.child(factory,adapter_index) as adapter:
                if adapter is None:break
                if adapter_index == 32:raise ActionError('DXGI adapter count exceeds its supported bound.')
                for output_index in range(33):
                    check()
                    with api.child(adapter,output_index) as output:
                        if output is None:break
                        if output_index == 32:raise ActionError('DXGI output count exceeds its supported bound.')
                        desc = api.description(output)
                        if not desc.attached:continue
                        if not desc.name or not desc.monitor:raise ActionError('DXGI did not identify an attached output.')
                        with api.output1(output) as output1:
                            if output1 is None:raise ActionError('DXGI Output1 is unavailable.')
                            modes = _read_modes(api,output1,check)
                        total_modes += len(modes)
                        if total_modes > 16384:raise ActionError('DXGI total mode count exceeds its supported bound.')
                        check()
                        after = api.description(output)
                        if (desc.name,desc.monitor,desc.rotation,tuple(desc.rect),desc.attached) != (after.name,after.monitor,after.rotation,tuple(after.rect),after.attached):
                            raise ActionError('The DXGI output changed during inspection.')
                        result.append({'device_name':desc.name,'rotation':desc.rotation,'modes':modes})
        check()
        if not api.current(factory):raise ActionError('The DXGI adapter topology changed during inspection.')
    return sorted(result,key=lambda value:value['device_name'].casefold())


def match_catalogue(catalogue, display):
    timing = display['active_timing']
    matches = [item for item in catalogue if item['device_name'].casefold() == display['device_name'].casefold()]
    if display['remote'] or timing['status'] != 'observed' or len(matches) != 1 or matches[0]['rotation'] != timing['rotation']:
        return {'status':'unresolved','reason':'A unique local DXGI output could not be matched to the observed display path.'}
    current = display['current']
    return {'status':'observed','format':'R8G8B8A8_UNORM',
            'scope':'DXGI candidates at the current resolution; excludes stereo, interlaced and scaling-required modes. Does not establish preservation of desktop color/HDR or authorize a change.',
            'modes':[mode for mode in matches[0]['modes'] if (mode['width'],mode['height']) == (current['width'],current['height'])]}
