"""Offline checks for the settings agent: run with `python -m pytest tests` from the repo root."""
import asyncio
import contextlib
import ctypes as ct
import itertools
import sys
import types

import pytest

from automation.agents.settings_agent import ACTIONS, SettingsAgent
from automation.agents.settings_ops import ActionError, control_panel, displays, radios, system, ui


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


def test_app_volume_changes_one_app_and_reads_back(monkeypatch):
    class Session:
        def __init__(self, name, stuck=False):
            self.name, self.playing, self.level, self.muted, self.stuck = name, True, 100, False, stuck

        def read(self):
            return self.level, self.muted

        def write(self, level, muted):
            if not self.stuck:
                self.level = self.level if level is None else level
                self.muted = self.muted if muted is None else muted

    sessions = [Session('chrome'), Session('chrome'), Session('Spotify'), Session('steam'), Session('steamwebhelper', stuck=True)]
    monkeypatch.setattr(system, '_app_sessions', lambda: contextlib.nullcontext(sessions))
    agent = SettingsAgent()
    done = agent.execute('set_app_volume', {'app': 'Chrome', 'level': 30})
    assert done['status'] == 'success' and done['data']['volume'] == 30
    assert [session.level for session in sessions] == [30, 30, 100, 100, 100]  # both chrome sessions, nothing else
    assert agent.execute('set_app_mute', {'app': 'spot', 'state': 'on'})['data']['muted'] is True
    assert agent.execute('set_app_volume', {'app': 'steam', 'level': 5})['status'] == 'success' and sessions[3].level == 5  # exact name wins
    assert [row['app'] for row in agent.execute('list_app_volumes')['data']['apps']] == ['chrome', 'Spotify', 'steam', 'steamwebhelper']
    ambiguous = agent.execute('set_app_volume', {'app': 's', 'level': 1})
    assert ambiguous['status'] == 'failure' and 'Spotify' in ambiguous['details']
    stuck = agent.execute('set_app_volume', {'app': 'webhelper', 'level': 10})
    assert stuck['status'] == 'failure' and 'did not apply' in stuck['details']
    assert agent.execute('set_app_volume', {'app': 'chrome'})['status'] == 'failure'  # no level
    assert agent.execute('set_app_volume', {'app': ' ', 'level': 10})['status'] == 'failure'


FAKE_TASKS = [{'name': 'Choose a power plan', 'group': 'Power Options', 'path': 'P1'},
              {'name': 'Edit power plan', 'group': 'Power Options', 'path': 'P2'},
              {'name': 'Change when the computer sleeps', 'group': 'Power Options', 'path': 'P3'},
              {'name': 'Change mouse settings', 'group': 'Mouse', 'path': 'P4'},
              {'name': 'Change mouse settings', 'group': 'Mouse', 'path': 'P4'}]


@pytest.fixture
def fake_panel(monkeypatch):
    opened = []
    monkeypatch.setattr(control_panel, '_tasks', lambda: FAKE_TASKS)
    monkeypatch.setattr(control_panel, '_invoke', opened.append)
    snapshots = itertools.cycle([{}, {7: ('CabinetWClass', 'Power Options')}])  # before / after each open
    monkeypatch.setattr(ui, 'top_windows', lambda: next(snapshots))
    monkeypatch.setattr(ui, 'foreground', lambda: 0)
    return opened


def test_control_panel_list_filters_and_hides_paths(fake_panel):
    everything = SettingsAgent().execute('list_control_panel_tasks')['data']
    assert everything['count'] == 4 and all(set(t) == {'name', 'group'} for t in everything['tasks'])
    assert SettingsAgent().execute('list_control_panel_tasks', {'query': 'POWER plan'})['data']['count'] == 2
    assert SettingsAgent().execute('list_control_panel_tasks', {'query': 'mouse'})['data']['tasks'][0]['group'] == 'Mouse'


def test_control_panel_open_exact_fuzzy_ambiguous_missing(fake_panel):
    agent = SettingsAgent()
    assert agent.execute('open_control_panel_task', {'name': 'edit POWER plan'})['data']['opened'] == 'Edit power plan'
    assert agent.execute('open_control_panel_task', {'name': 'Change mouse settings'})['data']['opened'] == 'Change mouse settings'
    assert agent.execute('open_control_panel_task', {'name': 'Change mouse setings'})['data']['opened'] == 'Change mouse settings'
    assert fake_panel == ['P2', 'P4', 'P4']
    ambiguous = agent.execute('open_control_panel_task', {'name': 'power'})
    assert ambiguous['status'] == 'failure' and 'Edit power plan' in ambiguous['details']
    assert agent.execute('open_control_panel_task', {'name': 'qqqqzzzz'})['status'] == 'failure'
    assert len(fake_panel) == 3


def test_control_panel_path_goes_through_environment(monkeypatch):
    calls = []
    monkeypatch.setattr(system, '_powershell', lambda script, timeout=20, env=None: calls.append((script, env)) or (0, ''))
    control_panel._invoke("P'; evil")
    script, env = calls[0]
    assert env == {'AURA_CP_PATH': "P'; evil"} and 'evil' not in script and '$env:AURA_CP_PATH' in script


POWERCFG = """Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  GUID Alias: SCHEME_BALANCED
  Subgroup GUID: 7516b95f-f776-4464-8c53-06167f40cc99  (Display)
    Power Setting GUID: 3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e  (Turn off display after)
      GUID Alias: VIDEOIDLE
      Minimum Possible Setting: 0x00000000
      Maximum Possible Setting: 0xffffffff
      Possible Settings increment: 0x00000001
      Possible Settings units: Seconds
    Current AC Power Setting Index: 0x{ac:08x}
    Current DC Power Setting Index: 0x{dc:08x}
"""


def test_power_timeouts_parse_set_and_readback_mismatch(monkeypatch):
    state = {'monitor-timeout-ac': 600, 'monitor-timeout-dc': 300, 'standby-timeout-ac': 0, 'standby-timeout-dc': 900}

    def fake_cmd(args, timeout=20, env=None):
        if args[1] == '/query':
            key = 'monitor' if args[3] == 'SUB_VIDEO' else 'standby'
            return 0, POWERCFG.format(ac=state[key + '-timeout-ac'], dc=state[key + '-timeout-dc'])
        if not frozen:
            state[args[2]] = int(args[3]) * 60
        return 0, ''

    frozen = False
    monkeypatch.setattr(system, '_cmd', fake_cmd)
    assert system.get_power_timeouts() == {'display_plugged_in': 10, 'display_battery': 5, 'sleep_plugged_in': 0, 'sleep_battery': 15}
    assert SettingsAgent().execute('set_power_timeout', {'what': 'sleep', 'power': 'battery', 'minutes': 20})['data']['sleep_battery'] == 20
    assert state['standby-timeout-dc'] == 1200
    frozen = True
    stuck = SettingsAgent().execute('set_power_timeout', {'what': 'display', 'power': 'plugged_in', 'minutes': 1})
    assert stuck['status'] == 'failure' and 'did not change' in stuck['details']
    assert SettingsAgent().execute('set_power_timeout', {'what': 'display', 'power': 'plugged_in', 'minutes': 601})['status'] == 'failure'


def test_open_task_returns_new_retitled_or_settings_window(fake_panel, monkeypatch):
    assert SettingsAgent().execute('open_control_panel_task', {'name': 'edit power plan'})['data']['window'] == 'Power Options'
    before = {7: ('CabinetWClass', 'Power Options'), 9: ('ApplicationFrameWindow', 'Settings')}
    for after, wanted in (({**before, 8: ('#32770', 'Mouse Properties')}, 'Mouse Properties'),  # new window
                          ({**before, 7: ('CabinetWClass', 'Edit Plan Settings')}, 'Edit Plan Settings'),  # reused Explorer window
                          ({**before, 10: ('ApplicationFrameWindow', 'Settings')}, 'Settings')):  # Settings app
        snapshots = iter([before, after])
        monkeypatch.setattr(ui, 'top_windows', lambda: next(snapshots))
        assert control_panel.open_task('Change mouse settings')['window'] == wanted


class FakeWindow:
    def __init__(self, title, cls, children=()):
        self.Name, self.ClassName, self.NativeWindowHandle, self._children = title, cls, hash(title), list(children)

    def GetChildren(self):
        return self._children


def fake_desktop(monkeypatch, windows):
    monkeypatch.setitem(sys.modules, 'uiautomation', types.SimpleNamespace(GetRootControl=lambda: FakeWindow('', '', windows)))


def test_window_resolution_none_exact_ambiguous_missing(monkeypatch):
    settings, sound, sound_set, mouse, other = (FakeWindow('Settings', 'ApplicationFrameWindow'), FakeWindow('Sound', '#32770'),
                                                FakeWindow('Sound Settings', 'CabinetWClass'), FakeWindow('Mouse Properties', '#32770'),
                                                FakeWindow('Notepad', 'Notepad'))
    fake_desktop(monkeypatch, [other, sound_set, sound, mouse, settings])
    assert ui._window() is settings and ui._window('settings') is settings  # no title: the Settings app
    assert ui._window('mouse prop') is mouse  # substring, casefold
    assert ui._window('sound') is sound  # exact title beats the earlier, foreground-most partial match
    fake_desktop(monkeypatch, [sound_set, mouse, FakeWindow('Sound Mixer', '#32770')])
    assert ui._window('sound') is sound_set  # ambiguous: foreground-most
    with pytest.raises(ActionError, match='Sound Settings.*Mouse Properties') as error:
        ui._window('printers')
    assert 'Notepad' not in str(error.value)


def test_window_param_bypasses_settings_app(monkeypatch):
    calls = []
    monkeypatch.setattr(ui, '_window', lambda title=None: None)  # Settings is not open
    monkeypatch.setattr(ui, 'open_page', lambda page: calls.append(page))
    monkeypatch.setattr(ui, 'get_toggle', lambda name, window=None: calls.append((name, window)) or {'name': name, 'state': 'on'})
    agent = SettingsAgent()
    assert agent.execute('get_toggle', {'window': 'Mouse Properties', 'name': 'Display pointer trails'})['status'] == 'success'
    assert calls == [('Display pointer trails', 'Mouse Properties')]
    assert agent.execute('get_toggle', {'name': 'x'})['status'] == 'failure'  # no window, no page: Settings is required
    assert all('window' in ACTIONS[name][2] for name in ('read_page', 'get_toggle', 'set_toggle', 'select_option', 'set_value', 'click'))


class FakeEdit:
    ControlTypeName, Name, AutomationId, IsOffscreen = 'EditControl', 'Lines', '', False

    def __init__(self, sticks):
        self.value, self.sticks = '3', sticks

    def GetPattern(self, pattern_id):
        return self if pattern_id == 'value' else None

    Value = property(lambda self: self.value)

    def SetValue(self, text):
        if self.sticks:
            self.value = text


def test_set_value_reads_back_and_reports_mismatch(monkeypatch):
    edit = FakeEdit(sticks=True)
    patterns = types.SimpleNamespace(RangeValuePattern='range', ValuePattern='value', SelectionPattern='selection')
    monkeypatch.setitem(sys.modules, 'uiautomation', types.SimpleNamespace(PatternId=patterns))
    monkeypatch.setattr(ui, '_controls', lambda window=None: [edit])
    assert SettingsAgent().execute('set_value', {'window': 'Mouse Properties', 'name': 'lines', 'value': 5})['data']['value'] == '5'
    edit.sticks = False
    refused = SettingsAgent().execute('set_value', {'window': 'Mouse Properties', 'name': 'lines', 'value': 9})
    assert refused['status'] == 'failure' and 'is 5 after setting 9' in refused['details']


def test_elevated_window_is_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, 'uiautomation', types.SimpleNamespace())
    monkeypatch.setattr(ui, '_window', lambda title=None: FakeWindow('Services', '#32770'))
    result = SettingsAgent().execute('read_page', {'window': 'Services'})
    assert result['status'] == 'failure' and 'administrator rights' in result['details']
