"""NewFilePickerView — choose where a new config/settings file should live.

Pushed over a Files panel when the user presses ``n``. A developer who
doesn't know the file conventions cannot type the right filename into a
prompt — so instead of asking, the picker *lists* the conventional
locations (existing ones included, marked), and Enter continues into the
shared Detail view scoped to the chosen path, where staging + Ctrl+S
brings the file into being. No file is created until that save.

This module is in the ``_cli/`` layer — Textual + stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import ComposeResult

__all__ = ["NewFileCandidate", "NewFilePickerView"]


@dataclass(frozen=True)
class NewFileCandidate:
    """One conventional location a new file could be created at.

    Attributes:
        path: The absolute path the file would have.
        label: Display name (usually cwd-/home-relative).
        note: What this location means ("project settings", "prod overlay").
        exists: True when the file is already there — still selectable, the
            Detail view then edits it rather than creating it.
    """

    path: Path
    label: str
    note: str
    exists: bool


class NewFilePickerView(Widget):
    """Row-navigable list of conventional file locations.

    Same interaction contract as every other pushed view: j/k navigate,
    Enter selects (posts :class:`Selected`), Esc pops the view via the
    app's normal exit flow.
    """

    can_focus = True

    DEFAULT_CSS = """
    NewFilePickerView {
        height: auto;
        min-height: 3;
        max-height: 12;
    }
    NewFilePickerView DataTable {
        height: auto;
        min-height: 2;
        max-height: 12;
    }
    """

    class Selected(Message):
        """Enter was pressed on a candidate row."""

        def __init__(self, candidate: NewFileCandidate) -> None:
            self.candidate = candidate
            super().__init__()

    def __init__(
        self,
        candidates: list[NewFileCandidate],
        *,
        id: str | None = None,  # noqa: A002 — Textual's own signature
    ) -> None:
        super().__init__(id=id)
        self._candidates = list(candidates)
        self._cursor_row = 0
        self._table: DataTable[str] | None = None

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        table: DataTable[str] = DataTable(cursor_type="row")
        table.add_columns("Location", "Status", "For")
        self._table = table
        yield table

    def on_mount(self) -> None:
        if self._table is None:
            return
        for candidate in self._candidates:
            status = "● exists" if candidate.exists else "○ available"
            self._table.add_row(candidate.label, status, candidate.note)
        self._sync_cursor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def candidates(self) -> list[NewFileCandidate]:
        """The locations on offer."""
        return list(self._candidates)

    @property
    def cursor_candidate(self) -> NewFileCandidate | None:
        """The candidate under the cursor, or None when empty."""
        if not self._candidates:
            return None
        return self._candidates[self._cursor_row]

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Footer hints."""
        if not focused:
            return []
        return [("j/k", "navigate"), ("Enter", "select"), ("Esc", "back")]

    # ------------------------------------------------------------------
    # Actions (routed via KEYMAPS)
    # ------------------------------------------------------------------

    def action_cursor_down(self) -> None:
        """Move down one row, wrapping."""
        if not self._candidates:
            return
        self._cursor_row = (self._cursor_row + 1) % len(self._candidates)
        self._sync_cursor()

    def action_cursor_up(self) -> None:
        """Move up one row, wrapping."""
        if not self._candidates:
            return
        self._cursor_row = (self._cursor_row - 1) % len(self._candidates)
        self._sync_cursor()

    def action_drill_down(self) -> None:
        """Select the highlighted location (Enter)."""
        candidate = self.cursor_candidate
        if candidate is not None:
            self.post_message(self.Selected(candidate))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sync_cursor(self) -> None:
        if self._table is not None and self._candidates:
            self._table.move_cursor(row=self._cursor_row)
