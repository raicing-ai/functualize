"""Pre-flight config summary widget for the TUI help panel.

Displays all resolved config values when the smart bar is green (command is
ready to execute). Shows field names, effective values, source labels, and
override indicators. Sensitive fields are masked with asterisks.

This module is in the ``_cli/`` layer — it imports ONLY from public API.
Textual imports are guarded behind try/except ImportError.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize._cli.data.pending_execution import PendingExecution

try:
    from textual.app import ComposeResult  # noqa: TC002
    from textual.containers import Vertical  # noqa: TC002
    from textual.message import Message  # noqa: TC002
    from textual.widget import Widget  # noqa: TC002
    from textual.widgets import Static  # noqa: TC002
except ImportError as _exc:
    raise ImportError(
        "PreFlightWidget requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

_SENSITIVE_PATTERN = re.compile(r"(secret|password|token|key)", re.IGNORECASE)

_MASK = "********"


def _is_sensitive(field_name: str) -> bool:
    """Return True if the field name contains a sensitive keyword."""
    return _SENSITIVE_PATTERN.search(field_name) is not None


class PreFlightWidget(Widget):
    """Pre-flight config summary shown when command is ready.

    Displays all effective values with their source and override status.
    Posts messages for Ctrl+O, Ctrl+K, Ctrl+D delegated to the app.
    """

    can_focus = True

    DEFAULT_CSS = """
    PreFlightWidget {
        height: auto;
        min-height: 4;
        max-height: 16;
        padding: 0 1;
        border-top: dashed $surface-lighten-2;
    }
    PreFlightWidget .pf-title {
        height: 1;
        color: $text;
        text-style: bold;
        padding: 0 0;
    }
    PreFlightWidget .pf-fields {
        height: auto;
        min-height: 1;
        max-height: 12;
        overflow-y: auto;
    }
    PreFlightWidget .pf-hints {
        height: 1;
        color: $text-muted;
        padding: 0 0;
    }
    """

    class OverrideRequested(Message):
        """User pressed Ctrl+O — wants to quick-override."""

    class ConfigTableRequested(Message):
        """User pressed Ctrl+K — wants full config table."""

    class DiffRequested(Message):
        """User pressed Ctrl+D — wants diff view."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)

    def compose(self) -> ComposeResult:
        """Render a static container for field rows and a keybinding hints bar."""
        yield Static(
            "[bold]Pre-flight Config Summary[/bold]",
            classes="pf-title",
            markup=True,
        )
        with Vertical(classes="pf-fields"):
            yield Static(
                "[dim]No configuration fields for this job[/dim]",
                id="pf-field-list",
                markup=True,
            )
        yield Static(
            "[dim][Ctrl+J] Config Table  [Ctrl+K] Override  [Ctrl+L] Diff[/dim]",
            classes="pf-hints",
            markup=True,
        )

    def update_from_pending(self, pending: PendingExecution) -> None:
        """Update the widget to display fields from a PendingExecution.

        Renders each field as: field_name = value (source) with override
        indicator if has_override. Masks sensitive fields with asterisks.
        Shows "No configuration fields for this job" if resolved_values is empty.

        Args:
            pending: The PendingExecution state to render.
        """
        field_list = self.query_one("#pf-field-list", Static)

        if not pending.resolved_values:
            field_list.update("[dim]No configuration fields for this job[/dim]")
            return

        lines: list[str] = []
        all_effective = pending.all_effective()

        for field_name in sorted(all_effective.keys()):
            value, source = all_effective[field_name]

            # Mask sensitive values
            display_value = _MASK if _is_sensitive(field_name) else repr(value)

            # Override indicator
            override_marker = (
                " [bold yellow]⚡override[/bold yellow]"
                if pending.has_override(field_name)
                else ""
            )

            lines.append(
                f"  [bold]{field_name}[/bold] = {display_value} "
                f"[dim]({source})[/dim]{override_marker}"
            )

        field_list.update("\n".join(lines))

    def on_key(self, event: object) -> None:
        """Handle keybindings: Ctrl+J, Ctrl+K, Ctrl+L."""
        key: str = getattr(event, "key", "")

        if key == "ctrl+j":
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            if hasattr(event, "stop"):
                event.stop()
            self.post_message(self.ConfigTableRequested())
        elif key == "ctrl+k":
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            if hasattr(event, "stop"):
                event.stop()
            self.post_message(self.OverrideRequested())
        elif key == "ctrl+l":
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            if hasattr(event, "stop"):
                event.stop()
            self.post_message(self.DiffRequested())
