"""Windows display inventory, plus a refresh-rate change (ChangeDisplaySettingsExW) that is tested, applied and read back."""
import ctypes as ct
import hashlib
import json
import os
from fractions import Fraction

from . import ActionError
from . import display_config, display_modes


# Display form of the documented DEVMODEW unions, using fixed-width Win32 types.
class DisplayMode(ct.Structure):
    _fields_ = [('device_name',ct.c_wchar*32), ('spec_version',ct.c_uint16),
                ('driver_version',ct.c_uint16), ('size',ct.c_uint16), ('extra',ct.c_uint16),
                ('fields',ct.c_uint32), ('x',ct.c_int32), ('y',ct.c_int32),
                ('orientation',ct.c_uint32), ('fixed_output',ct.c_uint32),
                ('color',ct.c_int16), ('duplex',ct.c_int16), ('y_resolution',ct.c_int16),
                ('tt_option',ct.c_int16), ('collate',ct.c_int16), ('form_name',ct.c_wchar*32),
                ('log_pixels',ct.c_uint16), ('bits_per_pixel',ct.c_uint32),
                ('width',ct.c_uint32), ('height',ct.c_uint32), ('display_flags',ct.c_uint32),
                ('frequency',ct.c_uint32), ('icm_method',ct.c_uint32), ('icm_intent',ct.c_uint32),
                ('media_type',ct.c_uint32), ('dither_type',ct.c_uint32),
                ('reserved1',ct.c_uint32), ('reserved2',ct.c_uint32),
                ('panning_width',ct.c_uint32), ('panning_height',ct.c_uint32)]


class DisplayDevice(ct.Structure):
    _fields_ = [('size',ct.c_uint32), ('name',ct.c_wchar*32), ('description',ct.c_wchar*128),
                ('flags',ct.c_uint32), ('device_id',ct.c_wchar*128), ('key',ct.c_wchar*128)]


class WindowsDisplays:
    def __init__(self):
        if os.name != 'nt':
            raise ActionError('Display inspection requires a Windows desktop session.')
        if ct.sizeof(DisplayMode) != 220 or ct.sizeof(DisplayDevice) != 840:
            raise ActionError('Unsupported Windows display structure layout.')
        self.api = ct.WinDLL('user32', use_last_error=True)
        self.api.EnumDisplayDevicesW.argtypes = [ct.c_wchar_p,ct.c_uint32,ct.POINTER(DisplayDevice),ct.c_uint32]
        self.api.EnumDisplayDevicesW.restype = ct.c_int32
        self.api.EnumDisplaySettingsExW.argtypes = [ct.c_wchar_p,ct.c_uint32,ct.POINTER(DisplayMode),ct.c_uint32]
        self.api.EnumDisplaySettingsExW.restype = ct.c_int32
        self.api.ChangeDisplaySettingsExW.argtypes = [ct.c_wchar_p,ct.POINTER(DisplayMode),ct.c_void_p,ct.c_uint32,ct.c_void_p]
        self.api.ChangeDisplaySettingsExW.restype = ct.c_int32
        display_config.configure(self.api)

    def timings(self, check):
        return display_config.read_paths(self.api,check)

    def catalogue(self, check):
        return display_modes.read_catalogue(check)

    def device(self, parent, index):
        value = DisplayDevice()
        value.size = ct.sizeof(value)
        # Interface IDs distinguish physical monitor associations, not just labels.
        return value if self.api.EnumDisplayDevicesW(parent,index,ct.byref(value),1 if parent else 0) else None

    def mode(self, device, index):
        value = DisplayMode()
        value.size = ct.sizeof(value)
        # Flags zero: monitor-compatible modes in the current orientation only.
        return value if self.api.EnumDisplaySettingsExW(device,index,ct.byref(value),0) else None


def _enumerate(read, limit, check):
    for index in range(limit+1):
        check()
        value = read(index)
        if value is None:
            return
        if index == limit:
            raise ActionError('Display enumeration exceeded its limit; no complete mode list is available.')
        yield value


def _mode(value):
    if value is None or value.fields & 0x1c0000 != 0x1c0000 or not (value.width and value.height and value.bits_per_pixel):
        raise ActionError('Windows did not report a complete display mode.')
    return {'width':value.width, 'height':value.height, 'bits_per_pixel':value.bits_per_pixel,
            'nominal_hz':value.frequency if value.fields & 0x400000 and value.frequency > 1 else None,
            'orientation':value.orientation if value.fields & 0x80 else 0,
            'fixed_output':value.fixed_output if value.fields & 0x20000000 else 0,
            'display_flags':value.display_flags if value.fields & 0x200000 else 0}


def read_displays(check, *, api=None):
    api = api or WindowsDisplays()
    displays = []
    for adapter in _enumerate(lambda index:api.device(None,index),32,check):
        if not adapter.flags & 1 or adapter.flags & 8:  # Attached desktop, not a mirroring driver.
            continue
        monitors = sorted(({'name':monitor.description,'interface_id':monitor.device_id}
                           for monitor in _enumerate(lambda index:api.device(adapter.name,index),16,check)
                           if monitor.flags & 1),key=lambda item:(item['interface_id'],item['name']))
        check()
        raw = api.mode(adapter.name,0xffffffff)  # ENUM_CURRENT_SETTINGS
        current = _mode(raw)
        compatible = set()
        for mode in _enumerate(lambda index:api.mode(adapter.name,index),4096,check):
            choice = _mode(mode)
            if all(choice[key] == current[key] for key in current if key != 'nominal_hz') and choice['nominal_hz']:
                compatible.add(choice['nominal_hz'])
        identity = [adapter.name,adapter.device_id,[monitor['interface_id'] for monitor in monitors]]
        digest = hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()
        displays.append({'display_id':'display_'+digest, 'device_name':adapter.name,
                         'adapter_name':adapter.description, 'primary':bool(adapter.flags & 4),
                         'remote':bool(adapter.flags & 0x4000000), 'monitors':monitors,
                         'position':{'x':raw.x,'y':raw.y} if raw.fields & 0x20 else None,
                         'current':current, 'compatible_nominal_hz':sorted(compatible)})
    if not displays:
        raise ActionError('Windows did not report an attached desktop display in this session.')
    try:
        paths = api.timings(check)
    except ActionError as error:
        for display in displays:
            display['active_timing'] = {'status':'unavailable','reason':str(error)}
    else:
        for display in displays:
            display['active_timing'] = display_config.match_timing(paths,display['device_name'],display['monitors'],display['current'],display['position'])
    try:
        catalogue = api.catalogue(check)
    except ActionError as error:
        for display in displays:
            display['alternate_modes'] = {'status':'unavailable','reason':str(error)}
    else:
        for display in displays:
            display['alternate_modes'] = display_modes.match_catalogue(catalogue,display)
    displays.sort(key=lambda item:item['display_id'])
    return {'displays':displays, 'text':'\n\n'.join(describe_display(display) for display in displays)+'\n\nNo settings changed. GDI choices are nominal Hz; DXGI candidates retain precise fractions within their declared format scope.',
            'rate_precision':'GDI choices are nominal integer Hz. DXGI candidates and observed active CCD timings retain exact fractions; desktop refresh and signal VSync may differ with dynamic refresh or remote display timing. DXGI format-scoped candidates do not establish preservation of desktop color/HDR. These are reported configuration values, not measured instantaneous rates.',
            'mode_scope':'Current resolution, bit depth, orientation, display flags and scaling mode.',
            'applied':False}


def preview_refresh(inventory, display_id, nominal_hz):
    matches = [display for display in inventory['displays'] if display['display_id'] == display_id]
    if len(matches) != 1:
        raise ActionError('That display is no longer uniquely identified. Inspect connected displays again.')
    display = matches[0]
    eligible = (not display['remote'] and len(display['monitors']) == 1
                and bool(display['monitors'][0]['interface_id']) and display['current']['nominal_hz'] is not None)
    supported = eligible and nominal_hz in display['compatible_nominal_hz']
    status = ('already_current' if nominal_hz == display['current']['nominal_hz'] else 'available') if supported else 'unresolved_display' if not eligible else 'unsupported_rate'
    conclusion = {'already_current':f'The current nominal setting is already {nominal_hz} Hz.',
                  'available':f'{nominal_hz} Hz is an available nominal choice at the current resolution.',
                  'unresolved_display':'A change cannot be proposed because this physical display is not uniquely resolved.',
                  'unsupported_rate':f'{nominal_hz} Hz is not available while retaining the current resolution and mode.'}[status]
    return {'display':display, 'requested_nominal_hz':nominal_hz, 'supported':supported,
            'text':describe_display(display)+'\n\n'+conclusion+' No settings changed. Applying a reviewed change is not available yet.',
            'proposed':{**display['current'],'nominal_hz':nominal_hz} if supported else None,
            'status':status,
            'rate_precision':inventory['rate_precision'], 'applied':False,
            'message':'Inspection only. Applying a mode with confirmation and revert handling is not implemented yet.'}


def set_refresh_rate(display_id, nominal_hz):
    nominal_hz = int(nominal_hz)
    inventory = read_displays(lambda: None)
    preview = preview_refresh(inventory, display_id, nominal_hz)
    if preview['status'] == 'already_current':
        return {**preview['display'], 'previous_nominal_hz': nominal_hz}
    if preview['status'] != 'available':
        raise ActionError(preview['text'].splitlines()[-1].split(' No settings changed')[0])
    api, device = WindowsDisplays(), preview['display']['device_name']
    previous = preview['display']['current']['nominal_hz']
    mode = api.mode(device, 0xffffffff)  # ENUM_CURRENT_SETTINGS
    mode.frequency = nominal_hz
    mode.fields |= 0x5c0000  # DM_DISPLAYFREQUENCY | DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL
    # CDS_TEST first; only a successful test is applied (CDS_UPDATEREGISTRY).
    for flag in (2, 1):
        if api.api.ChangeDisplaySettingsExW(device, ct.byref(mode), None, flag, None) != 0:
            raise ActionError(f'Windows rejected {nominal_hz} Hz (ChangeDisplaySettingsEx {"test" if flag == 2 else "apply"} failed). Nothing was changed.')
    now = next((d for d in read_displays(lambda: None)['displays'] if d['display_id'] == display_id), None)
    if now is None or now['current']['nominal_hz'] != nominal_hz:
        raise ActionError(f'The refresh rate is {now and now["current"]["nominal_hz"]} Hz after the request, not {nominal_hz} Hz.')
    return {**now, 'previous_nominal_hz': previous}


def preview_exact_refresh(inventory, display_id, numerator, denominator):
    matches = [display for display in inventory['displays'] if display['display_id'] == display_id]
    if len(matches) != 1:
        raise ActionError('That display is no longer uniquely identified. Inspect connected displays again.')
    display = matches[0]
    timing, alternate = display['active_timing'], display['alternate_modes']
    if (display['remote'] or len(display['monitors']) != 1 or not display['monitors'][0]['interface_id']
            or timing['status'] != 'observed' or timing.get('advanced_color',{}).get('status') != 'observed'
            or alternate['status'] != 'observed' or timing['dynamic_refresh']):
        raise ActionError('This display lacks a unique, local, fixed-refresh timing and observed color baseline.')
    requested = Fraction(numerator,denominator)
    if not 2 <= requested <= 2000:
        raise ActionError('The requested exact refresh is outside the supported preview range.')
    candidates = [mode for mode in alternate['modes']
                  if Fraction(mode['refresh']['numerator'],mode['refresh']['denominator']) == requested]
    if len(candidates) != 1:
        raise ActionError('That exact refresh is absent or ambiguous in this display’s format-scoped mode list.')
    choice = candidates[0]
    baseline = {key:display[key] for key in ('display_id','device_name','monitors','current','active_timing')}
    proposal = {'display':baseline,'candidate':choice,'format_scope':alternate['scope']}
    proposal_id = hashlib.sha256(json.dumps(proposal,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    current = timing['desktop_refresh']
    already_current = Fraction(current['numerator'],current['denominator']) == requested
    return {'proposal_id':proposal_id,'proposal':proposal,'status':'already_current' if already_current else 'format_scoped_candidate',
            'requested_refresh':choice['refresh'],'applied':False,
            'text':describe_display(display)+f"\n\nExact candidate: {requested.numerator}/{requested.denominator} Hz. "
                   +('The reported desktop refresh already matches. ' if already_current else '')
                   +'This format-scoped candidate has not been validated as a desktop change. No setting changed.'}


def describe_display(display):
    current, timing = display['current'], display['active_timing']
    name = timing.get('monitor_name') or ', '.join(m['name'] for m in display['monitors']) or 'Unidentified monitor'
    lines = [f"{name} · {display['device_name']}"+(' · Primary' if display['primary'] else ''),
             f"{current['width']} × {current['height']} · {current['bits_per_pixel']}-bit · nominal {current['nominal_hz']} Hz" if current['nominal_hz'] else
             f"{current['width']} × {current['height']} · current nominal refresh unknown"]
    if timing['status'] == 'observed':
        lines.append(f"Reported desktop refresh: {timing['desktop_refresh']['hz']} Hz; signal VSync: {timing['signal_vsync']['hz']} Hz.")
        lines.append('Dynamic refresh: '+('on' if timing['dynamic_refresh'] else 'off')+'.')
        color = timing.get('advanced_color',{'status':'unavailable'})
        if color['status'] == 'observed':
            lines.append('Advanced color: '+('enabled' if color['enabled'] else 'off')+
                         f"; {color['bits_per_channel']} bits/channel; encoding {color['encoding']}.")
        else:
            lines.append('Advanced color state could not be read.')
    else:
        lines.append('Precise current timing is unavailable or cannot be matched to this monitor.')
    rates = ', '.join(str(rate) for rate in display['compatible_nominal_hz']) or 'none reported'
    lines.append('Compatible nominal choices at the current resolution and mode: '+rates+'.')
    alternate = display.get('alternate_modes',{})
    if alternate.get('status') == 'observed':
        rates = list(dict.fromkeys(f"{mode['refresh']['numerator']}/{mode['refresh']['denominator']} Hz (≈{mode['refresh']['hz']} Hz)" for mode in alternate['modes']))
        lines.append('Precise DXGI candidates (RGBA8, current resolution): '+(', '.join(rates) or 'none reported')+'. Desktop color/HDR preservation is not yet validated.')
    else:
        lines.append('Precise alternate modes are unavailable or cannot be matched to this display.')
    return '\n'.join(lines)
