"""
AURA App Map Crawler

Crawls the UIA tree of a given application window and generates
a structured JSON representation of the UI elements. This can be used
to bootstrap App Maps.
"""

from __future__ import annotations
import json
import os
from typing import Any

from pywinauto import ElementNotFoundError

class UIACrawler:
    """Crawls a pywinauto window and extracts its UI hierarchy."""

    def __init__(self):
        self.elements = []
        
    def crawl(self, window, max_depth: int = 5) -> dict:
        """
        Crawl a window and return a dictionary of discovered elements.
        
        Returns a structure suitable for saving as an initial App Map.
        """
        self.elements = []
        
        try:
            wrapper = window.wrapper_object() if hasattr(window, 'wrapper_object') else window
            app_name = (wrapper.element_info.name or "unknown").split("-")[-1].strip().lower()
        except Exception:
            app_name = "unknown_app"
            
        print(f"Crawling {app_name}...")
        self._crawl_recursive(window, depth=0, max_depth=max_depth, path="")
        
        # Convert crawled elements into a flat map format
        app_map = {
            "application": app_name,
            "version": "1.0",
            "elements": {}
        }
        
        for i, el in enumerate(self.elements):
            # Generate a readable key if possible
            name = el.get("name", "").lower()
            ctrl_type = el.get("control_type", "").lower()
            
            key = f"{name}_{ctrl_type}".strip("_")
            # If empty, just use index
            if not key:
                key = f"element_{i}"
                
            # Ensure unique key
            base_key = key
            counter = 1
            while key in app_map["elements"]:
                key = f"{base_key}_{counter}"
                counter += 1
                
            app_map["elements"][key] = {
                "identifiers": {
                    "name": el.get("name"),
                    "control_type": el.get("control_type"),
                    "class_name": el.get("class_name"),
                    "automation_id": el.get("automation_id")
                },
                "path": el.get("path"),
                "actions": self._guess_actions(el.get("control_type", ""))
            }
            
        return app_map

    def _crawl_recursive(self, element, depth: int, max_depth: int, path: str):
        if depth > max_depth:
            return

        try:
            info = element.element_info
            
            # Skip invisible elements to reduce noise
            if not info.visible:
                return
                
            el_data = {
                "name": info.name or "",
                "control_type": info.control_type or "",
                "class_name": info.class_name or "",
                "automation_id": info.automation_id or "",
                "path": path,
            }
            
            # Only record interesting elements (skip empty panes/windows without IDs)
            is_interesting = (
                el_data["name"] or 
                el_data["automation_id"] or 
                el_data["control_type"] in ("Button", "Edit", "Document", "MenuItem", "TabItem")
            )
            
            if is_interesting and depth > 0: # Skip the root window itself in elements
                self.elements.append(el_data)
                
            try:
                children = element.children()
                for i, child in enumerate(children):
                    child_path = f"{path}/{i}" if path else str(i)
                    self._crawl_recursive(child, depth + 1, max_depth, child_path)
            except ElementNotFoundError:
                pass
                
        except Exception as e:
            # Skip elements that cause errors
            pass
            
    def _guess_actions(self, control_type: str) -> list[str]:
        """Guess supported actions based on control type."""
        ct = control_type.lower()
        if ct in ("edit", "document"):
            return ["type", "read", "select_all", "copy", "paste"]
        elif ct == "button":
            return ["click"]
        elif ct == "menuitem":
            return ["click"]
        elif ct == "checkbox":
            return ["toggle", "read"]
        return []

def save_app_map(app_map: dict, output_path: str):
    """Save the app map to a JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(app_map, f, indent=2, ensure_ascii=False)
    print(f"App map saved to {output_path}")
