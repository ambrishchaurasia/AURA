"""Settings app navigation by ms-settings: URI, plus named-control access for the
long tail of settings that have no direct API. Controls are driven through UIA
patterns (no mouse movement) and every change is read back."""
import difflib
import os
import re
import time

from . import ActionError

PAGES = {
    'home': 'ms-settings:',
    # System
    'display': 'ms-settings:display', 'advanced display': 'ms-settings:display-advanced',
    'graphics': 'ms-settings:display-advancedgraphics', 'night light': 'ms-settings:nightlight',
    'sound': 'ms-settings:sound', 'sound devices': 'ms-settings:sound-devices', 'volume mixer': 'ms-settings:apps-volume',
    'notifications': 'ms-settings:notifications', 'focus': 'ms-settings:quiethours', 'do not disturb': 'ms-settings:notifications',
    'power & battery': 'ms-settings:powersleep', 'battery saver': 'ms-settings:batterysaver',
    'storage': 'ms-settings:storagesense', 'nearby sharing': 'ms-settings:crossdevice',
    'multitasking': 'ms-settings:multitasking', 'activation': 'ms-settings:activation',
    'troubleshoot': 'ms-settings:troubleshoot', 'recovery': 'ms-settings:recovery',
    'projecting to this pc': 'ms-settings:project', 'remote desktop': 'ms-settings:remotedesktop',
    'clipboard': 'ms-settings:clipboard', 'about': 'ms-settings:about',
    # Bluetooth & devices
    'bluetooth': 'ms-settings:bluetooth', 'devices': 'ms-settings:connecteddevices', 'printers': 'ms-settings:printers',
    'mouse': 'ms-settings:mousetouchpad', 'touchpad': 'ms-settings:devices-touchpad', 'typing': 'ms-settings:typing',
    'autoplay': 'ms-settings:autoplay', 'usb': 'ms-settings:usb',
    # Network & internet
    'network': 'ms-settings:network-status', 'wi-fi': 'ms-settings:network-wifi', 'ethernet': 'ms-settings:network-ethernet',
    'vpn': 'ms-settings:network-vpn', 'mobile hotspot': 'ms-settings:network-mobilehotspot',
    'airplane mode': 'ms-settings:network-airplanemode', 'proxy': 'ms-settings:network-proxy', 'data usage': 'ms-settings:datausage',
    # Personalization
    'personalization': 'ms-settings:personalization', 'background': 'ms-settings:personalization-background',
    'colors': 'ms-settings:colors', 'themes': 'ms-settings:themes', 'lock screen': 'ms-settings:lockscreen',
    'start': 'ms-settings:personalization-start', 'taskbar': 'ms-settings:taskbar', 'fonts': 'ms-settings:fonts',
    # Apps
    'installed apps': 'ms-settings:appsfeatures', 'default apps': 'ms-settings:defaultapps',
    'startup apps': 'ms-settings:startupapps', 'optional features': 'ms-settings:optionalfeatures',
    # Accounts
    'accounts': 'ms-settings:yourinfo', 'sign-in options': 'ms-settings:signinoptions',
    'email & accounts': 'ms-settings:emailandaccounts', 'other users': 'ms-settings:otherusers',
    # Time & language
    'date & time': 'ms-settings:dateandtime', 'language': 'ms-settings:regionlanguage',
    'region': 'ms-settings:regionformatting', 'speech': 'ms-settings:speech',
    # Gaming
    'game mode': 'ms-settings:gaming-gamemode', 'game bar': 'ms-settings:gaming-gamebar',
    # Accessibility
    'accessibility': 'ms-settings:easeofaccess', 'text size': 'ms-settings:easeofaccess-display',
    'mouse pointer': 'ms-settings:easeofaccess-mousepointer', 'magnifier': 'ms-settings:easeofaccess-magnifier',
    'narrator': 'ms-settings:easeofaccess-narrator', 'captions': 'ms-settings:easeofaccess-closedcaptioning',
    'color filters': 'ms-settings:easeofaccess-colorfilter', 'contrast themes': 'ms-settings:easeofaccess-highcontrast',
    'accessibility keyboard': 'ms-settings:easeofaccess-keyboard',
    # Privacy & security
    'privacy': 'ms-settings:privacy', 'windows security': 'ms-settings:windowsdefender',
    'location': 'ms-settings:privacy-location', 'camera': 'ms-settings:privacy-webcam',
    'microphone': 'ms-settings:privacy-microphone', 'find my device': 'ms-settings:findmydevice',
    'for developers': 'ms-settings:developers',
    # Windows Update
    'windows update': 'ms-settings:windowsupdate', 'update history': 'ms-settings:windowsupdate-history',
    'advanced update options': 'ms-settings:windowsupdate-options', 'optional updates': 'ms-settings:windowsupdate-optionalupdates',
    'windows insider': 'ms-settings:windowsinsider',
}

# Buttons whose effect cannot be undone from Settings; require confirm=true.
RISKY = re.compile(r'\b(reset|remove|delete|uninstall|erase|forget|format|sign out|clean ?up|restart|shut ?down|wipe|disconnect)\b', re.I)

_TYPES = {'ButtonControl', 'CheckBoxControl', 'ComboBoxControl', 'RadioButtonControl', 'HyperlinkControl',
          'ListItemControl', 'SliderControl', 'GroupControl'}
_CHROME = {'minimize', 'maximize', 'restore', 'close', 'navigationviewbackbutton', 'userprofilecontrolbutton'}


def resolve_page(page):
    key = str(page or '').strip().casefold().replace(' and ', ' & ').replace('wifi', 'wi-fi')
    if key.startswith('ms-settings:'):
        return key, key
    if key in ('', 'settings'):
        key = 'home'
    match = key if key in PAGES else next(iter(difflib.get_close_matches(key, PAGES, n=1, cutoff=0.6)), None)
    if match is None:
        match = next((name for name in PAGES if key in name or name in key and name != 'home'), None)
    if match is None:
        raise ActionError(f"Unknown Settings page '{page}'. Known pages: {', '.join(PAGES)}.")
    return match, PAGES[match]


def _window():
    import uiautomation as auto
    for window in auto.GetRootControl().GetChildren():
        try:
            if window.ClassName == 'ApplicationFrameWindow' and 'settings' in (window.Name or '').casefold():
                return window
        except Exception:
            continue
    return None


def open_page(page='home', timeout=8):
    name, uri = resolve_page(page)
    os.startfile(uri)
    deadline = time.monotonic() + timeout
    while _window() is None:
        if time.monotonic() > deadline:
            raise ActionError('The Settings window did not appear.')
        time.sleep(.2)
    return {'page': name, 'uri': uri}


def _toggle_state(control):
    import uiautomation as auto
    try:
        pattern = control.GetPattern(auto.PatternId.TogglePattern)
        return ('off', 'on', 'mixed')[pattern.ToggleState] if pattern else None
    except Exception:
        return None


def _controls():
    """Visible, named, actionable controls in the Settings content area."""
    import uiautomation as auto
    window = _window()
    if window is None:
        raise ActionError('Settings is not open.')
    for control, _depth in auto.WalkControl(window, maxDepth=30):
        try:
            if (control.ControlTypeName in _TYPES and control.Name and not control.IsOffscreen
                    and (control.AutomationId or '').casefold() not in _CHROME):
                yield control
        except Exception:
            continue


def _describe(control):
    import uiautomation as auto
    item = {'name': control.Name, 'type': control.ControlTypeName.removesuffix('Control')}
    state = _toggle_state(control)
    if state:
        item['state'] = state
    try:
        if control.ControlTypeName == 'ComboBoxControl':
            pattern = control.GetPattern(auto.PatternId.ValuePattern)
            selection = control.GetPattern(auto.PatternId.SelectionPattern)
            item['value'] = pattern.Value if pattern else selection.GetSelection()[0].Name
        elif control.ControlTypeName == 'SliderControl':
            item['value'] = control.GetPattern(auto.PatternId.RangeValuePattern).Value
    except Exception:
        pass
    return item


def read_page():
    seen, items = set(), []
    for control in _controls():
        item = _describe(control)
        # Group containers are only interesting when they are the toggle themselves.
        if item['type'] == 'Group' and 'state' not in item:
            continue
        if (key := (item['name'], item['type'])) not in seen:
            seen.add(key)
            items.append(item)
    return {'controls': items}


def _find(name, accept, timeout=6):
    """Best-named control passing `accept`; polls because pages render late."""
    wanted, deadline = str(name or '').strip().casefold(), time.monotonic() + timeout
    if not wanted:
        raise ActionError('name of the control is required.')
    while True:
        candidates = [control for control in _controls() if accept(control)]
        for test in (lambda n: n == wanted, lambda n: n.startswith(wanted), lambda n: wanted in n):
            matches = [control for control in candidates if test(control.Name.casefold())]
            if matches:
                return matches[0]
        if time.monotonic() > deadline:
            names = sorted({control.Name for control in candidates})
            raise ActionError(f"No matching control named '{name}' on this Settings page. Available: {', '.join(names) or 'none'}.")
        time.sleep(.3)


def get_toggle(name):
    control = _find(name, lambda control: _toggle_state(control) is not None)
    return {'name': control.Name, 'state': _toggle_state(control)}


def set_toggle(name, on):
    import uiautomation as auto
    wanted = 'on' if on else 'off'
    control = _find(name, lambda control: _toggle_state(control) is not None)
    label = control.Name
    if _toggle_state(control) != wanted:
        control.GetPattern(auto.PatternId.TogglePattern).Toggle()
        deadline = time.monotonic() + 4
        # Re-find: Settings often rebuilds the row after a toggle.
        while (state := _toggle_state(_find(label, lambda control: _toggle_state(control) is not None))) != wanted:
            if time.monotonic() > deadline:
                raise ActionError(f"'{label}' is still {state} after toggling; Windows may have blocked the change.")
            time.sleep(.3)
    return {'name': label, 'state': wanted}


def click(name, confirm=False):
    import uiautomation as auto
    control = _find(name, lambda control: control.ControlTypeName in ('ButtonControl', 'HyperlinkControl', 'ListItemControl', 'RadioButtonControl'))
    if RISKY.search(control.Name) and not confirm:
        raise ActionError(f"'{control.Name}' may be irreversible. Ask the user, then repeat with confirm=true.")
    for pattern_id, act in ((auto.PatternId.InvokePattern, 'Invoke'), (auto.PatternId.SelectionItemPattern, 'Select'),
                            (auto.PatternId.ExpandCollapsePattern, 'Expand')):
        pattern = control.GetPattern(pattern_id)
        if pattern:
            getattr(pattern, act)()
            return {'clicked': control.Name}
    raise ActionError(f"'{control.Name}' cannot be activated without moving the mouse.")


def select(name, value):
    """Choose `value` in the dropdown called `name`."""
    import uiautomation as auto
    combo = _find(name, lambda control: control.ControlTypeName == 'ComboBoxControl')
    label, wanted = combo.Name, str(value).strip().casefold()
    combo.GetPattern(auto.PatternId.ExpandCollapsePattern).Expand()
    time.sleep(.5)
    try:
        # The open list is a popup; it may sit under the combo or under the window.
        options = [control for root in (combo, _window()) for control, _ in auto.WalkControl(root, maxDepth=30)
                   if control.ControlTypeName == 'ListItemControl' and control.Name and not control.IsOffscreen
                   and control.GetPattern(auto.PatternId.SelectionItemPattern)]
        for test in (lambda n: n == wanted, lambda n: wanted in n):
            for option in options:
                if test(option.Name.casefold()):
                    option.GetPattern(auto.PatternId.SelectionItemPattern).Select()
                    return {'name': label, 'value': option.Name}
        raise ActionError(f"'{label}' has no option '{value}'. Options: {', '.join(dict.fromkeys(o.Name for o in options)) or 'none'}.")
    finally:
        try:
            combo.GetPattern(auto.PatternId.ExpandCollapsePattern).Collapse()
        except Exception:
            pass
