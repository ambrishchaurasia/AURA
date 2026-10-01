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
    
    # Fast path: use pywinauto's built-in filtering which is much faster
    # than fetching all windows and filtering in Python
    try:
        if title_contains:
            # Special case for notepad to avoid matching VS Code tabs
            if title_contains.lower() == "notepad":
                windows = desktop.windows(title_re="(?i).*notepad.*")
                for window in windows:
                    info = window.element_info
                    wt = (info.name or "").strip().lower()
                    cls = (info.class_name or "").strip().lower()
                    if class_name and class_name.lower() != cls:
                        continue
                    
                    is_real_notepad = (
                        wt == "notepad"
                        or wt.endswith("- notepad")
                        or wt.endswith("– notepad")
                        or wt.endswith("— notepad")
                        or cls == "notepad"
                    )
                    if is_real_notepad:
                        return desktop.window(handle=info.handle)
            else:
                windows = desktop.windows(title_re=f"(?i).*{title_contains}.*")
                for window in windows:
                    info = window.element_info
                    cls = (info.class_name or "").strip().lower()
                    if class_name and class_name.lower() != cls:
                        continue
                    return desktop.window(handle=info.handle)
                    
        elif class_name:
            windows = desktop.windows(class_name=class_name)
            if windows:
                return desktop.window(handle=windows[0].element_info.handle)
                
        else:
            # Fallback to scanning everything (slow)
            for window in desktop.windows():
                return desktop.window(handle=window.element_info.handle)
    except Exception:
        pass

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
        import sys
        print(f"[WindowManager] Application.start failed: {e}", file=sys.stderr)

    # Strategy 2: Fall back to subprocess + connect by title
    try:
        import subprocess
        subprocess.Popen(
            executable, 
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(1.5)
    except Exception as e:
        import sys
        print(f"[WindowManager] subprocess failed: {e}", file=sys.stderr)
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

    import sys
    print(f"[WindowManager] Timeout waiting for window: {wait_title}", file=sys.stderr)
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
        import sys
        print(f"[WindowManager] Failed to focus window: {e}", file=sys.stderr)
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
        import sys
        print(f"[WindowManager] Failed to close window: {e}", file=sys.stderr)
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
