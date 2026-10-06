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
    Set focus to an element cleanly without mouse movement hanging.
    """
    try:
        from automation.core import window_manager
        if window_manager.focus_window(element):
            return True

        try:
            if hasattr(element, 'set_focus'):
                element.set_focus()
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[InputHandler] set_focus notice: {e}")
        return False


def type_text(element=None, text: str = "", method: str = "clipboard", **kwargs) -> bool:
    """
    Type text at the current caret position.

    Supports both:
      type_text(element, text)
      type_text("text_string")
    """
    if isinstance(element, str) and not text:
        text = element
        element = None

    if element is not None:
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
        if element is not None:
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


def send_hotkey(*keys: str) -> bool:
    """Send hotkey combination like send_hotkey('ctrl', 'l')."""
    return send_keys("+".join(keys))


def send_key(key: str) -> bool:
    """Send a single key press like send_key('enter')."""
    return send_keys(key)


def send_key_sequence(element, keys: str) -> bool:
    """
    Send a key sequence or shortcut to a specific element cleanly.
    """
    try:
        import pyautogui
        pyautogui.FAILSAFE = False

        if element is not None:
            set_focus(element)

        # Parse modifiers: ^ -> ctrl, % -> alt, + -> shift
        key_map = {"^": "ctrl", "%": "alt", "+": "shift"}
        mods = []
        clean_key = keys.lower()
        for char in ["^", "%", "+"]:
            if char in clean_key:
                mods.append(key_map[char])
                clean_key = clean_key.replace(char, "")

        if mods and clean_key:
            pyautogui.hotkey(*mods, clean_key)
            time.sleep(0.15)
            return True
        elif clean_key and len(clean_key) <= 5:
            pyautogui.press(clean_key)
            time.sleep(0.15)
            return True

        if element is not None:
            try:
                element.type_keys(keys, pause=0.02)
                time.sleep(0.15)
                return True
            except Exception:
                pass
        return False
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
        pyautogui.FAILSAFE = False

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
