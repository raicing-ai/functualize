"""Dynamic footer renderer for panel action hints.

Renders action tuples from get_available_actions(focused) as a single
formatted string for display in panel footers.
"""

from __future__ import annotations


def render_footer(actions: list[tuple[str, str]]) -> str:
    """Render action tuples as 'key label' pairs separated by double spaces.

    Each tuple (key, label) is formatted as "key label".
    Pairs are joined with "  " (two spaces).
    Empty list returns empty string.

    Args:
        actions: List of (key, label) tuples from get_available_actions().

    Returns:
        Rendered footer string.
    """
    if not actions:
        return ""
    return "  ".join(f"{key} {label}" for key, label in actions)
