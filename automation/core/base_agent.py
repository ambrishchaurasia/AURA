"""
AURA Base Agent — Abstract contract for all application agents.

Every App Agent must implement this interface:
- get_capabilities(): What actions this agent supports
- resolve(intent): Resolve an intent to a UI target
- execute(action, params): Execute an action
- verify(expected_state): Verify the post-action state
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Abstract base class for all AURA application agents."""

    @property
    @abstractmethod
    def app_name(self) -> str:
        """Human-readable application name."""
        ...

    @property
    @abstractmethod
    def process_name(self) -> str:
        """Process executable name (e.g., 'notepad.exe')."""
        ...

    @abstractmethod
    def get_agent_name(self) -> str:
        """Return the universal name of this agent (e.g., 'notepad', 'explorer')."""
        ...

    @abstractmethod
    def get_llm_capabilities(self) -> str:
        """
        Return a formatted string describing what actions this agent supports,
        which will be injected into the LLM Orchestrator's prompt.
        
        Example:
        - `open`: Opens the app (No params).
        - `type`: Types text. Params: `{"text": "<string>"}`.
        """
        ...

    @abstractmethod
    def get_capabilities(self) -> dict:
        """
        Return a dictionary describing this agent's supported operations.

        Returns:
            {
                "application": "notepad",
                "actions": {
                    "open": {
                        "description": "Open or find the application",
                        "parameters": {},
                        "safety": "safe"
                    },
                    "type": {
                        "description": "Type text at the current caret position",
                        "parameters": {"text": "string"},
                        "safety": "safe"
                    },
                    ...
                }
            }
        """
        ...

    @abstractmethod
    def resolve(self, intent: str, **kwargs) -> dict:
        """
        Resolve a user intent to actionable target information.

        Args:
            intent: The action intent (e.g., "type", "save_as")

        Returns:
            {
                "action": "type",
                "target_element": <element info or None>,
                "resolver_tier": 1,
                "confidence": 0.95
            }
        """
        ...

    @abstractmethod
    def execute(self, action: str, params: dict | None = None) -> dict:
        """
        Execute an action on the application.

        Args:
            action: Action name (e.g., "type", "open", "save")
            params: Action parameters (e.g., {"text": "Hello"})

        Returns:
            {
                "status": "success" | "failure",
                "action": "type",
                "details": "...",
                "duration_ms": 123
            }
        """
        ...

    @abstractmethod
    def verify(self, expected_state: dict) -> dict:
        """
        Verify the application's current state against expectations.

        Args:
            expected_state: What should be true after an action.
                e.g., {"text_contains": "Hello World"}
                e.g., {"window_exists": True}
                e.g., {"menu_open": "File"}

        Returns:
            {
                "verified": True | False,
                "expected": {...},
                "actual": {...},
                "details": "..."
            }
        """
        ...

    def get_window(self):
        """
        Get the application's main window wrapper.
        Subclasses should implement or use WindowManager.
        """
        return None

    def is_running(self) -> bool:
        """Check if the application is currently running."""
        window = self.get_window()
        return window is not None
