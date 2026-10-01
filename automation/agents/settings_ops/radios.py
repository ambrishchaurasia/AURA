"""Bluetooth / Wi-Fi radio state and Bluetooth presence checks through Windows Runtime."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

from . import ActionError

LABELS = {'bluetooth': 'Bluetooth', 'wifi': 'Wi-Fi'}


def _run(coro):
    # Callers may already be inside an event loop (MCP worker); a fresh thread never is.
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _radio(kind):
    from winrt.windows.devices.radios import Radio, RadioKind
    wanted = {'bluetooth': RadioKind.BLUETOOTH, 'wifi': RadioKind.WI_FI}[kind]
    radios = [radio for radio in await Radio.get_radios_async() if radio.kind == wanted]
    if not radios:
        raise ActionError(f'Windows did not report a {LABELS[kind]} radio.')
    return radios[0]


async def _state(kind):
    return {'radio': kind, 'radio_state': (await _radio(kind)).state.name.lower()}


def get_radio(kind):
    return _run(_state(kind))


async def _set(kind, on):
    from winrt.windows.devices.radios import Radio, RadioAccessStatus, RadioState
    radio, wanted = await _radio(kind), RadioState.ON if on else RadioState.OFF
    if radio.state != wanted:
        for request in (Radio.request_access_async, lambda: radio.set_state_async(wanted)):
            access = await request()
            if access != RadioAccessStatus.ALLOWED:
                raise ActionError(f'Windows denied {LABELS[kind]} radio control ({access.name.lower().replace("_", " ")}). '
                                  f'{LABELS[kind]} was not turned {"on" if on else "off"}.')
    # Separate read: report what Windows says now, not what was requested.
    state = await _state(kind)
    if state['radio_state'] != ('on' if on else 'off'):
        raise ActionError(f'{LABELS[kind]} is still {state["radio_state"]} after the request.')
    return state


def set_radio(kind, on):
    return _run(_set(kind, on))


async def _restart(kind):
    await _set(kind, False)
    await asyncio.sleep(2)
    return await _set(kind, True)


def restart_radio(kind):
    return _run(_restart(kind))


async def _find_device(name, scan):
    from winrt.windows.devices.enumeration import DeviceInformation, DeviceInformationKind
    from winrt.system import unbox_boolean
    state = await _state('bluetooth')
    if state['radio_state'] != 'on':
        raise ActionError('Bluetooth is off, so AURA cannot check for a nearby device.')
    selector = 'System.Devices.Aep.ProtocolId:="{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"'
    if not scan:  # Skip the ~30 s radio inquiry: paired devices only, presence as Windows last saw it.
        selector += (' AND (System.Devices.Aep.IsPaired:=System.StructuredQueryType.Boolean#True'
                     ' OR System.Devices.Aep.Bluetooth.IssueInquiry:=System.StructuredQueryType.Boolean#False)')
    properties = ['System.Devices.Aep.IsPresent', 'System.Devices.Aep.IsConnected']
    try:
        devices = await DeviceInformation.find_all_async_with_kind_aqs_filter_and_additional_properties(
            selector, properties, DeviceInformationKind.ASSOCIATION_ENDPOINT)
    except PermissionError as error:
        raise ActionError('Windows denied Bluetooth device discovery. AURA cannot say whether the device is nearby.') from error
    matches = []
    for device in devices:
        if name.casefold() not in device.name.casefold():
            continue
        # Windows caches paired endpoints. Presence must be explicitly true.
        presence = device.properties.get('System.Devices.Aep.IsPresent')
        connected = device.properties.get('System.Devices.Aep.IsConnected')
        matches.append({'name': device.name, 'present': unbox_boolean(presence) if presence else False,
                        'connected': unbox_boolean(connected) if connected else False,
                        'paired': bool(device.pairing and device.pairing.is_paired)})
    return {'radio_state': state['radio_state'], 'device_name': name, 'matches': matches,
            'nearby': any(item['present'] or item['connected'] for item in matches), 'scanned': scan}


def find_bluetooth_device(name='', scan=False):
    """Empty name lists every known Bluetooth device."""
    return _run(_find_device(name, scan))
