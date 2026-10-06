"""
AURA File Explorer Agent — Automation agent for Windows File Explorer.

Implements the BaseAgent contract with operations:
- open: Launch File Explorer or open a specific path
- navigate: Navigate to a directory path
- create_folder: Create a new folder
- create_file: Create a new file with optional content
- search: Search for files within File Explorer
- select_all: Select all items (Ctrl+A)
- copy: Copy selected items (Ctrl+C)
- paste: Paste copied items (Ctrl+V)
- delete: Delete selected items (Delete)
- close: Close File Explorer window
- verify: Check path existence or window state
"""

from __future__ import annotations
import os
import re
import subprocess
import time
from typing import Optional

from pywinauto import Application

from automation.core.base_agent import BaseAgent
from automation.core import window_manager
from automation.core import input_handler
from automation.core import verifier as verify_module


class ExplorerAgent(BaseAgent):
    """Agent for automating Windows File Explorer."""

    _last_created_folder: str = ""

    @classmethod
    def get_last_created_folder(cls) -> str:
        return cls._last_created_folder

    def __init__(self):
        self._app = None
        self._window = None
        self._current_path = os.path.expanduser("~")
        try:
            from automation.core.app_map import load_app_map
            from automation.core.resolver import TieredResolver
            self.app_map = load_app_map("explorer")
            self.resolver = TieredResolver(self.app_map)
        except Exception:
            self.app_map = None
            self.resolver = None

    def get_agent_name(self) -> str:
        return "explorer"

    @property
    def app_name(self) -> str:
        return "File Explorer"

    @property
    def process_name(self) -> str:
        return "explorer.exe"

    def get_llm_capabilities(self) -> str:
        return """
Agent `explorer` supports:
- `open`: Opens File Explorer or a specific directory path. Params: `{"path": "<optional_folder_path>"}`.
- `navigate`: Navigates to a folder path in File Explorer. Params: `{"path": "<folder_path>"}`.
- `create_folder`: Creates a new folder. Params: `{"folder_name": "<string>", "path": "<optional_parent_path>"}`.
- `create_file`: Creates a new file. Params: `{"file_name": "<string>", "content": "<optional_content>", "path": "<optional_parent_path>"}`.
- `search`: Searches for files in File Explorer. Params: `{"query": "<string>"}`.
- `open_item`: Opens a file or selected item in File Explorer. Params: `{"filename": "<optional_file_or_path>"}`.
- `select_all`: Selects all files/folders in the active directory (Ctrl+A). Params: none.
- `copy`: Copies selected item(s) to clipboard (Ctrl+C). Params: none.
- `paste`: Pastes items from clipboard (Ctrl+V). Params: none.
- `delete`: Deletes selected item(s) (Delete key). Params: none.
- `close`: Closes the active File Explorer window. Params: none.
"""

    def get_capabilities(self) -> dict:
        return {
            "application": "explorer",
            "actions": {
                "open": {
                    "description": "Open File Explorer or a target directory path",
                    "parameters": {"path": "string"},
                    "safety": "safe",
                },
                "navigate": {
                    "description": "Navigate to a specific directory in File Explorer",
                    "parameters": {"path": "string"},
                    "safety": "safe",
                },
                "create_folder": {
                    "description": "Create a new folder in File Explorer",
                    "parameters": {"folder_name": "string", "path": "string"},
                    "safety": "safe",
                },
                "create_file": {
                    "description": "Create a new file in File Explorer",
                    "parameters": {"file_name": "string", "content": "string", "path": "string"},
                    "safety": "safe",
                },
                "search": {
                    "description": "Search for files within File Explorer",
                    "parameters": {"query": "string"},
                    "safety": "safe",
                },
                "select_all": {
                    "description": "Select all items in the folder",
                    "parameters": {},
                    "safety": "safe",
                },
                "copy": {
                    "description": "Copy selected items to clipboard",
                    "parameters": {},
                    "safety": "safe",
                },
                "paste": {
                    "description": "Paste items from clipboard",
                    "parameters": {},
                    "safety": "safe",
                },
                "delete": {
                    "description": "Delete selected items",
                    "parameters": {},
                    "safety": "needs_confirmation",
                },
                "close": {
                    "description": "Close File Explorer window",
                    "parameters": {},
                    "safety": "safe",
                },
            },
        }

    def get_window(self):
        """Get or refresh the visible File Explorer window handle."""
        if self._window is not None:
            try:
                if self._window.is_visible():
                    return self._window
            except Exception:
                pass
            self._window = None

        import win32gui
        found_hwnd = None

        def enum_cb(hwnd, extra):
            nonlocal found_hwnd
            if win32gui.IsWindowVisible(hwnd):
                cls = win32gui.GetClassName(hwnd) or ""
                wt = (win32gui.GetWindowText(hwnd) or "").strip()
                if cls == "CabinetWClass" or "file explorer" in wt.lower():
                    found_hwnd = hwnd
                    return False
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception:
            pass

        if found_hwnd:
            from pywinauto import Desktop
            self._window = Desktop(backend="win32").window(handle=found_hwnd)
            return self._window

        return None

    def resolve(self, intent: str, **kwargs) -> dict:
        """Resolve intent to target element."""
        window = self.get_window()
        return {
            "action": intent,
            "target_element": window,
            "resolver_tier": 1,
            "confidence": 0.9 if window else 0.0,
        }

    @classmethod
    def _normalize_path(cls, target_path: str, default_path: str = "") -> str:
        """Expand environment variables and resolve absolute path."""
        if not target_path:
            return default_path or os.path.expanduser("~")

        p_clean = target_path.strip().strip("'\"").lower()
        p_clean = re.sub(r"^(?:in|to|into|at|from|go\s+to|open)\s+", "", p_clean).strip()
        p_clean = re.sub(r"\s+(?:folder|directory)$", "", p_clean).strip()

        user_home = os.path.expanduser("~")
        onedrive_home = os.path.join(user_home, "OneDrive")
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")

        def get_known_dir(name: str) -> str:
            od_path = os.path.join(onedrive_home, name)
            if os.path.exists(od_path):
                return od_path
            return os.path.join(user_home, name)

        known_folder_keys = ["desktop", "downloads", "documents", "pictures", "videos", "music"]

        # Contextual folder references (e.g., "that folder", "this folder")
        if p_clean in (
            "that folder", "this folder", "the folder", 
            "that directory", "this directory", "the created folder", 
            "that created folder", "in that folder", "in the folder"
        ) or p_clean.startswith("that folder") or p_clean.startswith("this folder"):
            last_dir = ExplorerAgent.get_last_created_folder()
            if last_dir and os.path.exists(last_dir):
                return last_dir

        # Match phrases like "<subfolder> in <known_folder>" e.g. "camera roll in pictures"
        sub_in_known = re.search(r"(.+?)\s+in\s+([a-zA-Z0-9_\-\s]+)", p_clean, re.IGNORECASE)
        if sub_in_known:
            sub_part = sub_in_known.group(1).strip()
            parent_part = sub_in_known.group(2).strip()
            for key in known_folder_keys:
                if key in parent_part:
                    parent_dir = get_known_dir(key.capitalize())
                    cand = os.path.join(parent_dir, sub_part)
                    if os.path.exists(cand):
                        return cand
                    if os.path.exists(parent_dir):
                        try:
                            for item in os.listdir(parent_dir):
                                if item.lower() == sub_part.lower():
                                    return os.path.join(parent_dir, item)
                        except Exception:
                            pass
                    return os.path.abspath(cand)

        # Match phrases like "<folder> in <drive> drive" e.g. "Phone Link in c drive"
        drive_match = re.search(r"(.+?)\s+in\s+([a-zA-Z])\s+drive", p_clean, re.IGNORECASE)
        if drive_match:
            folder_part = drive_match.group(1).strip()
            drive_letter = drive_match.group(2).upper()
            target = os.path.join(f"{drive_letter}:\\", folder_part)
            if os.path.exists(target):
                return target
            for base in [f"{drive_letter}:\\", prog_files, user_home, onedrive_home]:
                candidate = os.path.join(base, folder_part)
                if os.path.exists(candidate):
                    return candidate
            return os.path.abspath(target)

        if "program files" in p_clean:
            return prog_files
        if p_clean in ("c drive", "c:", "c"):
            return r"C:\\"

        # Check direct known folder or subpath of known folder e.g. "pictures/camera roll", "pictures\camera roll", "pictures"
        for key in known_folder_keys:
            if p_clean == key or p_clean in (f"my {key}", f"the {key}"):
                return get_known_dir(key.capitalize())
            if p_clean.startswith(f"{key}\\") or p_clean.startswith(f"{key}/"):
                parent_dir = get_known_dir(key.capitalize())
                rel_part = target_path.strip()[len(key):].lstrip("\\/")
                cand = os.path.join(parent_dir, rel_part)
                if os.path.exists(cand):
                    return cand
                if os.path.exists(parent_dir):
                    try:
                        for item in os.listdir(parent_dir):
                            if item.lower() == rel_part.lower():
                                return os.path.join(parent_dir, item)
                    except Exception:
                        pass
                return os.path.abspath(cand)

        expanded = os.path.expandvars(os.path.expanduser(target_path.strip()))
        if os.path.isabs(expanded) and os.path.exists(expanded):
            return expanded

        for base_dir in [user_home, onedrive_home]:
            cand = os.path.join(base_dir, expanded.lstrip("\\/"))
            if os.path.exists(cand):
                return cand

        return os.path.abspath(expanded)

    @classmethod
    def _find_matching_file(cls, sdir: str, filename_query: str) -> Optional[str]:
        """Find matching file in directory based on query, supporting stem, descriptor, and prefix matching."""
        if not sdir or not os.path.isdir(sdir):
            return None

        clean_q = filename_query.strip().lower()
        clean_name = re.sub(
            r"^(?:image|picture|photo|video|movie|audio|music|text\s+file|text\s+document|document|file)\s+",
            "",
            clean_q,
            flags=re.IGNORECASE
        ).strip()

        try:
            entries = [f for f in os.listdir(sdir) if os.path.isfile(os.path.join(sdir, f))]
        except Exception:
            return None

        if not entries:
            return None

        # 1. Exact full filename match
        for item in entries:
            if item.lower() == clean_q or item.lower() == clean_name:
                return os.path.join(sdir, item)

        # 2. Exact stem match (filename without extension)
        for q in [clean_q, clean_name]:
            if not q:
                continue
            for item in entries:
                stem = os.path.splitext(item.lower())[0]
                if stem == q:
                    return os.path.join(sdir, item)

        # 3. Stem starts with query or query starts with stem
        for q in [clean_q, clean_name]:
            if not q or len(q) < 3:
                continue
            for item in entries:
                stem = os.path.splitext(item.lower())[0]
                if stem.startswith(q) or q.startswith(stem):
                    return os.path.join(sdir, item)

        # 4. Substring match
        for q in [clean_q, clean_name]:
            if not q or len(q) < 3:
                continue
            for item in entries:
                if q in item.lower():
                    return os.path.join(sdir, item)

        return None

    def execute(self, action: str, params: dict | None = None) -> dict:
        """Execute action on File Explorer."""
        params = params or {}
        start_time = time.time()
        action_lower = action.lower()

        try:
            if action_lower in ("open", "navigate", "goto"):
                path = params.get("path", params.get("filepath", params.get("filename", "")))
                target_path = self._normalize_path(path) if path else os.path.expanduser("~")

                # Always launch explorer.exe at target_path to guarantee a visible window on screen
                if os.path.exists(target_path):
                    subprocess.Popen(f'explorer.exe "{target_path}"')
                else:
                    subprocess.Popen('explorer.exe')

                self._current_path = target_path
                time.sleep(0.8)

                window = self.get_window()
                if window:
                    window_manager.focus_window(window)

                return {
                    "status": "success",
                    "action": action_lower,
                    "details": f"Opened File Explorer at '{target_path}'",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            elif action_lower in ("create_folder", "new_folder", "mkdir"):
                folder_name = params.get("folder_name", params.get("name", "New Folder"))
                folder_name = re.sub(r"^(?:named\s+|called\s+)", "", folder_name, flags=re.IGNORECASE).strip()
                
                base_path = params.get("path", "")
                target_dir = self._normalize_path(base_path) if base_path else self._current_path

                full_folder_path = os.path.join(target_dir, folder_name)
                os.makedirs(full_folder_path, exist_ok=True)
                ExplorerAgent._last_created_folder = full_folder_path

                window = self.get_window()
                if window:
                    window_manager.focus_window(window)
                    # Refresh active Explorer window (F5) so single new folder appears
                    input_handler.send_key("f5")
                else:
                    subprocess.Popen(f'explorer.exe "{target_dir}"')
                    time.sleep(1.0)
                    window = self.get_window()
                    if window:
                        window_manager.focus_window(window)

                return {
                    "status": "success",
                    "action": "create_folder",
                    "details": f"Created folder '{full_folder_path}'",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            elif action_lower in ("create_file", "new_file", "touch"):
                file_name = params.get("file_name", params.get("name", "new_file.txt"))
                file_name = re.sub(r"^(?:named\s+|called\s+)", "", file_name, flags=re.IGNORECASE).strip()
                if not os.path.splitext(file_name)[1]:
                    file_name += ".txt"

                content = params.get("content", "")
                base_path = params.get("path", "")
                target_dir = self._normalize_path(base_path) if base_path else self._current_path

                full_file_path = os.path.join(target_dir, file_name)

                try:
                    os.makedirs(target_dir, exist_ok=True)
                    with open(full_file_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    details = f"Created file '{full_file_path}'"
                except PermissionError:
                    # Windows UAC protects Program Files; fallback to Desktop and inform user
                    fallback_dir = os.path.join(os.path.expanduser("~"), "Desktop")
                    full_file_path = os.path.join(fallback_dir, file_name)
                    with open(full_file_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    details = f"Created file '{full_file_path}' on Desktop (System folder '{target_dir}' is write-protected without Admin privileges)"

                window = self.get_window()
                if window:
                    window_manager.focus_window(window)
                    # Refresh active Explorer window (F5) so new file appears immediately
                    input_handler.send_key("f5")
                else:
                    subprocess.Popen(f'explorer.exe "{target_dir}"')
                    time.sleep(1.0)
                    window = self.get_window()
                    if window:
                        window_manager.focus_window(window)

                return {
                    "status": "success",
                    "action": "create_file",
                    "details": details,
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            elif action_lower in ("search", "find"):
                query = params.get("query", "")
                window = self.get_window()
                
                if not window:
                    subprocess.Popen('explorer.exe')
                    time.sleep(1.0)
                    window = self.get_window()

                if window:
                    window_manager.focus_window(window)
                    # Focus search box in Explorer via Ctrl+F
                    input_handler.send_hotkey("ctrl", "f")
                    time.sleep(0.3)
                    input_handler.type_text(query)
                    input_handler.send_key("enter")
                    time.sleep(1.5)  # Wait for search results to populate

                return {
                    "status": "success",
                    "action": "search",
                    "details": f"Searched for '{query}' in File Explorer",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            elif action_lower in ("open_item", "open_file", "open_selected"):
                filename = params.get("filename", params.get("path", params.get("name", "")))
                found_path = None

                if filename:
                    norm = self._normalize_path(filename)
                    if os.path.exists(norm) and not os.path.isdir(norm):
                        found_path = norm
                    else:
                        user_home = os.path.expanduser("~")
                        onedrive_home = os.path.join(user_home, "OneDrive")

                        search_dirs = [
                            self._current_path,
                            os.path.join(onedrive_home, "Pictures", "Camera Roll"),
                            os.path.join(onedrive_home, "Pictures"),
                            os.path.join(user_home, "Pictures"),
                            os.path.join(onedrive_home, "Videos"),
                            os.path.join(user_home, "Videos"),
                            os.path.join(onedrive_home, "Downloads"),
                            os.path.join(user_home, "Downloads"),
                            os.path.join(onedrive_home, "Documents"),
                            os.path.join(user_home, "Documents"),
                            os.path.join(onedrive_home, "Desktop"),
                            os.path.join(user_home, "Desktop"),
                        ]
                        last_created = ExplorerAgent.get_last_created_folder()
                        if last_created and os.path.isdir(last_created):
                            search_dirs.insert(0, last_created)

                        for sdir in search_dirs:
                            res = self._find_matching_file(sdir, filename)
                            if res:
                                found_path = res
                                break

                if found_path:
                    # Focus existing File Explorer window if already open, otherwise open one highlighting the file
                    window = self.get_window()
                    if window:
                        window_manager.focus_window(window)
                    else:
                        try:
                            subprocess.Popen(f'explorer.exe /select,"{found_path}"')
                            time.sleep(0.3)
                            window = self.get_window()
                            if window:
                                window_manager.focus_window(window)
                        except Exception:
                            pass
                    # Launch target file in default application
                    os.startfile(found_path)
                    details = f"Opened file '{found_path}'"
                elif filename:
                    # Bring up active File Explorer window at current path if specific file wasn't located
                    window = self.get_window()
                    if window:
                        window_manager.focus_window(window)
                    details = f"Could not find exact file '{filename}'; opened active File Explorer window at '{self._current_path}'"
                else:
                    window = self.get_window()
                    if window:
                        window_manager.focus_window(window)
                        input_handler.send_key("tab")
                        time.sleep(0.3)
                        input_handler.send_key("down")
                        time.sleep(0.3)
                        input_handler.send_key("enter")
                    details = f"Opened selected item in File Explorer results ({filename or 'current item'})"

                return {
                    "status": "success",
                    "action": "open_item",
                    "details": details,
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            elif action_lower == "select_all":
                window = self.get_window()
                if window:
                    window_manager.focus_window(window)
                    input_handler.send_hotkey("ctrl", "a")

                return {
                    "status": "success",
                    "action": "select_all",
                    "details": "Selected all items in File Explorer",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            elif action_lower == "copy":
                window = self.get_window()
                if window:
                    window_manager.focus_window(window)
                    input_handler.send_hotkey("ctrl", "c")

                return {
                    "status": "success",
                    "action": "copy",
                    "details": "Copied selected items in File Explorer",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            elif action_lower == "paste":
                window = self.get_window()
                if window:
                    window_manager.focus_window(window)
                    input_handler.send_hotkey("ctrl", "v")

                return {
                    "status": "success",
                    "action": "paste",
                    "details": "Pasted items in File Explorer",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            elif action_lower in ("delete", "remove"):
                window = self.get_window()
                if window:
                    window_manager.focus_window(window)
                    input_handler.send_key("delete")

                return {
                    "status": "success",
                    "action": "delete",
                    "details": "Triggered delete action in File Explorer",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            elif action_lower == "close":
                window = self.get_window()
                if window:
                    window_manager.close_window(window)
                    self._window = None

                return {
                    "status": "success",
                    "action": "close",
                    "details": "Closed File Explorer window",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            else:
                return {
                    "status": "failure",
                    "action": action,
                    "details": f"Unknown action '{action}' for ExplorerAgent",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

        except Exception as e:
            return {
                "status": "failure",
                "action": action,
                "details": f"ExplorerAgent execution error: {str(e)}",
                "duration_ms": int((time.time() - start_time) * 1000),
            }

    def verify(self, expected_state: dict) -> dict:
        """Verify Explorer state."""
        window = self.get_window()
        actual = {"window_exists": window is not None}

        if "folder_exists" in expected_state:
            folder_path = self._normalize_path(expected_state["folder_exists"])
            actual["folder_exists"] = os.path.isdir(folder_path)

        if "file_exists" in expected_state:
            file_path = self._normalize_path(expected_state["file_exists"])
            actual["file_exists"] = os.path.isfile(file_path)

        verified = True
        for k, v in expected_state.items():
            if actual.get(k) != v:
                verified = False
                break

        return {
            "verified": verified,
            "expected": expected_state,
            "actual": actual,
            "details": f"Verified Explorer state: {verified}",
        }
