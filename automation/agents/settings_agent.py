"""
AURA Settings Agent — Windows 11 settings control and troubleshooting.

Three layers, most reliable first:
1. Direct Windows APIs for everyday settings (radios, volume, brightness, theme,
   power, network, displays). No Settings window, every change is read back.
2. ms-settings: URIs to open any Settings page instantly.
3. Named-control access (toggle / dropdown / button) on the open page for
   settings that have no API. Driven by UIA patterns, verified after acting.
"""
from __future__ import annotations
import time

from automation.core.base_agent import BaseAgent
from automation.agents.settings_ops import ActionError, displays, radios, system, ui


def _on(params: dict) -> bool:
    state = params.get("state")
    if isinstance(state, bool):
        return state
    if str(state).strip().lower() in ("on", "off"):
        return str(state).strip().lower() == "on"
    raise ActionError("state must be 'on' or 'off'.")


def _on_page(operation):
    """Run a named-control operation, first opening params['page'] if given."""
    def run(params):
        if params.get("page"):
            ui.open_page(params["page"])
        elif ui._window() is None:
            raise ActionError("Settings is not open. Pass 'page' so AURA knows where the control lives.")
        return operation(params)
    return run


def _displays(preview=None):
    def run(params):
        inventory = displays.read_displays(lambda: None)
        try:
            return preview(inventory, **params) if preview else inventory
        except TypeError:
            raise ActionError("Run inspect_displays first and pass its exact display_id with the requested rate.") from None
    return run


def _check_updates(params):
    ui.open_page("ms-settings:windowsupdate-action")
    return {"page": "windows update", "message": "Windows Update opened and a check was started."}


# action -> (handler(params) -> data, description, parameters, safety)
ACTIONS = {
    # Radios
    "get_bluetooth": (lambda p: radios.get_radio("bluetooth"), "Read whether Bluetooth is on or off", {}, "safe"),
    "set_bluetooth": (lambda p: radios.set_radio("bluetooth", _on(p)), "Turn Bluetooth on or off", {"state": "on|off"}, "safe"),
    "restart_bluetooth": (lambda p: radios.restart_radio("bluetooth"), "Troubleshoot: turn Bluetooth off and on again", {}, "safe"),
    "find_bluetooth_device": (lambda p: radios.find_bluetooth_device(str(p.get("name", "")), p.get("scan") is True),
                              "Check whether a paired Bluetooth device is nearby / connected. Empty name lists all paired devices. scan=true also finds unpaired nearby devices and takes about 30 seconds",
                              {"name": "string", "scan": "bool (optional)"}, "safe"),
    "get_wifi": (lambda p: radios.get_radio("wifi"), "Read whether Wi-Fi is on or off", {}, "safe"),
    "set_wifi": (lambda p: radios.set_radio("wifi", _on(p)), "Turn Wi-Fi on or off", {"state": "on|off"}, "safe"),
    "restart_wifi": (lambda p: radios.restart_radio("wifi"), "Troubleshoot: turn Wi-Fi off and on again", {}, "safe"),
    "list_wifi_networks": (lambda p: system.list_wifi_networks(), "List visible Wi-Fi networks", {}, "safe"),
    "connect_wifi": (lambda p: system.connect_wifi(p.get("name")), "Connect to a Wi-Fi network already saved on this PC", {"name": "string"}, "safe"),
    "set_airplane_mode": (lambda p: (ui.open_page("airplane mode"), ui.set_toggle("airplane mode", _on(p)))[1],
                          "Turn airplane mode on or off", {"state": "on|off"}, "safe"),
    # Network troubleshooting
    "diagnose_network": (lambda p: system.diagnose_network(), "Troubleshoot: check internet reachability, DNS and Wi-Fi link, with advice", {}, "safe"),
    "flush_dns": (lambda p: system.flush_dns(), "Troubleshoot: clear the DNS cache", {}, "safe"),
    # Sound
    "get_volume": (lambda p: system.get_volume(), "Read the volume and mute state", {}, "safe"),
    "set_volume": (lambda p: system.set_volume(level=p.get("level")), "Set the volume (0-100)", {"level": "int"}, "safe"),
    "set_mute": (lambda p: system.set_volume(muted=_on(p)), "Mute (on) or unmute (off) sound", {"state": "on|off"}, "safe"),
    "list_audio_devices": (lambda p: system.list_audio_devices(), "List active sound output devices and which is the default", {}, "safe"),
    "set_audio_device": (lambda p: system.set_audio_device(p.get("name")), "Make a sound output device the default (matched by part of its name)", {"name": "string"}, "safe"),
    # Display
    "get_brightness": (lambda p: system.get_brightness(), "Read screen brightness", {}, "safe"),
    "set_brightness": (lambda p: system.set_brightness(p.get("level")), "Set screen brightness (0-100)", {"level": "int"}, "safe"),
    "get_theme": (lambda p: system.get_theme(), "Read whether dark or light mode is active", {}, "safe"),
    "set_theme": (lambda p: system.set_theme(str(p.get("mode", "")).lower()), "Switch dark / light mode", {"mode": "dark|light"}, "safe"),
    "inspect_displays": (_displays(), "Read connected displays, resolution, refresh rates and HDR state. Changes nothing", {}, "safe"),
    "preview_refresh_rate": (_displays(displays.preview_refresh), "Check whether a refresh rate is available on a display. Changes nothing",
                             {"display_id": "string from inspect_displays", "nominal_hz": "int"}, "safe"),
    "preview_exact_refresh_rate": (_displays(displays.preview_exact_refresh), "Check an exact fractional refresh rate on a display. Changes nothing",
                                   {"display_id": "string from inspect_displays", "numerator": "int", "denominator": "int"}, "safe"),
    "set_refresh_rate": (lambda p: displays.set_refresh_rate(p.get("display_id"), p.get("nominal_hz")),
                         "Set a display's refresh rate at its current resolution. Only rates from inspect_displays work; reversible by setting the old rate",
                         {"display_id": "string from inspect_displays", "nominal_hz": "int"}, "safe"),
    # Power / system
    "get_battery": (lambda p: system.get_battery(), "Read battery level, charging and battery saver state", {}, "safe"),
    "list_power_plans": (lambda p: system.list_power_plans(), "List power plans and the active one", {}, "safe"),
    "set_power_plan": (lambda p: system.set_power_plan(p.get("name", "")), "Activate a power plan by name", {"name": "string"}, "safe"),
    "storage_status": (lambda p: system.storage_status(), "Read free space on each drive", {}, "safe"),
    "system_info": (lambda p: system.system_info(), "Read PC name, Windows version and uptime", {}, "safe"),
    "check_updates": (_check_updates, "Open Windows Update and start checking for updates", {}, "safe"),
    # Settings app
    "open": (lambda p: ui.open_page("home"), "Open Settings home", {}, "safe"),
    "navigate": (lambda p: ui.open_page(p.get("page", "home")), "Open a Settings page by name (e.g. 'sound', 'troubleshoot', 'default apps') or ms-settings: URI",
                 {"page": "string"}, "safe"),
    "read_page": (_on_page(lambda p: ui.read_page()), "List the toggles, dropdowns and buttons on a Settings page with their current values",
                  {"page": "string (optional)"}, "safe"),
    "get_toggle": (_on_page(lambda p: ui.get_toggle(p.get("name"))), "Read a named toggle on a Settings page",
                   {"page": "string (optional)", "name": "string"}, "safe"),
    "set_toggle": (_on_page(lambda p: ui.set_toggle(p.get("name"), _on(p))), "Turn a named toggle on a Settings page on or off (e.g. page 'night light', name 'night light')",
                   {"page": "string (optional)", "name": "string", "state": "on|off"}, "safe"),
    "select_option": (_on_page(lambda p: ui.select(p.get("name"), p.get("value", ""))), "Choose a value in a named dropdown on a Settings page",
                      {"page": "string (optional)", "name": "string", "value": "string"}, "safe"),
    "click": (_on_page(lambda p: ui.click(p.get("name"), p.get("confirm") is True)),
              "Press a named button / link on a Settings page. Irreversible buttons (reset, remove, uninstall...) need confirm=true after asking the user",
              {"page": "string (optional)", "name": "string", "confirm": "bool"}, "confirm"),
}


class SettingsAgent(BaseAgent):
    """Agent for controlling and troubleshooting Windows 11 settings."""

    @property
    def app_name(self) -> str:
        return "Settings"

    @property
    def process_name(self) -> str:
        return "SystemSettings.exe"

    def get_agent_name(self) -> str:
        return "settings"

    def get_llm_capabilities(self) -> str:
        lines = [f"- `{name}`: {description}. Params: {parameters or 'none'}."
                 for name, (_, description, parameters, _) in ACTIONS.items()]
        return ("\nAgent `settings` controls and troubleshoots Windows 11 settings.\n"
                "Prefer the dedicated actions (set_bluetooth, set_wifi, set_volume, ...): they call Windows directly and verify the result.\n"
                "For any other setting use read_page to see the controls on a page, then set_toggle / select_option / click.\n"
                "A failed action reports the real reason in `details`; never tell the user it worked.\n"
                + "\n".join(lines) + f"\nPages for navigate / page: {', '.join(ui.PAGES)}.\n")

    def get_capabilities(self) -> dict:
        return {"application": "settings",
                "actions": {name: {"description": description, "parameters": parameters, "safety": safety}
                            for name, (_, description, parameters, safety) in ACTIONS.items()},
                "pages": list(ui.PAGES)}

    def resolve(self, intent: str, **kwargs) -> dict:
        return {"action": intent, "target_element": None, "resolver_tier": 1, "confidence": 1.0 if intent in ACTIONS else 0.0}

    def execute(self, action: str, params: dict | None = None) -> dict:
        start = time.time()
        if action not in ACTIONS:
            return self._result("failure", action, f"Unknown action: {action}. Available: {', '.join(ACTIONS)}", start)
        try:
            data = ACTIONS[action][0](params or {})
        except ActionError as error:
            return self._result("failure", action, str(error), start)
        except Exception as error:
            return self._result("failure", action, f"{type(error).__name__}: {error}", start)
        details = data.pop("text", None) or ", ".join(f"{key}: {value}" for key, value in data.items() if not isinstance(value, (list, dict)))
        return self._result("success", action, details, start, data)

    def verify(self, expected_state: dict) -> dict:
        exists = self.get_window() is not None
        return {"verified": exists, "expected": expected_state, "actual": {"window_exists": exists},
                "details": "Settings window found" if exists else "Settings window not found"}

    def get_window(self):
        return ui._window()

    def _result(self, status: str, action: str, details: str, start_time: float, data: dict | None = None) -> dict:
        return {"status": status, "action": action, "details": details, "data": data or {},
                "duration_ms": round((time.time() - start_time) * 1000)}
