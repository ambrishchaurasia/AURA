"""
AURA Settings Agent — Windows 11 Settings automation.

Uses ms-settings: URI schemes for instant, reliable navigation to any Settings page
(no UI tree walking required). Learned from auracopy's settings agent structure.

Supported actions:
- open         : Open Settings home
- navigate     : Go to a specific settings page (wifi, display, bluetooth, etc.)
- toggle_wifi  : Turn Wi-Fi on or off
- toggle_bluetooth : Turn Bluetooth on or off
- check_updates: Open Windows Update and check for updates
"""
from __future__ import annotations
import os
import time
import subprocess
import json
import pathlib
from typing import Optional

import pyautogui

from automation.core.base_agent import BaseAgent
from automation.core import window_manager


import sys
# Add auracopy to path so we can import its execution engine
sys.path.append(str(pathlib.Path(__file__).parent.parent.parent / "auracopy"))

from core.execution_engine.tier1_map import Tier1MapResolver
from core.execution_engine.tier2_crawl import Tier2LiveCrawler

APP_MAP_PATH = pathlib.Path(__file__).parent.parent.parent / "app_maps" / "settings.json"


class SettingsAgent(BaseAgent):
    """Agent for automating Windows 11 Settings using auracopy's map."""

    def __init__(self):
        with open(APP_MAP_PATH, encoding="utf-8") as f:
            self._app_map = json.load(f)
        self.resolver = Tier1MapResolver(allow_coordinate_click=True)
        self.crawler = Tier2LiveCrawler(allow_coordinate_click=True)

    # ── BaseAgent abstract contract ──────────────────────────────────────────

    @property
    def app_name(self) -> str:
        return "Settings"

    @property
    def process_name(self) -> str:
        return "SystemSettings.exe"

    def get_agent_name(self) -> str:
        return "settings"

    def get_llm_capabilities(self) -> str:
        features = list(self._app_map.get("feature_index", {}).keys())
        examples = ", ".join(f'"{f}"' for f in features[:20]) + "..."
        return f"""
Agent `settings` supports Windows 11 Settings automation using a feature map.
- `open`: Opens Settings home. No params.
- `execute_feature`: Clicks/executes a specific feature from the UI map or live screen. Params: {{"feature": <string>}}.
  Example map features you can request: {examples}
  
  IMPORTANT INSTRUCTION: If you need to click a specific toggle (like turning off Wi-Fi or Bluetooth), you MUST use TWO steps:
  1. Navigate to the page using a map feature (e.g., {{"action": "execute_feature", "params": {{"feature": "open wi-fi in network & internet"}} }})
  2. Click the actual toggle by naming it (e.g., {{"action": "execute_feature", "params": {{"feature": "wi-fi"}} }})
  
- `set_brightness`: Sets the screen brightness (0-100). Params: {{"level": <int>}}
"""

    def get_capabilities(self) -> dict:
        return {
            "application": "settings",
            "actions": {
                "open":               {"description": "Open Settings home", "parameters": {}, "safety": "safe"},
                "execute_feature":    {"description": "Execute a feature path from the map", "parameters": {"feature": "string"}, "safety": "safe"},
                "set_brightness":     {"description": "Set screen brightness", "parameters": {"level": "int"}, "safety": "safe"},
            },
        }

    def resolve(self, intent: str, **kwargs) -> dict:
        return {"action": intent, "target_element": None, "resolver_tier": 1, "confidence": 1.0}

    def execute(self, action: str, params: dict | None = None) -> dict:
        params = params or {}
        start = time.time()
        try:
            if action == "open":
                return self._action_open(start)
            elif action == "execute_feature":
                return self._action_execute_feature(params.get("feature", ""), start)
            elif action == "set_brightness":
                return self._action_set_brightness(params.get("level", 50), start)
            else:
                return self._result("failure", action, f"Unknown action: {action}", start)
        except Exception as e:
            return self._result("failure", action, str(e), start)

    def verify(self, expected_state: dict) -> dict:
        window = self.get_window()
        exists = window is not None
        return {
            "verified": exists,
            "expected": expected_state,
            "actual": {"window_exists": exists},
            "details": "Settings window found" if exists else "Settings window not found",
        }

    # ── Window management ────────────────────────────────────────────────────

    def get_window(self):
        """Find the Settings window if it's open."""
        # Windows 11 Settings uses 'ApplicationFrameWindow' as the outer frame class
        # Try multiple class names for compatibility
        for class_name in ["ApplicationFrameWindow", "SystemSettings", None]:
            try:
                win = window_manager.find_window(
                    title_contains="Settings",
                    class_name=class_name
                )
                if win is not None:
                    return win
            except Exception:
                continue
        return None

    # ── Private actions ──────────────────────────────────────────────────────

    def _launch_uri(self, uri: str):
        """Launch a ms-settings: URI. Opens Settings directly at that page."""
        try:
            os.startfile(uri)
        except Exception:
            # Fallback: use explorer.exe to open URI
            subprocess.Popen(["explorer.exe", uri])
        time.sleep(2.5)  # Wait for Settings window to appear and render

    def _action_open(self, start: float) -> dict:
        """Open Settings home."""
        self._launch_uri("ms-settings:")
        win = self.get_window()
        if win:
            window_manager.focus_window(win)
        # URI launch always works even if window detection fails
        return self._result("success", "open", "Settings opened", start)

    def _action_execute_feature(self, feature: str, start: float) -> dict:
        """Executes a feature by looking it up in the auracopy map."""
        if not feature:
            return self._result("failure", "execute_feature", "No feature provided", start)
            
        # Ensure window is open
        win = self.get_window()
        if not win:
            os.system("start ms-settings:")
            time.sleep(2)
            
        # Use auracopy's Tier1MapResolver to click through the path
        # Note: Tier1MapResolver handles finding the app window itself based on self._app_map
        result = self.resolver.resolve_and_execute(feature, self._app_map)
        
        if result.get("success"):
            return self._result("success", "execute_feature", f"Tier 1: {result.get('message', 'Success')}", start)
        else:
            # Try fuzzy match if exact match failed
            features = list(self._app_map.get("feature_index", {}).keys())
            import difflib
            matches = difflib.get_close_matches(feature, features, n=1, cutoff=0.6)
            if matches:
                fuzzy_feature = matches[0]
                result = self.resolver.resolve_and_execute(fuzzy_feature, self._app_map)
                if result.get("success"):
                    return self._result("success", "execute_feature", f"Tier 1 (Fuzzy '{fuzzy_feature}'): " + result.get("message", "Success"), start)

            # Fallback to Tier 2 Live Crawler
            print(f"[SettingsAgent] Tier 1 failed for '{feature}', falling back to Tier 2 live crawler...")
            t2_result = self.crawler.resolve_and_execute(feature, self._app_map)
            if t2_result.get("success"):
                return self._result("success", "execute_feature", f"Tier 2 Live Crawler: {t2_result.get('message')}", start)

            return self._result("failure", "execute_feature", f"Tier 1 and Tier 2 both failed for '{feature}'.", start)


    def _netsh_fallback(self, page: str, toggle_label: str, state: str, start: float) -> dict:

        """Fallback: use netsh to toggle Wi-Fi / airplane mode via OS commands."""
        try:
            if "wi-fi" in toggle_label.lower() or "wifi" in toggle_label.lower():
                action = "enable" if state == "on" else "disable"
                result = subprocess.run(
                    ["netsh", "interface", "set", "interface", "Wi-Fi", f"admin={action}"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return self._result("success", f"toggle_{page}",
                                        f"Wi-Fi turned {state} via netsh", start)
                else:
                    return self._result("failure", f"toggle_{page}",
                                        f"netsh failed (try running as admin): {result.stderr.strip()}", start)
            return self._result("failure", f"toggle_{page}",
                                f"Could not toggle '{toggle_label}' — no usable UIA pattern found", start)
        except Exception as e:
            return self._result("failure", f"toggle_{page}", f"All toggle methods failed: {e}", start)

    def _action_set_brightness(self, level: int, start: float) -> dict:
        """Set screen brightness using WMI."""
        try:
            level = max(0, min(100, int(level)))
            import wmi
            w = wmi.WMI(namespace='wmi')
            monitors = w.WmiMonitorBrightnessMethods()
            if not monitors:
                return self._result("failure", "set_brightness", "No WMI brightness methods found (may not be supported on this monitor)", start)
            
            for monitor in monitors:
                monitor.WmiSetBrightness(level, 0)
                
            return self._result("success", "set_brightness", f"Brightness set to {level}%", start)
        except Exception as e:
            return self._result("failure", "set_brightness", f"Failed to set brightness via WMI: {e}", start)




    def _result(self, status: str, action: str, details: str, start_time: float) -> dict:
        return {
            "status": status,
            "action": action,
            "details": details,
            "duration_ms": round((time.time() - start_time) * 1000),
        }
