"""BreadcrumbHeader widget for panel navigation display.

A simple Textual widget that renders the BreadcrumbState as a single-line
header bar. It displays the panel type prefix, ring position, title, and
any sub-level navigation trail.

Usage:
    header = BreadcrumbHeader(id="breadcrumb-header")
    header.update_state(BreadcrumbState(
        type_prefix="R", position=1, total=3,
        title="Config Table", sub_levels=("Field Detail: region",)
    ))

This module is in the ``_cli/`` layer — it imports Textual at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

try:
    from textual.widgets import Static
except ImportError as _exc:
    raise ImportError(
        "BreadcrumbHeader requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

if TYPE_CHECKING:
    from functualize._cli.tui.models.ring_models import BreadcrumbState


class BreadcrumbHeader(Static):
    """Displays the breadcrumb navigation header for the active panel.

    Renders a BreadcrumbState as a single line showing:
    [TYPE:N/M] Title [> SubLevel1 [> SubLevel2]]

    Has an update_state() method to refresh the displayed breadcrumb
    when the panel ring navigates or breadcrumb depth changes.
    """

    DEFAULT_CSS = """
    BreadcrumbHeader {
        height: 1;
        background: $surface;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }
    """

    def update_state(self, state: BreadcrumbState) -> None:
        """Update the displayed breadcrumb from a BreadcrumbState.

        Calls state.render() to produce the formatted string and updates
        the widget content.

        Args:
            state: The BreadcrumbState to render. Its render() method
                produces the "[TYPE:N/M] Title > Sub" format.
        """
        self.update(state.render())

    def clear_state(self) -> None:
        """Clear the breadcrumb display (empty content)."""
        self.update("")
