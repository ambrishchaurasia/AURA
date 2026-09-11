"""
AURA Window Manager — Find, launch, focus, and manage application windows.

Uses pywinauto's Application API for reliable window management.
Handles Windows 11 UWP/packaged apps (like new Notepad) correctly.
"""

from __future__ import annotations
import subprocess
import time
from typing import Optional

from pywinauto import Application, Desktop


def find_window(
    title_contains: str = None,
    process_name: str = None,
    class_name: str = None,
) -> Optional[object]:
    """
    Find a top-level window matching the given criteria.

    Uses pywinauto Desktop enumeration which is the most reliable
    for UWP/packaged apps like Win11 Notepad.
    """
    desktop = Desktop(backend="uia")
    for window in desktop.windows():
        try:
            info = window.element_info
            wt = (info.name or "").strip()
            wt_lower = wt.lower()
            cls = (info.class_name or "").strip()

            if class_name:
                if class_name.lower() != cls.lower():
                    continue

            if title_contains:
                tc_lower = title_contains.lower()
                # Safeguard: if looking for Notepad, do not match editor tabs like "notepad.json - VS Code"
                if tc_lower == "notepad":
                    is_real_notepad = (
                        wt_lower == "notepad"
                        or wt_lower.endswith("- notepad")
                        or wt_lower.endswith("– notepad")
                        or wt_lower.endswith("— notepad")
                        or cls.lower() == "notepad"
                    )
                    if not is_real_notepad:
                        continue
                elif tc_lower not in wt_lower:
                    continue

            # Return wrapped window using exact handle
            return desktop.window(handle=info.handle)
        except Exception:
            continue

    return None


def find_window_simple(title_contains: str) -> Optional[object]:
    """
    Simplified window finder — searches by title substring.
    """
    return find_window(title_contains=title_contains)


def launch_application(
    executable: str,
    args: list[str] = None,
    wait_title: str = None,
    timeout: float = 10.0,
) -> Optional[object]:
    """
    Launch an application and wait for its window to appear.

    Uses Application.start for reliable process tracking, which handles
    UWP/packaged apps (like Windows 11 Notepad) correctly.

    Args:
        executable: Path or name of the executable
        args: Command-line arguments
        wait_title: Expected window title substring to wait for
        timeout: Maximum seconds to wait for window

    Returns:
        pywinauto window wrapper, or None if window didn't appear
    """
    cmd = executable
    if args:
        cmd = f"{executable} {' '.join(args)}"

    if wait_title is None:
        wait_title = executable.split("\\")[-1].split(".")[0]

    # Strategy 1: Use Application.start for direct process tracking
    try:
        app = Application(backend="uia").start(cmd, timeout=int(timeout))
        time.sleep(1.0)  # Let the window fully initialize

        # Try to get the window
        try:
            window = app.top_window()
            if window.exists():
                return window
        except Exception:
            pass
    except Exception as e:
        print(f"[WindowManager] Application.start failed: {e}")

    # Strategy 2: Fall back to subprocess + connect by title
    try:
        subprocess.Popen(executable)
        time.sleep(1.5)
    except Exception as e:
        print(f"[WindowManager] subprocess failed: {e}")
        return None

    # Wait for window to appear via connect
    start = time.time()
    while time.time() - start < timeout:
        try:
            app = Application(backend="uia").connect(
                title_re=f".*{wait_title}.*",
                timeout=1,
            )
            window = app.top_window()
            if window.exists():
                return window
        except Exception:
            pass
        time.sleep(0.5)

    # Strategy 3: Desktop enumeration
    window = find_window(title_contains=wait_title)
    if window is not None:
        return window

    print(f"[WindowManager] Timeout waiting for window: {wait_title}")
    return None


def focus_window(window) -> bool:
    """
    Bring a window to the foreground and set focus.

    Args:
        window: pywinauto window wrapper
    """
    try:
        wrapper = window
        # Get the actual wrapper if needed
        if hasattr(window, 'wrapper_object'):
            try:
                wrapper = window.wrapper_object()
            except Exception:
                pass

        if hasattr(wrapper, 'is_minimized') and wrapper.is_minimized():
            wrapper.restore()
            time.sleep(0.2)

        wrapper.set_focus()
        time.sleep(0.2)
        return True
    except Exception as e:
        print(f"[WindowManager] Failed to focus window: {e}")
        return False


def close_window(window) -> bool:
    """
    Close a window.

    Args:
        window: pywinauto window wrapper
    """
    try:
        window.close()
        return True
    except Exception as e:
        print(f"[WindowManager] Failed to close window: {e}")
        return False


def get_window_info(window) -> dict:
    """
    Get detailed information about a window.

    Returns dict with title, class_name, rectangle, process_id, is_visible, etc.
    """
    try:
        info = window.element_info
        rect = info.rectangle
        return {
            "title": info.name or "",
            "class_name": info.class_name or "",
            "process_id": info.process_id,
            "rectangle": {
                "left": rect.left if rect else 0,
                "top": rect.top if rect else 0,
                "right": rect.right if rect else 0,
                "bottom": rect.bottom if rect else 0,
            },
            "is_visible": info.visible,
            "is_enabled": info.enabled,
        }
    except Exception as e:
        return {"error": str(e)}
