"""SourceChainDetailView — the shared Detail screen for config precedence.

One widget serves both drill-downs, because they are the same screen viewed
along different axes of the same table:

- **File detail** (Enter on a Config Files row) — rows are *keys*. "This file
  is one source; what does it say about each key, and does it win?"
- **Key detail** (Enter on a Settings row) — rows are *sources*. "This key has
  many sources; what does each say, and which one wins?"

Both show every source's contribution (including the losing ones), let the
user stage edits and removals against writable sources, and save atomically
on Ctrl+S. Esc discards — staging is what makes discard cheap enough to need
no confirmation prompt.

The widget talks to its domain only through ``SourceChainProvider``, which is
what lets job config and TUI settings share it.

Keys reach this widget through the normal ``KEYMAPS`` → ``KeyDispatcher``
→ ``active_panel`` path once ``PanelHost.push_view()`` puts it on top; it
introduces no key routing of its own.

This module is in the ``_cli/`` layer — it imports Textual at runtime.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

try:
    from textual.message import Message
    from textual.widget import Widget
    from textual.widgets import DataTable
except ImportError as _exc:
    raise ImportError(
        "SourceChainDetailView requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

from functualize._cli.tui.panels.config_table import FieldDef

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from functualize._cli.tui.models.source_chain import (
        ResolvedKey,
        SourceChainProvider,
    )

__all__ = ["FILE_FLAVOR", "KEY_FLAVOR", "SourceChainDetailView"]

FILE_FLAVOR = "file"
"""Rows are keys; the scope is one source (a file)."""

KEY_FLAVOR = "key"
"""Rows are sources; the scope is one key."""

# Status glyphs — the whole point of the screen is telling these apart.
_STATUS_WINNING = "★ winning"
_STATUS_OVERRIDDEN = "● overridden"
_STATUS_NOT_SET = "— not set"

_MARK_EDIT = "[EDIT]"
_MARK_DEL = "[DEL]"

_COL_LABEL = 0
_COL_VALUE = 1


@dataclass
class _DetailRow:
    """One rendered row, flattened from whichever axis we're viewing."""

    key_name: str
    source_id: str
    label: str
    """Row header: the key name (file flavor) or the source name (key flavor)."""

    value: str
    """What this row's source contributes, or "" if it contributes nothing."""

    is_set: bool
    effective: str
    status: str
    writable: bool
    type_hint: str
    choices: list[str] | None
    description: str


class SourceChainDetailView(Widget):
    """Interactive precedence/detail table over a ``SourceChainProvider``."""

    can_focus = True

    DEFAULT_CSS = """
    SourceChainDetailView {
        height: auto;
        min-height: 3;
        max-height: 16;
    }
    SourceChainDetailView DataTable {
        height: auto;
        min-height: 2;
        max-height: 16;
        overflow-x: hidden;
    }
    """

    class InsertRequested(Message):
        """Stage an edit for a row via the app's SmartBar INSERT flow.

        Carries a ``FieldDef`` because that is what ``InsertModeController``
        already speaks — the old ``ConfigFilesPanel.InsertRequested`` posted
        ``(field_name, current_value)`` instead, which no handler could
        consume even if one had existed.
        """

        def __init__(self, field_def: FieldDef) -> None:
            self.field_def = field_def
            super().__init__()

        @property
        def field(self) -> FieldDef:
            """Alias for readers that think in terms of the edited field."""
            return self.field_def

    class Saved(Message):
        """Staged changes were written. Carries what changed, for refresh."""

        def __init__(self, source_ids: list[str], edits: dict[str, str]) -> None:
            self.source_ids = source_ids
            self.edits = edits
            super().__init__()

    class SaveFailed(Message):
        """A write failed — surfaced rather than swallowed."""

        def __init__(self, error: str) -> None:
            self.error = error
            super().__init__()

    class ReadOnlyRejected(Message):
        """User tried to edit a source they cannot write (env, default)."""

        def __init__(self, label: str) -> None:
            self.label = label
            super().__init__()

    def __init__(
        self,
        provider: SourceChainProvider,
        *,
        flavor: str,
        scope: str,
        id: str | None = None,
    ) -> None:
        """
        Args:
            provider: The domain adapter to render and save through.
            flavor: ``FILE_FLAVOR`` (rows = keys) or ``KEY_FLAVOR`` (rows = sources).
            scope: The ``source_id`` being inspected (file flavor) or the key
                name being inspected (key flavor).
        """
        super().__init__(id=id)
        self._provider = provider
        self._flavor = flavor
        self._scope = scope
        self._keys: list[ResolvedKey] = []
        self._rows: list[_DetailRow] = []
        # Staged, not written: (source_id, key_name) → new value.
        self._staged_edits: dict[tuple[str, str], str] = {}
        self._staged_removals: set[tuple[str, str]] = set()
        self._cursor_row: int = 0
        self._editing_row: int | None = None
        self._table: DataTable[str] | None = None

    # ------------------------------------------------------------------
    # Compose / mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        table: DataTable[str] = DataTable(cursor_type="row")
        if self._flavor == FILE_FLAVOR:
            table.add_columns("Field", "In this file", "Effective", "Status")
        else:
            table.add_columns("Source", "Value", "Status")
        self._table = table
        yield table

    def on_mount(self) -> None:
        self.reload()

    def on_focus(self, event: object) -> None:
        """Delegate focus to the inner DataTable."""
        if self._table is not None:
            with contextlib.suppress(Exception):
                self._table.focus()

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Re-resolve from the provider and rebuild the rows."""
        self._keys = self._provider.resolve()
        self._build_rows()
        self._rebuild_table()

    def _build_rows(self) -> None:
        rows: list[_DetailRow] = []

        if self._flavor == FILE_FLAVOR:
            # Rows are keys; the scope is the one source we're looking at.
            for key in self._keys:
                entry = key.entry_for(self._scope)
                if entry is None:
                    continue
                rows.append(
                    _DetailRow(
                        key_name=key.name,
                        source_id=self._scope,
                        label=key.name,
                        value=str(entry.value) if entry.is_set else "",
                        is_set=entry.is_set,
                        effective=key.effective_value,
                        status=self._status_for(key, entry.source_id, entry.is_set),
                        writable=entry.writable,
                        type_hint=key.type_hint,
                        choices=key.choices,
                        description=key.description,
                    )
                )
        else:
            # Rows are sources; the scope is the one key we're looking at.
            scoped = next((k for k in self._keys if k.name == self._scope), None)
            if scoped is not None:
                # Highest precedence first — the winner reads at the top,
                # which is the question the screen exists to answer.
                for entry in sorted(
                    scoped.chain, key=lambda e: e.precedence, reverse=True
                ):
                    rows.append(
                        _DetailRow(
                            key_name=scoped.name,
                            source_id=entry.source_id,
                            label=entry.label,
                            value=str(entry.value) if entry.is_set else "",
                            is_set=entry.is_set,
                            effective=scoped.effective_value,
                            status=self._status_for(
                                scoped, entry.source_id, entry.is_set
                            ),
                            writable=entry.writable,
                            type_hint=scoped.type_hint,
                            choices=scoped.choices,
                            description=scoped.description,
                        )
                    )

        self._rows = rows
        if self._cursor_row >= len(rows):
            self._cursor_row = max(0, len(rows) - 1)

    @staticmethod
    def _status_for(key: ResolvedKey, source_id: str, is_set: bool) -> str:
        if not is_set:
            return _STATUS_NOT_SET
        if key.winning_source_id == source_id:
            return _STATUS_WINNING
        return _STATUS_OVERRIDDEN

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _display_value(self, row: _DetailRow) -> str:
        """The value cell, including any staged-change marker."""
        stage_key = (row.source_id, row.key_name)
        if stage_key in self._staged_removals:
            return f"{row.value or '—'} {_MARK_DEL}"
        if stage_key in self._staged_edits:
            return f"{self._staged_edits[stage_key]} {_MARK_EDIT}"
        return row.value or "—"

    def _row_cells(self, row: _DetailRow) -> tuple[str, ...]:
        label = row.label if row.writable else f"{row.label} 🔒"
        if self._flavor == FILE_FLAVOR:
            return (label, self._display_value(row), row.effective or "—", row.status)
        return (label, self._display_value(row), row.status)

    def _rebuild_table(self) -> None:
        """Rebuild the table from current state.

        The old file-detail view was a write-once RichLog, so a staged edit
        could never appear. A DataTable rebuilt here is what makes `i`/`d`
        visible at all.

        Not named ``_render``: that is Textual's own ``Widget._render()``,
        and shadowing it with a ``None``-returning method makes the widget
        render as ``visual=None`` and crash the compositor.
        """
        if self._table is None:
            return
        self._table.clear()
        for row in self._rows:
            self._table.add_row(*self._row_cells(row))
        self._sync_cursor()

    def _sync_cursor(self) -> None:
        if self._table is None or not self._rows:
            return
        with contextlib.suppress(Exception):
            self._table.move_cursor(row=self._cursor_row, column=_COL_LABEL)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def flavor(self) -> str:
        """Which axis this view renders."""
        return self._flavor

    @property
    def scope(self) -> str:
        """The source_id (file flavor) or key name (key flavor) in view."""
        return self._scope

    @property
    def rows(self) -> list[_DetailRow]:
        """Current rows — for tests and for the app's chrome."""
        return list(self._rows)

    @property
    def cursor_row(self) -> int:
        """Index of the highlighted row."""
        return self._cursor_row

    @property
    def is_dirty(self) -> bool:
        """Whether anything is staged but not yet written."""
        return bool(self._staged_edits or self._staged_removals)

    @property
    def staged_edits(self) -> dict[tuple[str, str], str]:
        """Staged edits: (source_id, key_name) → new value."""
        return dict(self._staged_edits)

    @property
    def staged_removals(self) -> set[tuple[str, str]]:
        """Staged removals: (source_id, key_name)."""
        return set(self._staged_removals)

    def current_row(self) -> _DetailRow | None:
        """The row under the cursor, or None if the view is empty."""
        if not self._rows or self._cursor_row >= len(self._rows):
            return None
        return self._rows[self._cursor_row]

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Footer hints — truthful, unlike the old detail view's."""
        if not focused:
            return []
        actions = [("j/k", "navigate"), ("i", "edit"), ("d", "remove")]
        if self.is_dirty:
            actions.append(("Ctrl+S", "save"))
            actions.append(("Esc", "discard"))
        else:
            actions.append(("Esc", "back"))
        return actions

    # ------------------------------------------------------------------
    # Actions — reached via KEYMAPS[NORMAL] → KeyDispatcher._resolve_target
    # ------------------------------------------------------------------

    def action_cursor_down(self) -> None:
        """Move down one row, wrapping."""
        if not self._rows:
            return
        self._cursor_row = (self._cursor_row + 1) % len(self._rows)
        self._sync_cursor()

    def action_cursor_up(self) -> None:
        """Move up one row, wrapping."""
        if not self._rows:
            return
        self._cursor_row = (self._cursor_row - 1) % len(self._rows)
        self._sync_cursor()

    def action_enter_insert(self) -> None:
        """Stage an edit for the current row via the SmartBar INSERT flow."""
        row = self.current_row()
        if row is None:
            return
        if not row.writable:
            self.post_message(self.ReadOnlyRejected(row.label))
            return

        self._editing_row = self._cursor_row
        stage_key = (row.source_id, row.key_name)
        current = self._staged_edits.get(stage_key, row.value)

        self.post_message(
            self.InsertRequested(
                FieldDef(
                    name=row.key_name,
                    value=current,
                    source=row.label,
                    choices=row.choices,
                    description=row.description,
                    type_annotation=row.type_hint,
                    original_value=row.value,
                    original_source=row.label,
                )
            )
        )

    def apply_value_edit(self, field: FieldDef, new_value: str) -> None:
        """Called by the app when an INSERT edit is confirmed.

        Stages the value — nothing touches disk until Ctrl+S.
        """
        index = self._editing_row if self._editing_row is not None else self._cursor_row
        self._editing_row = None
        if index >= len(self._rows):
            return
        row = self._rows[index]
        if not row.writable:
            return

        stage_key = (row.source_id, row.key_name)
        self._staged_edits[stage_key] = new_value
        # An edit supersedes a staged removal of the same key.
        self._staged_removals.discard(stage_key)
        self._rebuild_table()

    def action_toggle_removal(self) -> None:
        """Toggle a staged removal on the current row (the `d` key).

        Only meaningful for a source that actually sets the key — you cannot
        remove what isn't there.
        """
        row = self.current_row()
        if row is None or not row.writable:
            if row is not None:
                self.post_message(self.ReadOnlyRejected(row.label))
            return

        stage_key = (row.source_id, row.key_name)
        if stage_key in self._staged_removals:
            self._staged_removals.discard(stage_key)
        else:
            if not row.is_set and stage_key not in self._staged_edits:
                return
            self._staged_removals.add(stage_key)
            self._staged_edits.pop(stage_key, None)
        self._rebuild_table()

    def action_save(self) -> None:
        """Write every staged change atomically (Ctrl+S).

        Changes are grouped by destination, so one Ctrl+S in a key-detail
        view that staged edits against two different files still results in
        one atomic write per file.
        """
        if not self.is_dirty:
            return

        by_source: dict[str, tuple[dict[str, str], set[str]]] = {}
        for (source_id, key_name), value in self._staged_edits.items():
            edits, removals = by_source.setdefault(source_id, ({}, set()))
            edits[key_name] = value
        for source_id, key_name in self._staged_removals:
            edits, removals = by_source.setdefault(source_id, ({}, set()))
            removals.add(key_name)

        applied: dict[str, str] = {}
        written: list[str] = []
        try:
            for source_id, (edits, removals) in by_source.items():
                self._provider.write(source_id, edits, removals)
                written.append(source_id)
                applied.update(edits)
        except (OSError, ValueError) as exc:
            self.post_message(self.SaveFailed(f"{type(exc).__name__}: {exc}"))
            return

        self._staged_edits.clear()
        self._staged_removals.clear()
        self._provider.apply_live(applied)
        self.reload()
        self.post_message(self.Saved(written, applied))

    def discard(self) -> None:
        """Drop all staged changes (what Esc does before popping the view)."""
        self._staged_edits.clear()
        self._staged_removals.clear()
        self._editing_row = None
        self._rebuild_table()
