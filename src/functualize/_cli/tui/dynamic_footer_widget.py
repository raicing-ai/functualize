"""DynamicFooter widget for context-sensitive panel action hints.

A simple Textual widget that renders action tuples from a panel's
get_available_actions(focused) method as a formatted footer line.
Uses render_footer() from dynamic_footer.py for consistent formatting.

Usage:
    footer = DynamicFooterWidget(id="dynamic-footer")
    footer.update_actions([("↑↓", "navigate"), ("Enter", "detail"), ("Esc", "back")])

An empty list renders as an empty line (widget still occupies one line height).

This module is in the ``_cli/`` layer — it imports Textual at runtime.
"""

from __future__ import annotations

try:
    from textual.widgets import Static
except ImportError as _exc:
    raise ImportError(
        "DynamicFooterWidget requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

from functualize._cli.tui.dynamic_footer import render_footer


class DynamicFooterWidget(Static):
    """Displays context-sensitive action hints for the active panel.

    Renders (key, label) tuples as "key label" pairs separated by double
    spaces. An empty action list renders as an empty line.

    Has an update_actions() method to refresh the displayed footer when
    focus changes or the panel state changes.
    """

    DEFAULT_CSS = """
    DynamicFooterWidget {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def update_actions(self, actions: list[tuple[str, str]]) -> None:
        """Update the footer from a list of action tuples.

        Calls render_footer(actions) to produce the formatted string.
        An empty list results in an empty string (empty line displayed).

        Args:
            actions: List of (key, label) tuples, typically from a panel's
                get_available_actions(focused) method.
        """
        self.update(render_footer(actions))

    def clear_actions(self) -> None:
        """Clear the footer display (empty content)."""
        self.update("")
