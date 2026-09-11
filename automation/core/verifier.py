"""
AURA Verifier — Post-action state verification.

Every action should have an expected state. The verifier checks whether
the actual UI state matches the expected state after an action.

If verification fails, the system does NOT blindly continue.
"""

from __future__ import annotations
import time
from typing import Optional

from automation.core.element_finder import find_element, _get_element_info


class VerificationResult:
    """Result of a verification check."""

    def __init__(self, verified: bool, expected: dict, actual: dict, details: str = ""):
        self.verified = verified
        self.expected = expected
        self.actual = actual
        self.details = details

    def to_dict(self) -> dict:
        return {
            "verified": self.verified,
            "expected": self.expected,
            "actual": self.actual,
            "details": self.details,
        }

    def __repr__(self):
        status = "PASS" if self.verified else "FAIL"
        return f"VerificationResult({status}: {self.details})"


def verify_text_contains(window, text: str, control_name: str = None) -> VerificationResult:
    """
    Verify that a text control contains the expected text.

    Works by finding the text editing area and reading its value/text.

    Args:
        window: Application window
        text: Expected text content
        control_name: Name of the text control to check
    """
    try:
        # Find the text editing element
        edit_element = None
        if control_name:
            edit_element = find_element(window, name=control_name)

        if edit_element is None:
            # Try common edit control types
            edit_element = find_element(window, control_type="Edit")

        if edit_element is None:
            edit_element = find_element(window, control_type="Document")

        if edit_element is None:
            return VerificationResult(
                verified=False,
                expected={"text_contains": text},
                actual={"error": "No text control found"},
                details="Could not find a text editing control",
            )

        # Read the current text content
        actual_text = _read_element_text(edit_element)

        if text in actual_text:
            return VerificationResult(
                verified=True,
                expected={"text_contains": text},
                actual={"text": actual_text},
                details=f"Text '{text}' found in control",
            )
        else:
            return VerificationResult(
                verified=False,
                expected={"text_contains": text},
                actual={"text": actual_text[:200]},  # Truncate for readability
                details=f"Text '{text}' NOT found in control",
            )

    except Exception as e:
        return VerificationResult(
            verified=False,
            expected={"text_contains": text},
            actual={"error": str(e)},
            details=f"Verification error: {e}",
        )


def verify_window_exists(title_contains: str) -> VerificationResult:
    """Verify that a window with the given title exists."""
    from automation.core.window_manager import find_window_simple

    window = find_window_simple(title_contains)
    exists = window is not None

    return VerificationResult(
        verified=exists,
        expected={"window_exists": True, "title_contains": title_contains},
        actual={"window_exists": exists},
        details=f"Window '{title_contains}' {'found' if exists else 'NOT found'}",
    )


def verify_window_closed(title_contains: str) -> VerificationResult:
    """Verify that a window with the given title does NOT exist."""
    from automation.core.window_manager import find_window_simple

    window = find_window_simple(title_contains)
    closed = window is None

    return VerificationResult(
        verified=closed,
        expected={"window_closed": True, "title_contains": title_contains},
        actual={"window_closed": closed},
        details=f"Window '{title_contains}' {'closed' if closed else 'still open'}",
    )


def verify_element_exists(window, name: str = None, control_type: str = None) -> VerificationResult:
    """Verify that a specific UI element exists and is visible."""
    element = find_element(window, name=name, control_type=control_type)
    exists = element is not None

    expected = {"element_exists": True}
    if name:
        expected["name"] = name
    if control_type:
        expected["control_type"] = control_type

    return VerificationResult(
        verified=exists,
        expected=expected,
        actual={"element_exists": exists},
        details=f"Element (name={name}, type={control_type}) {'found' if exists else 'NOT found'}",
    )


def verify_element_focused(element) -> VerificationResult:
    """Verify that an element has keyboard focus."""
    try:
        has_focus = element.has_keyboard_focus()
        return VerificationResult(
            verified=has_focus,
            expected={"has_focus": True},
            actual={"has_focus": has_focus},
            details=f"Element {'has' if has_focus else 'does NOT have'} keyboard focus",
        )
    except Exception as e:
        return VerificationResult(
            verified=False,
            expected={"has_focus": True},
            actual={"error": str(e)},
            details=f"Focus verification error: {e}",
        )


def _read_element_text(element) -> str:
    """Read text content from a UI element using available patterns."""
    # Try ValuePattern
    try:
        iface = element.iface_value
        if iface:
            return iface.CurrentValue or ""
    except Exception:
        pass

    # Try TextPattern
    try:
        text_pattern = element.iface_text
        if text_pattern:
            return text_pattern.DocumentRange.GetText(-1) or ""
    except Exception:
        pass

    # Try window_text() as fallback
    try:
        return element.window_text() or ""
    except Exception:
        pass

    # Try legacy pattern
    try:
        return element.legacy_properties().get("Value", "")
    except Exception:
        pass

    return ""
