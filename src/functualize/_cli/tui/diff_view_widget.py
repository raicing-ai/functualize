"""Diff view widget showing config comparison to previous execution session.

Displays field-by-field comparison between the current PendingExecution and a
previous ConfigSnapshot, color-coded by status. Below the diff entries, a
DataTable with cursor_type="cell" shows session history — one row per past
execution, with columns for timestamp, outcome, and each config field value.

Navigation integrates with the app's KeyDispatcher via standard action_* methods:
- j/k (or ↑/↓): row navigation with wrapping
- h/l (or ←/→): column navigation (horizontal scroll)
- Enter: load selected session's values as overrides
- Esc: post BackRequested to exit panel

This module is in the ``_cli/`` layer — it imports ONLY from public API.
Textual imports are guarded behind try/except ImportError.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

try:
    from textual.css.query import NoMatches
    from textual.message import Message  # noqa: TC002
    from textual.widget import Widget  # noqa: TC002
    from textual.widgets import DataTable, Static  # noqa: TC002
except ImportError as _exc:
    raise ImportError(
        "DiffViewWidget requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

from functualize._cli.data.config_snapshot_store import ConfigSnapshot  # noqa: TC001
from functualize._cli.data.pending_execution import PendingExecution  # noqa: TC001
from functualize._cli.tui.config_diff import (  # noqa: TC001
    ConfigDiffEntry,
    compute_config_diff,
)

# Status → Rich markup color mapping
_STATUS_COLORS: dict[str, str] = {
    "changed": "yellow",
    "unchanged": "dim",
    "new": "green",
    "removed": "red",
}

# Status → prefix symbol
_STATUS_PREFIXES: dict[str, str] = {
    "changed": "~",
    "unchanged": " ",
    "new": "+",
    "removed": "-",
}


class DiffViewWidget(Widget):
    """Config diff and session history with interactive DataTable.

    Top section: color-coded field-by-field comparison (Static, read-only).
    Bottom section: DataTable with cursor_type="cell" for session history,
    supporting row selection (j/k/↑/↓) and horizontal scrolling (h/l/←/→).
    """

    can_focus = True

    DEFAULT_CSS = """
    DiffViewWidget {
        height: auto;
        min-height: 4;
        max-height: 16;
        padding: 0 1;
    }
    DiffViewWidget .dv-title {
        height: 1;
        color: $text;
        text-style: bold;
        padding: 0 0;
    }
    DiffViewWidget .dv-entries {
        height: auto;
        max-height: 5;
        overflow-y: hidden;
        padding: 0 0;
    }
    DiffViewWidget .dv-no-previous {
        height: 1;
        color: $text-muted;
        padding: 0 0;
        text-style: italic;
    }
    DiffViewWidget .dv-history-title {
        height: 1;
        color: $text;
        text-style: bold;
        padding: 1 0 0 0;
    }
    DiffViewWidget DataTable {
        height: auto;
        min-height: 5;
        max-height: 8;
        scrollbar-size: 1 1;
    }
    """

    class LoadSessionRequested(Message):
        """User selected a previous session to load values from."""

        def __init__(self, snapshot: ConfigSnapshot) -> None:
            self.snapshot = snapshot
            super().__init__()

    class BackRequested(Message):
        """User pressed Esc — back to pre-flight."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._history: list[ConfigSnapshot] = []
        self._pending: PendingExecution | None = None
        self._previous: ConfigSnapshot | None = None
        self._table: DataTable[str] | None = None
        self._populated: bool = False
        self._row_count: int = 0
        self._col_count: int = 0

    def compose(self) -> ComposeResult:
        """Render diff entries area and session history DataTable."""
        yield Static(
            "[bold]Config Diff from Previous Session[/bold]",
            classes="dv-title",
            markup=True,
        )
        yield Static("", id="dv-entries", classes="dv-entries", markup=True)
        yield Static("", id="dv-no-previous", classes="dv-no-previous", markup=True)
        yield Static(
            "[bold]Session History[/bold]",
            id="dv-history-title",
            classes="dv-history-title",
            markup=True,
        )
        table: DataTable[str] = DataTable(id="dv-history-table", cursor_type="cell")
        table.show_cursor = True
        self._table = table
        self._populated = False
        yield table

    def on_mount(self) -> None:
        """Populate the table after mount if show_diff was called pre-mount."""
        self._populate_table()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_diff(
        self,
        pending: PendingExecution,
        previous: ConfigSnapshot | None,
        history: list[ConfigSnapshot],
    ) -> None:
        """Compute and display the config diff + populate session history table.

        Args:
            pending: The current PendingExecution with resolved values and overrides.
            previous: The most recent previous snapshot, or None if no prior execution.
            history: List of past snapshots for this job (up to 10).
        """
        self._pending = pending
        self._previous = previous
        self._history = history[:10]
        self._populated = False

        # Render diff entries (top section)
        entries = compute_config_diff(pending, previous)
        self._render_entries(entries, previous)

        # Populate DataTable (bottom section)
        self._populate_table()

    def refresh_diff_only(
        self,
        pending: PendingExecution,
        previous: ConfigSnapshot | None,
    ) -> None:
        """Re-render only the diff entries section without touching the DataTable.

        Used after loading a session to update the top section while preserving
        the DataTable's cursor position and scroll state.

        Args:
            pending: The current PendingExecution with resolved values and overrides.
            previous: The most recent previous snapshot, or None if no prior execution.
        """
        self._pending = pending
        self._previous = previous

        # Only re-render the diff entries (top section)
        entries = compute_config_diff(pending, previous)
        self._render_entries(entries, previous)

    # ------------------------------------------------------------------
    # Action methods — called by KeyDispatcher via action_<name>
    # ------------------------------------------------------------------

    def action_cursor_down(self) -> None:
        """Move cursor down one row, wrapping from last to first."""
        if self._table is None or self._row_count == 0:
            return
        current = self._table.cursor_row
        if current >= self._row_count - 1:
            # Wrap to first row
            self._table.move_cursor(row=0)
        else:
            self._table.action_cursor_down()
        self._table._scroll_cursor_into_view(animate=False)

    def action_cursor_up(self) -> None:
        """Move cursor up one row, wrapping from first to last."""
        if self._table is None or self._row_count == 0:
            return
        current = self._table.cursor_row
        if current <= 0:
            # Wrap to last row
            self._table.move_cursor(row=self._row_count - 1)
        else:
            self._table.action_cursor_up()
        self._table._scroll_cursor_into_view(animate=False)

    def action_cursor_right(self) -> None:
        """Move cursor right one column (horizontal scroll, no wrap)."""
        if self._table is None or self._col_count == 0:
            return
        current = self._table.cursor_column
        if current < self._col_count - 1:
            self._table.action_cursor_right()
            self._table._scroll_cursor_into_view(animate=False)

    def action_cursor_left(self) -> None:
        """Move cursor left one column (horizontal scroll, no wrap)."""
        if self._table is None or self._col_count == 0:
            return
        current = self._table.cursor_column
        if current > 0:
            self._table.action_cursor_left()
            self._table._scroll_cursor_into_view(animate=False)

    def action_drill_down(self) -> None:
        """Load the selected session — post LoadSessionRequested.

        Uses cursor_row to determine which snapshot to load, regardless
        of which column the cell cursor is on.
        """
        if self._table is None or self._row_count == 0:
            return
        row_idx = self._table.cursor_row
        if 0 <= row_idx < len(self._history):
            snapshot = self._history[row_idx]
            self.post_message(self.LoadSessionRequested(snapshot=snapshot))

    def action_exit_panel(self) -> None:
        """Post BackRequested — exit panel and return to COMMAND mode."""
        self.post_message(self.BackRequested())

    # ------------------------------------------------------------------
    # Footer integration
    # ------------------------------------------------------------------

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Return context-sensitive action hints for PanelHost footer.

        Args:
            focused: Whether this widget currently has focus.

        Returns:
            List of (key_label, action_label) tuples.
        """
        if not focused:
            return [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]

        actions: list[tuple[str, str]] = []
        if self._row_count > 0:
            actions.append(("j/k", "navigate"))
            if self._col_count > 2:
                actions.append(("h/l", "scroll"))
            actions.append(("Enter", "load"))
        actions.append(("Esc", "back"))
        return actions

    # ------------------------------------------------------------------
    # Private: diff entries rendering (top section)
    # ------------------------------------------------------------------

    def _render_entries(
        self, entries: list[ConfigDiffEntry], previous: ConfigSnapshot | None
    ) -> None:
        """Render diff entries with color coding into the Static widget."""
        try:
            entries_widget = self.query_one("#dv-entries", Static)
            no_prev_widget = self.query_one("#dv-no-previous", Static)
        except NoMatches:
            return  # Not yet mounted

        if previous is None:
            no_prev_widget.update(
                "[italic]No previous sessions to compare against[/italic]"
            )
        else:
            no_prev_widget.update("")

        if not entries:
            entries_widget.update("[dim]No fields to display.[/dim]")
            return

        lines: list[str] = []
        for entry in entries:
            color = _STATUS_COLORS.get(entry.status, "dim")
            prefix = _STATUS_PREFIXES.get(entry.status, " ")
            line = self._format_entry(entry, color, prefix)
            lines.append(line)

        entries_widget.update("\n".join(lines))

    @staticmethod
    def _entry_label(entry: ConfigDiffEntry) -> str:
        """The field's display name, with its group when it has one.

        Same `[group] name` convention the config table and pre-flight use —
        one reader learns it once. The stored ``field_name`` is already
        group-prefixed to keep the keys distinct, so the group half is stripped
        before re-adding it as a label rather than printing `deploy.env` twice
        over.
        """
        if not entry.group_path:
            return entry.field_name
        name = entry.field_name
        head = f"{entry.group_path}."
        if name.startswith(head):
            name = name[len(head) :]
        return f"\\[{entry.group_path}] {name}"

    def _format_entry(self, entry: ConfigDiffEntry, color: str, prefix: str) -> str:
        """Format a single diff entry as a Rich markup line."""
        if entry.status == "changed":
            return (
                f"[{color}]{prefix} {self._entry_label(entry)}: "
                f"{entry.previous_value!r} → {entry.current_value!r} "
                f"({entry.current_source})[/{color}]"
            )
        elif entry.status == "removed":
            return (
                f"[{color}]{prefix} {self._entry_label(entry)}: "
                f"{entry.previous_value!r} (removed)[/{color}]"
            )
        elif entry.status == "new":
            return (
                f"[{color}]{prefix} {self._entry_label(entry)}: "
                f"{entry.current_value!r} ({entry.current_source})[/{color}]"
            )
        else:
            # unchanged
            return (
                f"[{color}]{prefix} {self._entry_label(entry)}: "
                f"{entry.current_value!r} ({entry.current_source})[/{color}]"
            )

    # ------------------------------------------------------------------
    # Private: DataTable population (bottom section)
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        """Populate the DataTable with session history rows.

        Uses the deferred population pattern: no-op if table isn't mounted
        or already populated. Called from both show_diff() and on_mount().
        """
        if self._populated or self._table is None:
            return
        if not self._history:
            # No history — leave table empty, update title
            try:
                title = self.query_one("#dv-history-title", Static)
                title.update("[bold]Session History[/bold] [dim](no history)[/dim]")
            except NoMatches:
                pass
            self._row_count = 0
            self._col_count = 0
            self._populated = True
            return

        # Determine field columns: union of all field keys across snapshots
        field_keys: list[str] = []
        seen_keys: set[str] = set()
        for snapshot in self._history:
            for key in snapshot.values:
                if key not in seen_keys:
                    field_keys.append(key)
                    seen_keys.add(key)

        # Build columns: When, Result, <field1>, <field2>, ...
        self._table.clear(columns=True)
        self._table.add_column("When", key="when")
        self._table.add_column("Result", key="result")
        for key in field_keys:
            self._table.add_column(key, key=key)

        self._col_count = 2 + len(field_keys)

        # Add rows
        for snapshot in self._history:
            ts = datetime.datetime.fromtimestamp(snapshot.timestamp, tz=datetime.UTC)
            formatted_ts = ts.strftime("%Y-%m-%d %H:%M")
            outcome_icon = "✓" if snapshot.outcome == "success" else "✗"

            cells: list[str] = [formatted_ts, outcome_icon]
            for key in field_keys:
                val = snapshot.values.get(key)
                cells.append(str(val) if val is not None else "—")

            self._table.add_row(*cells)

        self._row_count = len(self._history)
        self._populated = True
