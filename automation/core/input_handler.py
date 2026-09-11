"""
AURA Input Handler — Safe keyboard/mouse input for automation.

KEY RULES:
1. Typing INSERTS at the CURRENT CARET POSITION — never replaces.
2. Never uses Ctrl+A before typing.
3. Never blindly clicks the center of a text area.
4. Prefers UIA keyboard input via set_focus() + type_keys().
5. Falls back to pyautogui only when necessary.
6. If the user has manually positioned the caret, typing occurs there.
"""

from __future__ import annotations
import time


def set_focus(element) -> bool:
    """
    Set focus to an element without moving the caret.

    Uses UIA SetFocus which brings the element into focus
    without altering selection or caret position.
    """
    try:
        element.set_focus()
        time.sleep(0.15)
        return True
    except Exception as e:
        print(f"[InputHandler] set_focus failed: {e}")
        return False


def type_text(element, text: str, method: str = "clipboard") -> bool:
    """
    Type text at the current caret position.

    Uses clipboard paste (Ctrl+V) as the primary method because Windows 11
    UWP Notepad has an OS-level key-bounce/repeat bug with simulated hardware
    keystrokes (which causes stuttered letters like 'TTSALA' or 'IIISH').
    Clipboard paste is 100% reliable, preserves exact casing, Unicode, and caret position.

    Args:
        element: UIA element to type into
        text: The text to type
        method: 'clipboard' (default and recommended) or 'keystroke'
    """
    if not set_focus(element):
        return False

    time.sleep(0.1)

    # Strategy 1: Clipboard paste (zero key-repeat bugs, instant, handles all characters)
    if method == "clipboard":
        if _type_via_clipboard(text):
            return True

    # Strategy 2: pyautogui write (with safe inter-key interval)
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.02
        if _is_ascii(text):
            pyautogui.write(text, interval=0.04)
            return True
        else:
            return _type_via_clipboard(text)
    except Exception as e:
        print(f"[InputHandler] pyautogui fallback failed: {e}")

    # Strategy 3: pywinauto type_keys with safe pause
    try:
        escaped = _escape_for_type_keys(text)
        element.type_keys(escaped, with_spaces=True, set_foreground=True, pause=0.05)
        return True
    except Exception as e:
        print(f"[InputHandler] type_keys fallback failed: {e}")

    return False


def send_keys(keys: str) -> bool:
    """
    Send keyboard shortcuts/special keys.

    Uses pyautogui.hotkey for key combinations.
    Example: send_keys("ctrl+s") for Ctrl+S

    Args:
        keys: Key combination string (e.g., "ctrl+s", "enter", "tab")
    """
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        parts = keys.lower().split("+")
        pyautogui.hotkey(*parts)
        time.sleep(0.2)
        return True
    except Exception as e:
        print(f"[InputHandler] send_keys failed for {keys!r}: {e}")
        return False


def send_key_sequence(element, keys: str) -> bool:
    """
    Send a key sequence to a specific element using pywinauto.

    Args:
        element: Target UIA element
        keys: pywinauto key sequence (e.g., "^s" for Ctrl+S)
    """
    try:
        if not set_focus(element):
            return False
        element.type_keys(keys)
        time.sleep(0.2)
        return True
    except Exception as e:
        print(f"[InputHandler] send_key_sequence failed: {e}")
        return False


def _escape_for_type_keys(text: str) -> str:
    """
    Escape special characters for pywinauto's type_keys().

    Characters {, }, +, ^, %, (, ), ~ are special in pywinauto.
    They need to be wrapped in braces: { → {{}
    """
    special = {
        "{": "{{}",
        "}": "{}}",
        "+": "{+}",
        "^": "{^}",
        "%": "{%}",
        "(": "{(}",
        ")": "{)}",
        "~": "{~}",
    }
    result = []
    for char in text:
        if char in special:
            result.append(special[char])
        else:
            result.append(char)
    return "".join(result)


def _is_ascii(text: str) -> bool:
    """Check if text contains only ASCII characters."""
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _type_via_clipboard(text: str) -> bool:
    """Type text by copying to clipboard and pasting via Ctrl+V."""
    try:
        import pyperclip
        import pyautogui

        old_clip = None
        try:
            old_clip = pyperclip.paste()
        except Exception:
            pass

        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)

        # Restore original clipboard if it was different
        if old_clip is not None and old_clip != text:
            try:
                pyperclip.copy(old_clip)
            except Exception:
                pass
        return True
    except Exception as e:
        print(f"[InputHandler] clipboard paste failed: {e}")
        return False
