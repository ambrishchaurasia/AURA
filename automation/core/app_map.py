"""
AURA App Map Parser

Provides the AppMap class which loads and parses an application map JSON file,
making it easy for agents to resolve semantic element names to physical UIA identifiers.
"""

from __future__ import annotations
import json
import os
from typing import Optional


class AppMap:
    """Represents a loaded Application UI Map."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.application = ""
        self.version = ""
        self.elements = {}
        
        self._load()

    def _load(self):
        """Load the JSON app map."""
        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"App map not found: {self.filepath}")
            
        with open(self.filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        self.application = data.get("application", "")
        self.version = data.get("version", "")
        self.elements = data.get("elements", {})

    def get_element_def(self, logical_name: str) -> Optional[dict]:
        """
        Get the definition for a logical element name.
        
        Args:
            logical_name: The semantic name (e.g., "text_editor")
            
        Returns:
            Dictionary containing 'identifiers', 'alternatives', and 'actions'
        """
        # Exact match
        if logical_name in self.elements:
            return self.elements[logical_name]
            
        # Try fuzzy match (ignore case/spaces/underscores)
        clean_target = logical_name.lower().replace(" ", "").replace("_", "")
        for key, value in self.elements.items():
            clean_key = key.lower().replace(" ", "").replace("_", "")
            if clean_key == clean_target:
                return value
                
        return None

    def get_all_identifiers(self, logical_name: str) -> list[dict]:
        """
        Get a list of all identifier dicts for an element (primary + alternatives).
        Useful for iterating through fallback lookup strategies.
        """
        el_def = self.get_element_def(logical_name)
        if not el_def:
            return []
            
        results = []
        if "identifiers" in el_def:
            results.append(el_def["identifiers"])
            
        if "alternatives" in el_def and isinstance(el_def["alternatives"], list):
            results.extend(el_def["alternatives"])
            
        return results

    def supports_action(self, logical_name: str, action: str) -> bool:
        """Check if a logical element is expected to support an action."""
        el_def = self.get_element_def(logical_name)
        if not el_def:
            return False
            
        actions = el_def.get("actions", [])
        return action in actions


def load_app_map(app_name: str, maps_dir: str = None) -> Optional[AppMap]:
    """
    Helper to load an app map by application name.
    
    Args:
        app_name: Name of the application (e.g., "notepad")
        maps_dir: Directory containing maps. Defaults to ../../app_maps
    """
    if maps_dir is None:
        # Default relative to this file: automation/core/app_map.py -> app_maps/
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        maps_dir = os.path.join(base_dir, "app_maps")
        
    filepath = os.path.join(maps_dir, f"{app_name}.json")
    
    try:
        return AppMap(filepath)
    except FileNotFoundError:
        return None
