"""Offline checks for the settings agent: run with `python -m pytest tests` from the repo root."""
import asyncio
import ctypes as ct
import sys
import types

import pytest

from automation.agents.settings_agent import ACTIONS, SettingsAgent
from automation.agents.settings_ops import ActionError, displays, radios, system, ui


class FakeRadio:
    def __init__(self, kind, state, allow=True):
        self.kind, self.state, self.allow = kind, state, allow

    async def set_state_async(self, state):
        if self.allow:
            self.state = state
        return 'ALLOWED' if self.allow else types.SimpleNamespace(name='DENIED_BY_SYSTEM')


@pytest.fixture
def fake_winrt(monkeypatch):
    """Stand-in for winrt.windows.devices.radios with one Bluetooth radio."""
    state = types.SimpleNamespace(ON=types.SimpleNamespace(name='ON'), OFF=types.SimpleNamespace(name='OFF'))
    radio = FakeRadio('BT', state.ON)

    async def get_radios_async():
        return [radio]

    async def request_access_async():
        return 'ALLOWED'

    module = types.SimpleNamespace(
        Radio=types.SimpleNamespace(get_radios_async=get_radios_async, request_access_async=request_access_async),
        RadioKind=types.SimpleNamespace(BLUETOOTH='BT', WI_FI='WIFI'), RadioState=state,
        RadioAccessStatus=types.SimpleNamespace(ALLOWED='ALLOWED'))
    monkeypatch.setitem(sys.modules, 'winrt.windows.devices.radios', module)
    monkeypatch.setattr(asyncio, 'sleep', lambda _seconds, _real=asyncio.sleep: _real(0))
    return radio


def test_bluetooth_turns_off_and_back_on(fake_winrt):
    agent = SettingsAgent()
    off = agent.execute('set_bluetooth', {'state': 'off'})
    assert off['status'] == 'success' and off['data']['radio_state'] == 'off'
    assert agent.execute('get_bluetooth')['data']['radio_state'] == 'off'
    assert agent.execute('set_bluetooth', {'state': 'on'})['data']['radio_state'] == 'on'
    assert agent.execute('restart_bluetooth')['data']['radio_state'] == 'on'


def test_denied_or_missing_radio_is_reported_not_faked(fake_winrt):
    fake_winrt.allow = False
    agent = SettingsAgent()
    denied = agent.execute('set_bluetooth', {'state': 'off'})
    assert denied['status'] == 'failure' and 'not turned off' in denied['details']
    assert agent.execute('set_wifi', {'state': 'off'})['status'] == 'failure'  # no Wi-Fi radio in the fake
    assert agent.execute('set_bluetooth', {'state': 'maybe'})['status'] == 'failure'


def test_pages_resolve_by_name_typo_and_uri():
    assert ui.resolve_page('WiFi') == ('wi-fi', 'ms-settings:network-wifi')
    assert ui.resolve_page('power and battery')[1] == 'ms-settings:powersleep'
    assert ui.resolve_page('bluetoth')[0] == 'bluetooth'
    assert ui.resolve_page('ms-settings:nightlight')[1] == 'ms-settings:nightlight'
    with pytest.raises(ActionError):
        ui.resolve_page('zzzz')


def test_agent_contract_and_irreversible_guard(monkeypatch):
    agent = SettingsAgent()
    assert set(agent.get_capabilities()['actions']) == set(ACTIONS)
    assert all(name in agent.get_llm_capabilities() for name in ACTIONS)
    assert agent.execute('nope')['status'] == 'failure'
    assert ui.RISKY.search('Reset PC') and ui.RISKY.search('Remove device') and not ui.RISKY.search('Add device')
    assert radios.LABELS.keys() == {'bluetooth', 'wifi'}


def test_refresh_rate_refuses_unsupported_and_audio_name_must_be_unique(monkeypatch):
    mode = {'width': 1920, 'height': 1080, 'bits_per_pixel': 32, 'nominal_hz': 60}
    display = {'display_id': 'd', 'device_name': 'DISPLAY1', 'remote': False, 'primary': True, 'monitors': [{'name': 'M', 'interface_id': 'x'}],
               'current': mode, 'compatible_nominal_hz': [60, 144], 'active_timing': {'status': 'unavailable'}, 'alternate_modes': {}}
    monkeypatch.setattr(displays, 'read_displays', lambda check: {'displays': [display], 'rate_precision': ''})
    refused = SettingsAgent().execute('set_refresh_rate', {'display_id': 'd', 'nominal_hz': 75})
    assert refused['status'] == 'failure' and '75 Hz is not available' in refused['details']
    monkeypatch.setattr(system, '_devices', lambda enumerator: [('1', 'Speakers (A)', True), ('2', 'Speakers (B)', False)])
    monkeypatch.setattr(system, '_create', lambda clsid, iid: ct.c_void_p())
    ambiguous = SettingsAgent().execute('set_audio_device', {'name': 'speakers'})
    assert ambiguous['status'] == 'failure' and 'Speakers (B)' in ambiguous['details']
