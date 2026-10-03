"""Volume, brightness, theme, power, network and storage through Windows APIs and built-in tools."""
import ctypes as ct
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid

from . import ActionError
from .display_modes import Guid

U32, PTR = ct.c_uint32, ct.c_void_p


def _cmd(args, timeout=20, env=None):
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, errors='replace',
                          creationflags=subprocess.CREATE_NO_WINDOW, env={**os.environ, **env} if env else None)
    return done.returncode, (done.stdout + done.stderr).strip()


def _powershell(script, timeout=20, env=None):
    return _cmd(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], timeout, env)


def _level(value):
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        raise ActionError('level must be a number from 0 to 100.') from None


# ── Volume (Core Audio, raw vtable calls like display_modes) ────────────────

def _guid(text):
    return Guid.from_buffer_copy(uuid.UUID(text).bytes_le)


def _call(pointer, slot, types, *args):
    table = ct.cast(pointer, ct.POINTER(ct.POINTER(PTR))).contents
    code = ct.WINFUNCTYPE(ct.c_int32, PTR, *types)(table[slot])(pointer, *args)
    if code < 0:
        raise ActionError(f'Windows audio call failed (0x{code & 0xffffffff:08x}).')


@contextmanager
def _endpoint_volume():
    """IAudioEndpointVolume of the default playback device."""
    ole = ct.windll.ole32
    ole.CoInitializeEx(None, 0)
    enumerator, device, volume = PTR(), PTR(), PTR()
    try:
        if ole.CoCreateInstance(ct.byref(_guid('bcde0395-e52f-467c-8e3d-c4579291692e')), None, 23,
                                ct.byref(_guid('a95664d2-9614-4f35-a746-de8db63617e6')), ct.byref(enumerator)) < 0:
            raise ActionError('Windows audio device enumeration is unavailable.')
        try:
            _call(enumerator, 4, [U32, U32, ct.POINTER(PTR)], 0, 1, ct.byref(device))  # eRender, eMultimedia
        except ActionError:
            raise ActionError('No audio output device is available.') from None
        _call(device, 3, [ct.POINTER(Guid), U32, PTR, ct.POINTER(PTR)],
              ct.byref(_guid('5cdf2c82-841e-4546-9722-0cf74078229a')), 23, None, ct.byref(volume))
        yield volume
    finally:
        for pointer in (volume, device, enumerator):
            if pointer:
                _call(pointer, 2, [])  # IUnknown::Release
        ole.CoUninitialize()


def _read_volume(volume):
    level, muted = ct.c_float(), ct.c_int32()
    _call(volume, 9, [ct.POINTER(ct.c_float)], ct.byref(level))
    _call(volume, 15, [ct.POINTER(ct.c_int32)], ct.byref(muted))
    return {'volume': round(level.value * 100), 'muted': bool(muted.value)}


def _set_volume(level, muted):
    with _endpoint_volume() as volume:
        if level is not None:
            _call(volume, 7, [ct.c_float, PTR], _level(level) / 100, None)
        if muted is not None:
            _call(volume, 14, [ct.c_int32, PTR], int(bool(muted)), None)
        return _read_volume(volume)


def set_volume(level=None, muted=None):
    # Own thread: its COM apartment must not clash with the caller's (UIA, MCP worker).
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(_set_volume, level, muted).result()


def get_volume():
    return set_volume()


# ── Default playback device (Core Audio enumeration + IPolicyConfig) ────────

class _PropKey(ct.Structure):
    _fields_ = [('fmtid', Guid), ('pid', U32)]


def _create(clsid, iid):
    out = PTR()
    if ct.windll.ole32.CoCreateInstance(ct.byref(_guid(clsid)), None, 23, ct.byref(_guid(iid)), ct.byref(out)) < 0:
        raise ActionError('Windows audio device enumeration is unavailable.')
    return out


def _release(pointer):
    if pointer:
        _call(pointer, 2, [])  # IUnknown::Release


def _device_id(device):
    text = PTR()
    _call(device, 5, [ct.POINTER(PTR)], ct.byref(text))  # IMMDevice::GetId
    try:
        return ct.wstring_at(text.value)
    finally:
        ct.windll.ole32.CoTaskMemFree(text)


def _device_name(device):
    store, value = PTR(), (ct.c_ubyte * 24)()  # PROPVARIANT: vt at 0, pointer at 8
    _call(device, 4, [U32, ct.POINTER(PTR)], 0, ct.byref(store))  # OpenPropertyStore(STGM_READ)
    try:
        key = _PropKey(_guid('a45c254e-df1c-4efd-8020-67d146a850e0'), 14)  # PKEY_Device_FriendlyName
        _call(store, 5, [ct.POINTER(_PropKey), PTR], ct.byref(key), ct.byref(value))
        pointer = PTR.from_buffer(value, 8).value
        return ct.wstring_at(pointer) if value[0] == 31 and pointer else ''  # VT_LPWSTR
    finally:
        ct.windll.ole32.PropVariantClear(ct.byref(value))
        _release(store)


def _devices(enumerator):
    """[(id, friendly name, is_default)] of active playback endpoints."""
    collection, default, count = PTR(), PTR(), U32()
    _call(enumerator, 3, [U32, U32, ct.POINTER(PTR)], 0, 1, ct.byref(collection))  # eRender, DEVICE_STATE_ACTIVE
    try:
        try:
            _call(enumerator, 4, [U32, U32, ct.POINTER(PTR)], 0, 1, ct.byref(default))
            default_id = _device_id(default)
        except ActionError:
            default_id = None
        finally:
            _release(default)
        _call(collection, 3, [ct.POINTER(U32)], ct.byref(count))
        found = []
        for index in range(count.value):
            device = PTR()
            _call(collection, 4, [U32, ct.POINTER(PTR)], index, ct.byref(device))
            try:
                found.append((_device_id(device), _device_name(device)))
            finally:
                _release(device)
        return [(device_id, name, device_id == default_id) for device_id, name in found]
    finally:
        _release(collection)


def _audio(match=None):
    ole = ct.windll.ole32
    ole.CoInitializeEx(None, 0)
    enumerator = PTR()
    try:
        enumerator = _create('bcde0395-e52f-467c-8e3d-c4579291692e', 'a95664d2-9614-4f35-a746-de8db63617e6')
        devices = _devices(enumerator)
        if match is not None:
            hits = [device for device in devices if str(match).casefold() in device[1].casefold()]
            if len(hits) != 1:
                raise ActionError(f"No single audio device matches '{match}'. Available: {', '.join(d[1] for d in devices)}.")
            # IPolicyConfig is undocumented and may break on a future Windows build.
            policy = _create('870af99c-171d-4f9e-af0d-e63df40c2bc9', 'f8679f50-850a-41cf-9c72-430f290290c8')
            try:
                for role in (0, 1, 2):  # console, multimedia, communications
                    _call(policy, 13, [ct.c_wchar_p, U32], hits[0][0], role)  # SetDefaultEndpoint
            finally:
                _release(policy)
            devices = _devices(enumerator)
            if not any(device_id == hits[0][0] and default for device_id, _, default in devices):
                raise ActionError(f"The default audio device did not change to '{hits[0][1]}'.")
        return {'devices': [{'name': name, 'default': default} for _, name, default in devices]}
    finally:
        _release(enumerator)
        ole.CoUninitialize()


def list_audio_devices(match=None):
    with ThreadPoolExecutor(1) as pool:  # own COM apartment, like set_volume
        return pool.submit(_audio, match).result()


def set_audio_device(name):
    if not name:
        raise ActionError('name of the audio device is required.')
    return list_audio_devices(str(name or ''))


# ── Brightness (WMI; built-in laptop panels only) ───────────────────────────

def get_brightness():
    code, out = _powershell('(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop).CurrentBrightness')
    if code or not out.split()[0].isdigit():
        raise ActionError('This display does not expose brightness control to Windows (external monitors usually do not).')
    return {'brightness': int(out.split()[0])}


def set_brightness(level):
    level = _level(level)
    code, _ = _powershell('Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | '
                          f'Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness={level}}} -ErrorAction Stop')
    if code:
        raise ActionError('This display does not expose brightness control to Windows (external monitors usually do not).')
    return get_brightness()


# ── Theme ───────────────────────────────────────────────────────────────────

THEME_KEY = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'


def get_theme():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY) as key:
        return {'theme': 'light' if winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] else 'dark'}


def set_theme(mode):
    import winreg
    if mode not in ('dark', 'light'):
        raise ActionError("mode must be 'dark' or 'light'.")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY, 0, winreg.KEY_SET_VALUE) as key:
        for name in ('AppsUseLightTheme', 'SystemUsesLightTheme'):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(mode == 'light'))
    # Tell running apps and the shell to repaint: WM_SETTINGCHANGE to HWND_BROADCAST.
    ct.windll.user32.SendMessageTimeoutW(0xffff, 0x1a, 0, 'ImmersiveColorSet', 2, 2000, None)
    return get_theme()


# ── Power ───────────────────────────────────────────────────────────────────

class _PowerStatus(ct.Structure):
    _fields_ = [('ac', ct.c_ubyte), ('flag', ct.c_ubyte), ('percent', ct.c_ubyte), ('saver', ct.c_ubyte),
                ('seconds_left', U32), ('seconds_full', U32)]


def get_battery():
    status = _PowerStatus()
    if not ct.windll.kernel32.GetSystemPowerStatus(ct.byref(status)):
        raise ActionError('Windows did not report power status.')
    if status.flag & 128 or status.percent == 255:
        return {'battery': False, 'plugged_in': True}
    return {'battery': True, 'percent': status.percent, 'plugged_in': status.ac == 1,
            'charging': bool(status.flag & 8), 'battery_saver': bool(status.saver),
            'minutes_left': None if status.seconds_left == 0xffffffff else status.seconds_left // 60}


def list_power_plans():
    _, out = _cmd(['powercfg', '/list'])
    plans = [{'guid': guid, 'name': name, 'active': bool(star)}
             for guid, name, star in re.findall(r'([0-9a-f-]{36})\s+\((.+?)\)(\s*\*)?', out)]
    if not plans:
        raise ActionError('powercfg did not list any power plans.')
    return {'plans': plans}


def set_power_plan(name):
    plans = list_power_plans()['plans']
    matches = [plan for plan in plans if str(name).casefold() in plan['name'].casefold()]
    if len(matches) != 1:
        raise ActionError(f"No single power plan matches '{name}'. Available: {', '.join(p['name'] for p in plans)}.")
    code, out = _cmd(['powercfg', '/setactive', matches[0]['guid']])
    if code:
        raise ActionError(f'powercfg refused the change: {out}')
    return list_power_plans()


_TIMEOUTS = {'display': ('SUB_VIDEO', 'VIDEOIDLE', 'monitor-timeout'), 'sleep': ('SUB_SLEEP', 'STANDBYIDLE', 'standby-timeout')}


def get_power_timeouts():
    """Minutes before the display turns off / the PC sleeps, plugged in and on battery; 0 means never."""
    found = {}
    for what, (sub, setting, _) in _TIMEOUTS.items():
        _, out = _cmd(['powercfg', '/query', 'SCHEME_CURRENT', sub, setting])
        # The last two 0x values are the current AC and DC indexes (seconds), after the possible-settings block.
        values = re.findall(r'0x([0-9a-fA-F]{8})\b', out)
        if len(values) < 2:
            raise ActionError(f'powercfg did not report the {what} timeout (this plan may not have it).')
        found[what] = [int(value, 16) // 60 for value in values[-2:]]
    return {'display_plugged_in': found['display'][0], 'display_battery': found['display'][1],
            'sleep_plugged_in': found['sleep'][0], 'sleep_battery': found['sleep'][1]}


def set_power_timeout(what, power, minutes):
    if what not in _TIMEOUTS or power not in ('plugged_in', 'battery'):
        raise ActionError("what must be 'display' or 'sleep' and power must be 'plugged_in' or 'battery'.")
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = -1
    if not 0 <= minutes <= 600:
        raise ActionError('minutes must be a number from 0 to 600 (0 = never).')
    code, out = _cmd(['powercfg', '/change', f"{_TIMEOUTS[what][2]}-{'ac' if power == 'plugged_in' else 'dc'}", str(minutes)])
    if code:
        raise ActionError(f'powercfg refused the change: {out}')
    now = get_power_timeouts()
    if now[f'{what}_{power}'] != minutes:
        raise ActionError(f"The {what} timeout did not change to {minutes} minutes (it is {now[f'{what}_{power}']}); a policy may control it.")
    return now


# ── Network ─────────────────────────────────────────────────────────────────

def diagnose_network():
    """Read-only checks, in the order a person would troubleshoot."""
    _, wifi = _cmd(['netsh', 'wlan', 'show', 'interfaces'])
    internet = _cmd(['ping', '-n', '1', '-w', '2000', '1.1.1.1'])[0] == 0
    try:
        socket.getaddrinfo('www.microsoft.com', 443)
        dns = True
    except OSError:
        dns = False
    if internet and dns:
        advice = 'Connection looks healthy.'
    elif internet:
        advice = 'Internet is reachable but name lookup fails: run flush_dns, then check DNS / proxy / VPN settings.'
    else:
        advice = 'No internet: check Wi-Fi is on and connected (get_wifi, list_wifi_networks), then try restart_wifi.'
    return {'internet_reachable': internet, 'dns_working': dns, 'advice': advice, 'wifi_interface': wifi}


def flush_dns():
    code, out = _cmd(['ipconfig', '/flushdns'])
    if code:
        raise ActionError(f'ipconfig could not flush DNS: {out}')
    return {'flushed': True}


def list_wifi_networks():
    code, out = _cmd(['netsh', 'wlan', 'show', 'networks'])
    if code:
        raise ActionError(f'Windows could not list Wi-Fi networks (is Wi-Fi on? is location permission granted?): {out}')
    return {'networks': re.findall(r'^SSID \d+ : (.+)$', out, re.M), 'text': out}


def connect_wifi(name):
    """Saved networks only; AURA never handles Wi-Fi passwords."""
    if not name:
        raise ActionError('name of a saved Wi-Fi network is required.')
    code, out = _cmd(['netsh', 'wlan', 'connect', f'name={name}'])
    if code:
        raise ActionError(f"Could not connect to '{name}' (only networks already saved on this PC work): {out}")
    return {'requested': name, 'message': out}


# ── Storage / system ────────────────────────────────────────────────────────

def storage_status():
    drives = []
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        if ct.windll.kernel32.GetDriveTypeW(f'{letter}:\\') == 3:  # DRIVE_FIXED
            usage = shutil.disk_usage(f'{letter}:\\')
            drives.append({'drive': f'{letter}:', 'total_gb': round(usage.total / 2**30, 1),
                           'free_gb': round(usage.free / 2**30, 1), 'used_percent': round(usage.used * 100 / usage.total)})
    return {'drives': drives}


def system_info():
    ct.windll.kernel32.GetTickCount64.restype = ct.c_uint64
    return {'computer': platform.node(), 'os': f"Windows {11 if sys.getwindowsversion().build >= 22000 else platform.release()} ({platform.version()})",
            'processor': platform.processor(), 'uptime_hours': round(ct.windll.kernel32.GetTickCount64() / 3.6e6, 1),
            'local_time': time.strftime('%Y-%m-%d %H:%M')}
