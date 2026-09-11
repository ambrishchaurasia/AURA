"""
AURA Tiered UI Resolver

Coordinates the resolution of logical UI intents to physical elements
using a fallback chain:
- Tier 1: Deterministic App Map lookup
- Tier 2: Live UIA heuristic tree search
- Tier 3: Vision/OCR (Stubbed)
"""

from __future__ import annotations
from typing import Optional

from automation.core import element_finder
from automation.core.app_map import AppMap


class TieredResolver:
    """Coordinates tiered resolution of UI elements."""

    def __init__(self, app_map: Optional[AppMap] = None):
        self.app_map = app_map

    def resolve(self, window, logical_name: str, fallback_heuristics: dict = None) -> tuple[Optional[object], int]:
        """
        Attempt to resolve a logical UI element through the tiered strategy.
        
        Args:
            window: The root window to search within
            logical_name: Semantic name (e.g., "text_editor")
            fallback_heuristics: kwargs for Tier 2 fallback search
            
        Returns:
            (element, tier_used)
            element is None if all tiers failed.
        """
        # --- TIER 1: App Map ---
        if self.app_map:
            identifiers_list = self.app_map.get_all_identifiers(logical_name)
            for ids in identifiers_list:
                criteria = {k: v for k, v in ids.items() if v}
                if criteria:
                    el = element_finder.find_element(window, **criteria)
                    if el:
                        return el, 1

        # --- TIER 2: Live UIA Heuristics ---
        # If Tier 1 failed or no map exists, try fuzzy search if heuristics provided
        if fallback_heuristics:
            el = element_finder.find_element(window, **fallback_heuristics)
            if el:
                return el, 2
                
        # Fallback to searching by logical name directly as a last resort in Tier 2
        clean_name = logical_name.replace("_", " ")
        el = element_finder.find_element(window, name_contains=clean_name)
        if el:
            return el, 2

        # --- TIER 3: Vision/OCR (Stub) ---
        # In a full implementation, we would screenshot the window and use OCR
        # to find coordinates, returning a proxy element.
        print(f"[TieredResolver] Tier 1 and 2 failed for '{logical_name}'. Tier 3 (Vision) is stubbed.")
        
        return None, 0
