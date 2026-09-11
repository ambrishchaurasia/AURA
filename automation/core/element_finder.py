"""
AURA Element Finder — Multi-property UIA element resolution.

Finds UI elements using multiple properties for robust matching:
- name
- control_type
- automation_id
- class_name
- path hierarchy

Supports exact and fuzzy matching. Never assumes AutomationId alone is stable.
"""

from __future__ import annotations
from typing import Optional


def _normalize(text: str) -> str:
    """Normalize text for comparison."""
    if text is None:
        return ""
    return text.strip().lower()


def _get_element_info(element) -> dict:
    """Extract all relevant UIA properties from an element."""
    try:
        info = element.element_info
        return {
            "name": info.name or "",
            "control_type": info.control_type or "",
            "automation_id": info.automation_id or "",
            "class_name": info.class_name or "",
            "rectangle": str(info.rectangle) if info.rectangle else "",
        }
    except Exception:
        return {
            "name": "",
            "control_type": "",
            "automation_id": "",
            "class_name": "",
            "rectangle": "",
        }


def _match_score(element_info: dict, criteria: dict) -> float:
    """
    Calculate a match score (0.0 to 1.0) between element info and search criteria.

    Uses multiple properties for robust matching.
    """
    score = 0.0
    total_weight = 0.0

    # Name match (highest weight)
    if "name" in criteria and criteria["name"]:
        total_weight += 3.0
        target = _normalize(criteria["name"])
        actual = _normalize(element_info["name"])
        if actual == target:
            score += 3.0
        elif target in actual or actual in target:
            score += 2.0

    # Control type match
    if "control_type" in criteria and criteria["control_type"]:
        total_weight += 2.0
        target = _normalize(criteria["control_type"])
        actual = _normalize(element_info["control_type"])
        if actual == target:
            score += 2.0

    # Automation ID match
    if "automation_id" in criteria and criteria["automation_id"]:
        total_weight += 2.0
        target = _normalize(criteria["automation_id"])
        actual = _normalize(element_info["automation_id"])
        if actual == target:
            score += 2.0
        elif target in actual or actual in target:
            score += 1.0

    # Class name match
    if "class_name" in criteria and criteria["class_name"]:
        total_weight += 1.0
        target = _normalize(criteria["class_name"])
        actual = _normalize(element_info["class_name"])
        if actual == target:
            score += 1.0

    if total_weight == 0:
        return 0.0

    return score / total_weight


def find_element(
    root,
    name: str = None,
    control_type: str = None,
    automation_id: str = None,
    class_name: str = None,
    max_depth: int = 15,
    min_score: float = 0.5,
) -> Optional[object]:
    """
    Find a UI element using multi-property matching.

    Traverses the UIA tree from root, scoring each element against
    the provided criteria. Returns the best match above min_score.

    Args:
        root: The root UIA element to search from
        name: Expected element name
        control_type: Expected control type (e.g., "Edit", "MenuItem")
        automation_id: Expected automation ID
        class_name: Expected class name
        max_depth: Maximum tree traversal depth
        min_score: Minimum match score to accept (0.0-1.0)

    Returns:
        The best matching element, or None
    """
    criteria = {
        "name": name,
        "control_type": control_type,
        "automation_id": automation_id,
        "class_name": class_name,
    }

    # Remove None criteria
    criteria = {k: v for k, v in criteria.items() if v is not None}

    if not criteria:
        return None

    best_match = None
    best_score = 0.0

    def _search(element, depth):
        nonlocal best_match, best_score

        if depth > max_depth:
            return

        info = _get_element_info(element)
        score = _match_score(info, criteria)

        if score > best_score and score >= min_score:
            best_score = score
            best_match = element

        # If perfect match, stop searching
        if score >= 1.0:
            return

        try:
            children = element.children()
        except Exception:
            children = []

        for child in children:
            _search(child, depth + 1)
            # Early exit on perfect match
            if best_score >= 1.0:
                return

    _search(root, 0)
    return best_match


def find_all_elements(
    root,
    name: str = None,
    control_type: str = None,
    automation_id: str = None,
    class_name: str = None,
    max_depth: int = 15,
    min_score: float = 0.5,
) -> list:
    """
    Find ALL UI elements matching the criteria above min_score.

    Returns a list of (element, score) tuples sorted by score descending.
    """
    criteria = {
        "name": name,
        "control_type": control_type,
        "automation_id": automation_id,
        "class_name": class_name,
    }
    criteria = {k: v for k, v in criteria.items() if v is not None}

    if not criteria:
        return []

    matches = []

    def _search(element, depth):
        if depth > max_depth:
            return

        info = _get_element_info(element)
        score = _match_score(info, criteria)

        if score >= min_score:
            matches.append((element, score))

        try:
            children = element.children()
        except Exception:
            children = []

        for child in children:
            _search(child, depth + 1)

    _search(root, 0)
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


def find_element_by_path(root, path: list[str]) -> Optional[object]:
    """
    Find an element by traversing a specific path of element names.

    Example path: ["Window", "MenuBar", "File"]

    This walks down the tree matching each path segment to child names.
    """
    current = root

    for segment in path:
        target = _normalize(segment)
        found = False

        try:
            children = current.children()
        except Exception:
            return None

        for child in children:
            info = _get_element_info(child)
            if _normalize(info["name"]) == target:
                current = child
                found = True
                break
            if _normalize(info["automation_id"]) == target:
                current = child
                found = True
                break

        if not found:
            return None

    return current
