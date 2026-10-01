"""Read active CCD paths, retaining exact reported refresh rationals (Windows 11)."""
import ctypes as ct
from fractions import Fraction

from . import ActionError

U32, I32 = ct.c_uint32, ct.c_int32
FLAGS = 0x52  # Active paths, virtual-mode aware, virtual-refresh aware.


class Luid(ct.Structure):
    _fields_ = [('low',U32),('high',I32)]


class Rational(ct.Structure):
    _fields_ = [('numerator',U32),('denominator',U32)]


class Region(ct.Structure):
    _fields_ = [('width',U32),('height',U32)]


class Point(ct.Structure):
    _fields_ = [('x',I32),('y',I32)]


class Signal(ct.Structure):
    _fields_ = [('pixel_rate',ct.c_uint64),('horizontal',Rational),('vertical',Rational),
                ('active',Region),('total',Region),('additional',U32),('scanline',U32)]


class SourceMode(ct.Structure):
    _fields_ = [('width',U32),('height',U32),('pixel_format',U32),('position',Point)]


class ModeData(ct.Union):
    _fields_ = [('signal',Signal),('source',SourceMode)]  # Signal is the largest union member.


class ModeInfo(ct.Structure):
    _fields_ = [('kind',U32),('id',U32),('adapter',Luid),('data',ModeData)]


class PathSource(ct.Structure):
    _fields_ = [('adapter',Luid),('id',U32),('mode_index',U32),('status',U32)]


class PathTarget(ct.Structure):
    _fields_ = [('adapter',Luid),('id',U32),('mode_index',U32),('technology',U32),
                ('rotation',U32),('scaling',U32),('refresh',Rational),('scanline',U32),
                ('available',I32),('status',U32)]


class DisplayPath(ct.Structure):
    _fields_ = [('source',PathSource),('target',PathTarget),('flags',U32)]


class InfoHeader(ct.Structure):
    _fields_ = [('kind',U32),('size',U32),('adapter',Luid),('id',U32)]


class SourceName(ct.Structure):
    _fields_ = [('header',InfoHeader),('name',ct.c_wchar*32)]


class TargetName(ct.Structure):
    _fields_ = [('header',InfoHeader),('flags',U32),('technology',U32),
                ('manufacturer',ct.c_uint16),('product',ct.c_uint16),('connector',U32),
                ('name',ct.c_wchar*64),('path',ct.c_wchar*128)]


class AdvancedColor(ct.Structure):
    _fields_ = [('header',InfoHeader),('flags',U32),('encoding',U32),('bits_per_channel',U32)]


def configure(api):
    if (ct.sizeof(DisplayPath),ct.sizeof(ModeInfo),ct.sizeof(SourceName),ct.sizeof(TargetName),ct.sizeof(AdvancedColor)) != (72,64,84,420,32):
        raise ActionError('Unsupported Windows display configuration layout.')
    api.GetDisplayConfigBufferSizes.argtypes = [U32,ct.POINTER(U32),ct.POINTER(U32)]
    api.GetDisplayConfigBufferSizes.restype = I32
    api.QueryDisplayConfig.argtypes = [U32,ct.POINTER(U32),ct.POINTER(DisplayPath),ct.POINTER(U32),ct.POINTER(ModeInfo),ct.c_void_p]
    api.QueryDisplayConfig.restype = I32
    api.DisplayConfigGetDeviceInfo.argtypes = [ct.POINTER(InfoHeader)]
    api.DisplayConfigGetDeviceInfo.restype = I32


def _success(code):
    if code:
        raise ActionError(f'Windows precise display query failed (code {code}); no precise timing is claimed.')


def _fraction(rate):
    if not rate.numerator or not rate.denominator:
        return None
    value = Fraction(rate.numerator,rate.denominator)
    return {'numerator':value.numerator,'denominator':value.denominator,'hz':round(float(value),6)}


def _mode(modes, count, endpoint, virtual, kind):
    index = endpoint.mode_index >> 16 if virtual else endpoint.mode_index
    invalid = 0xffff if virtual else 0xffffffff
    if index == invalid or index >= count:
        raise ActionError('The active display path has no valid mode index; inspect again.')
    mode = modes[index]
    if mode.kind != kind or mode.id != endpoint.id or (mode.adapter.low,mode.adapter.high) != (endpoint.adapter.low,endpoint.adapter.high):
        raise ActionError('The active display path and its mode identity disagree; inspect again.')
    return mode.data


def _advanced_color(api, target, check):
    check()
    value = AdvancedColor()
    value.header = InfoHeader(9,ct.sizeof(value),target.adapter,target.id)
    code = api.DisplayConfigGetDeviceInfo(ct.byref(value.header))
    if code:
        return {'status':'unavailable','reason':f'Windows advanced-color query failed (code {code}).'}
    if value.encoding > 4 or not 1 <= value.bits_per_channel <= 32:
        return {'status':'unavailable','reason':'Windows returned incomplete advanced-color information.'}
    return {'status':'observed','supported':bool(value.flags & 1),
            'enabled':bool(value.flags & 2),'wide_color_enforced':bool(value.flags & 4),
            'force_disabled':bool(value.flags & 8),'encoding':value.encoding,
            'bits_per_channel':value.bits_per_channel}


def read_paths(api, check):
    for _ in range(3):
        check()
        path_count, mode_count = U32(), U32()
        _success(api.GetDisplayConfigBufferSizes(FLAGS,ct.byref(path_count),ct.byref(mode_count)))
        if not (0 < path_count.value <= 128 and 0 < mode_count.value <= 512):
            raise ActionError('Precise display enumeration is empty or exceeds its supported bounds.')
        paths, modes = (DisplayPath*path_count.value)(), (ModeInfo*mode_count.value)()
        check()
        code = api.QueryDisplayConfig(FLAGS,ct.byref(path_count),paths,ct.byref(mode_count),modes,None)
        if code == 122:  # Monitor topology changed after the buffer-size query.
            continue
        _success(code)
        if path_count.value > len(paths) or mode_count.value > len(modes):
            raise ActionError('Windows returned invalid display buffer counts.')
        break
    else:
        raise ActionError('The display configuration kept changing; inspect again once it is stable.')
    result = []
    for path in paths[:path_count.value]:
        check()
        if not path.flags & 1 or not path.target.available:
            raise ActionError('A queried active display disconnected; inspect again.')
        virtual = bool(path.flags & 8)
        source_mode = _mode(modes,mode_count.value,path.source,virtual,1).source
        signal = _mode(modes,mode_count.value,path.target,virtual,2).signal
        source, target = SourceName(), TargetName()
        for value, endpoint, kind in ((source,path.source,1),(target,path.target,2)):
            check()
            value.header = InfoHeader(kind,ct.sizeof(value),endpoint.adapter,endpoint.id)
            _success(api.DisplayConfigGetDeviceInfo(ct.byref(value.header)))
        if not source.name or not target.path:
            raise ActionError('Windows did not identify the source and physical monitor path.')
        result.append({'device_name':source.name,'monitor_path':target.path,'monitor_name':target.name,
                       'advanced_color':_advanced_color(api,path.target,check),
                       'source':{'width':source_mode.width,'height':source_mode.height,
                                 'x':source_mode.position.x,'y':source_mode.position.y},
                       'desktop_refresh':_fraction(path.target.refresh),'signal_vsync':_fraction(signal.vertical),
                       'dynamic_refresh':bool(path.flags & 0x10),'signal_divider':(signal.additional >> 16) & 0x3f,
                       'active_signal':{'width':signal.active.width,'height':signal.active.height},
                       'rotation':path.target.rotation,'scaling':path.target.scaling,'scanline':signal.scanline})
    return sorted(result,key=lambda value:(value['device_name'].casefold(),value['monitor_path'].casefold()))


def match_timing(paths, device_name, monitors, current, position):
    matches = [path for path in paths if path['device_name'].casefold() == device_name.casefold()]
    if len(matches) != 1 or len(monitors) != 1:
        return {'status':'unresolved','reason':'The physical path is missing or shared by multiple monitors.'}
    path = matches[0]
    if path['monitor_path'].casefold() != monitors[0]['interface_id'].casefold():
        return {'status':'unresolved','reason':'The GDI and CCD monitor identities disagree.'}
    if path['source'] != {'width':current['width'],'height':current['height'],**(position or {})}:
        return {'status':'unresolved','reason':'The GDI and CCD source modes disagree.'}
    if path['desktop_refresh'] is None or path['signal_vsync'] is None:
        return {'status':'unresolved','reason':'Windows did not report valid refresh fractions.'}
    return {'status':'observed',**path}
