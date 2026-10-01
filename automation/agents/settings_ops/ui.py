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
RISKY = re.compile(r'\b(reset|restore|remove|delete|uninstall|erase|forget|format|sign out|clean ?up|restart|shut ?down|wipe|disconnect)\b', re.I)

_TYPES = {'ButtonControl', 'CheckBoxControl', 'ComboBoxControl', 'RadioButtonControl', 'HyperlinkControl',
          'ListItemControl', 'SliderControl', 'GroupControl', 'EditControl', 'SpinnerControl', 'TabItemControl'}
_CHROME = {'minimize', 'maximize', 'restore', 'close', 'navigationviewbackbutton', 'userprofilecontrolbutton'}
_CP_CLASSES = ('CabinetWClass', '#32770')  # Explorer-hosted Control Panel pages, classic dialogs
SETTINGS_CLASS = 'ApplicationFrameWindow'


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


def _window(title=None):
    """The Settings window (title None), else the Control Panel window whose title contains `title`."""
    import uiautomation as auto
    wanted = str(title or '').strip().casefold()
    if wanted in ('', 'settings'):
        for window in auto.GetRootControl().GetChildren():
            try:
                if window.ClassName == SETTINGS_CLASS and 'settings' in (window.Name or '').casefold():
                    return window
            except Exception:
                continue
        return None
    open_titles, found = [], []
    for window in auto.GetRootControl().GetChildren():
        try:
            if window.ClassName in _CP_CLASSES and window.Name:
                open_titles.append(window.Name)
                if wanted in window.Name.casefold():
                    found.append(window)
        except Exception:
            continue
    found = [w for w in found if w.Name.casefold() == wanted] or found
    if not found:
        raise ActionError(f"No open Control Panel window titled '{title}'. Open windows: {', '.join(dict.fromkeys(open_titles)) or 'none'}.")
    return found[0]  # the desktop lists windows front to back, so this is the foreground-most


def top_windows():
    """{handle: (class, title)} of the open classic Control Panel windows and the Settings app."""
    import uiautomation as auto
    windows = {}
    for window in auto.GetRootControl().GetChildren():
        try:
            if window.ClassName in _CP_CLASSES and window.Name:
                windows[window.NativeWindowHandle] = (window.ClassName, window.Name)
        except Exception:
            continue
    if settings := _window():
        windows[settings.NativeWindowHandle] = (SETTINGS_CLASS, 'Settings')
    return windows


def foreground():
    import uiautomation as auto
    try:
        return auto.GetForegroundControl().GetTopLevelControl().NativeWindowHandle
    except Exception:
        return 0


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


def _label(control):
    """Own name, else the name of the control that labels it (classic dialogs), else ''."""
    import uiautomation as auto
    if control.Name:
        return control.Name
    try:
        labeller = control.GetPropertyValue(auto.PropertyId.LabeledByProperty)
        return (labeller.Name or '') if labeller else ''
    except Exception:
        return ''


def _controls(window=None):
    """Visible, labelled, actionable controls in the Settings content area or the named Control Panel window."""
    import uiautomation as auto
    root = _window(window)
    if root is None:
        raise ActionError('Settings is not open.')
    if window:
        try:
            driveable = bool(root.GetChildren())
        except Exception:
            driveable = False
        if not driveable:
            raise ActionError(f"'{root.Name}' runs with administrator rights and cannot be driven by AURA. The user must change it themselves.")
    for control, _depth in auto.WalkControl(root, maxDepth=30):
        try:
            if (control.ControlTypeName in _TYPES and _label(control) and not control.IsOffscreen
                    and (control.AutomationId or '').casefold() not in _CHROME):
                yield control
        except Exception:
            continue


def _value(control):
    import uiautomation as auto
    for pattern_id in (auto.PatternId.RangeValuePattern, auto.PatternId.ValuePattern):
        pattern = control.GetPattern(pattern_id)
        if pattern and pattern.Value not in ('', None):
            return pattern.Value
    selection = control.GetPattern(auto.PatternId.SelectionPattern)
    return selection.GetSelection()[0].Name if selection else None


def _describe(control):
    import uiautomation as auto
    kind = control.ControlTypeName
    item = {'name': _label(control), 'type': kind.removesuffix('Control')}
    state = _toggle_state(control)
    if state:
        item['state'] = state
    try:
        if kind in ('ComboBoxControl', 'SliderControl', 'SpinnerControl', 'EditControl'):
            item['value'] = _value(control)
        elif kind in ('TabItemControl', 'RadioButtonControl', 'ListItemControl'):
            pattern = control.GetPattern(auto.PatternId.SelectionItemPattern)
            if pattern and pattern.IsSelected:
                item['selected'] = True
    except Exception:
        pass
    return item


def _in_nav(control):
    """Left navigation and breadcrumb: listed by neither read_page nor needed there, but still clickable."""
    while control := control.GetParentControl():
        if control.AutomationId in ('MenuItemsHost', 'PermanentNavigationViewBreadcrumbBar'):
            return True
    return False


def read_page(window=None):
    seen, items = set(), []
    for control in _controls(window):
        if _in_nav(control):
            continue
        item = _describe(control)
        # Group containers are only interesting when they are the toggle themselves.
        if item['type'] == 'Group' and 'state' not in item:
            continue
        if (key := (item['name'], item['type'])) not in seen:
            seen.add(key)
            items.append(item)
    return {'controls': items, **({'window': _window(window).Name} if window else {})}


def _find(name, accept, window=None, timeout=6):
    """Best-named control passing `accept`; polls because pages render late."""
    wanted, deadline = str(name or '').strip().casefold(), time.monotonic() + timeout
    if not wanted:
        raise ActionError('name of the control is required.')
    while True:
        candidates = [(_label(control), control) for control in _controls(window) if accept(control)]
        for test in (lambda n: n == wanted, lambda n: n.startswith(wanted), lambda n: wanted in n):
            matches = [control for label, control in candidates if test(label.casefold())]
            if matches:
                return matches[0]
        if time.monotonic() > deadline:
            names = sorted({label for label, _ in candidates})
            raise ActionError(f"No matching control named '{name}' in {'this window' if window else 'this Settings page'}. Available: {', '.join(names) or 'none'}.")
        time.sleep(.3)


def _has_toggle(control):
    return _toggle_state(control) is not None


def get_toggle(name, window=None):
    control = _find(name, _has_toggle, window)
    return {'name': _label(control), 'state': _toggle_state(control)}


def set_toggle(name, on, window=None):
    import uiautomation as auto
    wanted = 'on' if on else 'off'
    control = _find(name, _has_toggle, window)
    label = _label(control)
    if _toggle_state(control) != wanted:
        control.GetPattern(auto.PatternId.TogglePattern).Toggle()
        deadline = time.monotonic() + 4
        # Re-find: Settings often rebuilds the row after a toggle.
        while (state := _toggle_state(_find(label, _has_toggle, window))) != wanted:
            if time.monotonic() > deadline:
                raise ActionError(f"'{label}' is still {state} after toggling; Windows may have blocked the change.")
            time.sleep(.3)
    return {'name': label, 'state': wanted}


def click(name, confirm=False, window=None):
    import uiautomation as auto
    control = _find(name, lambda control: control.ControlTypeName in ('ButtonControl', 'HyperlinkControl', 'ListItemControl',
                                                                     'RadioButtonControl', 'TabItemControl'), window)
    label = _label(control)
    if RISKY.search(label) and not confirm:
        raise ActionError(f"'{label}' may be irreversible. Ask the user, then repeat with confirm=true.")
    for pattern_id, act in ((auto.PatternId.InvokePattern, 'Invoke'), (auto.PatternId.SelectionItemPattern, 'Select'),
                            (auto.PatternId.ExpandCollapsePattern, 'Expand'),
                            (auto.PatternId.LegacyIAccessiblePattern, 'DoDefaultAction')):  # last non-mouse resort
        pattern = control.GetPattern(pattern_id)
        if pattern:
            getattr(pattern, act)()
            if act == 'Select':
                time.sleep(.2)
                if not pattern.IsSelected:
                    raise ActionError(f"'{label}' is not selected after clicking it.")
            return {'clicked': label}
    raise ActionError(f"'{label}' cannot be activated without moving the mouse.")


def select(name, value, window=None):
    """Choose `value` in the dropdown called `name`."""
    import uiautomation as auto
    combo = _find(name, lambda control: control.ControlTypeName == 'ComboBoxControl', window)
    label, wanted = _label(combo), str(value).strip().casefold()
    combo.GetPattern(auto.PatternId.ExpandCollapsePattern).Expand()
    time.sleep(.5)
    try:
        # The open list is a popup; it may sit under the combo or under the window.
        options = [control for root in (combo, _window(window)) for control, _ in auto.WalkControl(root, maxDepth=30)
                   if control.ControlTypeName == 'ListItemControl' and control.Name and not control.IsOffscreen
                   and control.GetPattern(auto.PatternId.SelectionItemPattern)]
        for test in (lambda n: n == wanted, lambda n: wanted in n):
            for option in options:
                if test(option.Name.casefold()):
                    option.GetPattern(auto.PatternId.SelectionItemPattern).Select()
                    time.sleep(.3)
                    try:
                        now = _value(combo)
                    except Exception:
                        now = None
                    if now is not None and option.Name.casefold() not in str(now).casefold():
                        raise ActionError(f"'{label}' shows '{now}' after choosing '{option.Name}'; the change did not stick.")
                    return {'name': label, 'value': option.Name}
        raise ActionError(f"'{label}' has no option '{value}'. Options: {', '.join(dict.fromkeys(o.Name for o in options)) or 'none'}.")
    finally:
        try:
            combo.GetPattern(auto.PatternId.ExpandCollapsePattern).Collapse()
        except Exception:
            pass


def set_value(name, value, window=None):
    """Type a value into the edit box / spinner / slider called `name`, then read it back."""
    import uiautomation as auto
    accept = lambda control: control.ControlTypeName in ('EditControl', 'SpinnerControl', 'SliderControl')
    control = _find(name, accept, window)
    label, text = _label(control), str(value).strip()
    for pattern_id in (auto.PatternId.RangeValuePattern, auto.PatternId.ValuePattern):
        if pattern := control.GetPattern(pattern_id):
            break
    else:
        raise ActionError(f"'{label}' cannot be set without moving the mouse.")
    try:
        pattern.SetValue(float(text) if pattern_id == auto.PatternId.RangeValuePattern else text)
    except Exception as error:
        raise ActionError(f"'{label}' did not accept '{text}': {error}") from None
    actual = _value(_find(label, accept, window))
    try:
        same = float(actual) == float(text)
    except (TypeError, ValueError):
        same = str(actual).strip().casefold() == text.casefold()
    if not same:
        raise ActionError(f"'{label}' is {actual} after setting {text}; the control rejected or adjusted the value.")
    return {'name': label, 'value': actual}
