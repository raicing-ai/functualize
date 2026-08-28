"""ConfigTablePanel — row-navigable config table with linked edits.

Provides a DataTable-based panel for inspecting and editing configuration
fields with row-level cursor control. Row navigation wraps. The 'i' action
always initiates INSERT mode for the value of the current row's field.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

from functualize.app.utils import display_value

if TYPE_CHECKING:
    from textual.app import ComposeResult

__all__ = [
    "EditOrigin",
    "ParamKind",
    "ChainEntry",
    "FieldDef",
    "ConfigTablePanel",
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class EditOrigin(Enum):
    """Tracks how a field was last modified."""

    NONE = "none"
    VALUE = "value"
    SOURCE = "source"


class ParamKind(Enum):
    """Classification of a field's resolution behavior.

    PLAIN: Direct pass-through from CLI/default only (no layered resolution).
    CONFIG: Full layered resolution chain (CLI → Env → File → Remote → Default).
    """

    PLAIN = "plain"
    CONFIG = "config"


@dataclass
class ChainEntry:
    """A single source→value pair in a field's resolution chain.

    ``path`` carries the concrete file behind a ``File`` entry, so the
    drill-down can say *which* file rather than the generic bucket. Defaulted
    for the sources that have no file identity (CLI/Env/Remote/Default).
    """

    source: str
    value: str
    path: str = ""


@dataclass
class FieldDef:
    """Definition of a single configuration field with its metadata and state."""

    name: str
    value: str
    source: str
    required: bool = False
    choices: list[str] | None = None
    validator: str | None = None
    is_path: bool = False
    description: str = ""
    positional: bool = False
    short_flag: str | None = None
    type_annotation: str = "str"
    chain: list[ChainEntry] = field(default_factory=list)
    edit_origin: EditOrigin = EditOrigin.NONE
    original_value: str = ""
    original_source: str = ""
    param_kind: ParamKind = ParamKind.CONFIG
    secret: bool = False
    """Model-declared secret. Drives masking here and in the drill-down.

    Copied from the cached ``FieldDescriptor`` rather than re-derived from the
    name — the name-based test that used to do this job masked ``sort_key`` and
    missed ``credential``.
    """

    def sources_with_values(self) -> list[ChainEntry]:
        """Return chain entries that have non-empty values."""
        return [e for e in self.chain if e.value]

    def value_for_source(self, source: str) -> str | None:
        """Look up the value for a specific source in the chain."""
        for e in self.chain:
            if e.source == source and e.value:
                return e.value
        return None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class ValueEdited(Message):
    """Posted when a field value is edited via INSERT mode."""

    def __init__(self, field_def: FieldDef, old_value: str) -> None:
        self.field_def = field_def
        self.old_value = old_value
        super().__init__()


class SourceChanged(Message):
    """Posted when a field source is changed via OptionList chooser."""

    def __init__(self, field_def: FieldDef, old_source: str) -> None:
        self.field_def = field_def
        self.old_source = old_source
        super().__init__()


class OverrideReset(Message):
    """Posted when a field override is reset to original values."""

    def __init__(self, field_def: FieldDef) -> None:
        self.field_def = field_def
        super().__init__()


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------


class ConfigTablePanel(Widget):
    """Row-navigable config table with linked edits.

    Wraps a DataTable with cursor_type="row" and provides vim-style
    row navigation (j/k wrap rows). The 'i' action always initiates
    INSERT mode for the value of the current row's field.
    """

    DEFAULT_CSS = """
    ConfigTablePanel {
        height: auto;
        min-height: 3;
        max-height: 10;
    }
    ConfigTablePanel DataTable {
        height: auto;
        min-height: 2;
        max-height: 10;
    }
    """

    # Re-export messages as nested classes for Textual convention
    class ValueEdited(ValueEdited):
        """Posted when a field value is edited via INSERT mode."""

    class SourceChanged(SourceChanged):
        """Posted when a field source is changed via OptionList chooser."""

    class OverrideReset(OverrideReset):
        """Posted when a field override is reset to original values."""

    class InsertRequested(Message):
        """Posted when INSERT mode should be initiated for a field value."""

        def __init__(self, field_def: FieldDef) -> None:
            self.field_def = field_def
            super().__init__()

    class DrillDownRequested(Message):
        """Posted when the user presses Enter to drill down into a field's resolution chain."""

        def __init__(self, field_def: FieldDef) -> None:
            self.field_def = field_def
            super().__init__()

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._fields: list[FieldDef] = []
        self._filtered_fields: list[FieldDef] = []
        self._active_filter_text: str = ""
        self._cursor_row: int = 0
        self._row_count: int = 0
        self._table: DataTable[str] | None = None
        self._populated: bool = False
        self._drill_down_field: FieldDef | None = None

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Mount the inner DataTable."""
        table: DataTable[str] = DataTable(cursor_type="row")
        table.add_columns("Setting", "Type", "Value", "Source", "Description")
        self._table = table
        self._populated = False  # Reset since table is fresh
        yield table

    def on_mount(self) -> None:
        """Populate the table after mount if set_fields was called pre-mount."""
        self._populate_table()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_fields(self, fields: list[FieldDef]) -> None:
        """Populate the table with field definitions.

        Clears existing rows and rebuilds from the provided field list.
        Resets cursor to row 0.
        """
        self._fields = list(fields)
        self._filtered_fields = list(fields)
        self._active_filter_text = ""
        self._row_count = len(fields)
        # Reset cursor to row 0
        self._cursor_row = 0
        self._populated = False
        self._populate_table()

    def _populate_table(self) -> None:
        """Actually add rows to the DataTable if it's ready and not yet populated."""
        fields = getattr(self, "_filtered_fields", None) or self._fields
        if self._populated or not fields or self._table is None:
            return
        self._table.clear()
        for f in fields:
            name_display, type_display, value_display, source_display, desc_display = (
                self._format_field_cells(f)
            )
            self._table.add_row(
                name_display, type_display, value_display, source_display, desc_display
            )
        self._populated = True
        self._sync_table_cursor()

    def get_cursor_field(self) -> FieldDef | None:
        """Return the FieldDef at the current cursor row, or None if empty."""
        fields = getattr(self, "_filtered_fields", None) or self._fields
        if not fields or self._cursor_row >= len(fields):
            return None
        return fields[self._cursor_row]

    @property
    def fields(self) -> list[FieldDef]:
        """Public accessor for the panel's current (unfiltered) field list."""
        return self._fields

    def reload_table(self) -> None:
        """Public wrapper to clear and repopulate the DataTable."""
        self._reload_table()

    # ------------------------------------------------------------------
    # Filterable protocol
    # ------------------------------------------------------------------

    @property
    def active_filter(self) -> str:
        """The currently applied filter text. Empty string means no filter."""
        return self._active_filter_text

    def apply_filter(self, query: str) -> None:
        """Filter visible rows by field name (case-insensitive substring match).

        An empty query resets the table to show all fields.
        """
        self._active_filter_text = query
        if not query:
            self._filtered_fields = list(self._fields)
        else:
            # Match either spelling: rows are shown with the hyphenated CLI-flag
            # name (``dry-run``) but the field name is underscored (``dry_run``),
            # so normalize both sides to treat ``-`` and ``_`` as equivalent.
            q = query.lower().replace("-", "_")
            self._filtered_fields = [
                f for f in self._fields if q in f.name.lower().replace("-", "_")
            ]
        self._row_count = len(self._filtered_fields)
        self._cursor_row = 0
        self._reload_table()

    # ------------------------------------------------------------------
    # Row navigation — rows wrap
    # ------------------------------------------------------------------

    def action_cursor_down(self) -> None:
        """Move cursor down one row, wrapping from last to first."""
        if self._row_count == 0:
            return
        self._cursor_row = (self._cursor_row + 1) % self._row_count
        self._sync_table_cursor()

    def action_cursor_up(self) -> None:
        """Move cursor up one row, wrapping from first to last."""
        if self._row_count == 0:
            return
        self._cursor_row = (self._cursor_row - 1) % self._row_count
        self._sync_table_cursor()

    # ------------------------------------------------------------------
    # 'i' action — always edits value for current row
    # ------------------------------------------------------------------

    def action_enter_insert(self) -> None:
        """Initiate INSERT mode for the current row's field value.

        Always posts InsertRequested(field) for the current row's field.
        """
        field_def = self.get_cursor_field()
        if field_def is None:
            return
        self.post_message(self.InsertRequested(field_def))

    def action_drill_down(self) -> None:
        """Drill down into the resolution chain for the current field (Enter key).

        Sets _drill_down_field and posts DrillDownRequested so the app can
        push a breadcrumb and render the chain detail view.

        No-op if already in drill-down state (prevents double-render and
        layout offset issues).

        R5-AC2: Push breadcrumb with "Detail: <field_name>" and render chain sub-view.
        """
        if self._drill_down_field is not None:
            return
        field_def = self.get_cursor_field()
        if field_def is None:
            return
        self._drill_down_field = field_def
        self.post_message(self.DrillDownRequested(field_def))

    def clear_drill_down(self) -> None:
        """Clear the drill-down state and restore the table view.

        Called when Esc pops the breadcrumb from the drill-down sub-view.
        R5-AC7: Pop breadcrumb and restore Config Table view.
        """
        self._drill_down_field = None

    # ------------------------------------------------------------------
    # Linked edits
    # ------------------------------------------------------------------

    def apply_value_edit(self, field: FieldDef, new_value: str) -> None:
        """Apply value edit with linked source change.

        Sets field.value to new_value, field.source to "cli", and
        field.edit_origin to VALUE. Posts ValueEdited message.

        Under the SmartBar-as-CLI model, an edited
        value is synced into the SmartBar as literal text and reads as
        "cli" everywhere — there is no live "session" source category.
        """
        old_value = field.value
        field.value = new_value
        field.source = "cli"
        field.edit_origin = EditOrigin.VALUE
        self.post_message(self.ValueEdited(field, old_value))
        self._reload_table()

    def apply_source_edit(self, field: FieldDef, new_source: str) -> None:
        """Apply source edit with linked value change.

        Sets field.source to new_source, field.value to the chain value
        for that source, and field.edit_origin to SOURCE. Posts SourceChanged.

        Req 5.2: Source edit → field.source=new_source, field.value=chain_value,
        field.edit_origin=SOURCE.
        Req 5.8: Guard — don't apply if chain has no value for this source.
        """
        chain_value = field.value_for_source(new_source)
        if chain_value is None:
            return  # Guard: don't apply if chain has no value for this source
        old_source = field.source
        field.source = new_source
        field.value = chain_value
        field.edit_origin = EditOrigin.SOURCE
        self.post_message(self.SourceChanged(field, old_source))
        self._reload_table()

    def action_reset_override(self) -> None:
        """Reset the current field to its original values.

        Restores field.value and field.source to originals, sets
        edit_origin to NONE, and posts OverrideReset message.

        Req 5.6: Reset → restore originals, edit_origin=NONE, remove markers.
        Req 5.7: No-op if edit_origin is already NONE.
        """
        field = self.get_cursor_field()
        if field is None or field.edit_origin == EditOrigin.NONE:
            return  # No-op
        field.value = field.original_value
        field.source = field.original_source
        field.edit_origin = EditOrigin.NONE
        # Clear the CLI chain entry so drill-down view doesn't show stale value
        for entry in field.chain:
            if entry.source == "CLI":
                entry.value = ""
                break
        self.post_message(self.OverrideReset(field))
        self._reload_table()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reload_table(self) -> None:
        """Clear and repopulate the DataTable with current field values.

        Renders visual markers based on edit_origin and fill indicators.
        """
        if self._table is None:
            return
        self._table.clear()
        fields = getattr(self, "_filtered_fields", None) or self._fields
        for f in fields:
            name_display, type_display, value_display, source_display, desc_display = (
                self._format_field_cells(f)
            )
            self._table.add_row(
                name_display, type_display, value_display, source_display, desc_display
            )
        self._populated = True
        self._sync_table_cursor()

    @staticmethod
    def _format_field_cells(field: FieldDef) -> tuple[str, str, str, str, str]:
        """Format name, type, value, source, and description cells with indicators.

        Returns (name_display, type_display, value_display, source_display, desc_display).
        Name column shows ● (filled) or ○ (missing required) indicator.
        Required fields get a * suffix.
        Type column shows the type annotation with [arg] or [flag] kind.
        """
        # Indicator: ● filled, ○ missing+required, · optional+empty
        if field.value:
            indicator = "●"
        elif field.required:
            indicator = "○"
        else:
            indicator = "·"

        req_mark = "*" if field.required else ""
        short = (
            f"/{getattr(field, 'short_flag', '') or ''}"
            if getattr(field, "short_flag", None)
            else ""
        )
        # Mirror the CLI flag spelling: an option's underscored name is
        # hyphenated (``dry_run`` → ``dry-run``), matching what the user types;
        # a positional argument carries no flag, so its bare name is unchanged.
        display_name = (
            field.name
            if getattr(field, "positional", False)
            else field.name.replace("_", "-")
        )
        name_display = f"{indicator} {display_name}{req_mark}{short}"

        # Type column: type annotation + kind indicator
        type_str = getattr(field, "type_annotation", "str") or "str"
        if getattr(field, "positional", False):
            type_display = f"{type_str} \\[arg]"
        else:
            type_display = type_str

        # Masked on presence, not on value: an empty secret still reads as a
        # secret, so a viewer cannot infer "unset" from a blank cell.
        value_display = display_value(field.value, secret=field.secret)
        source_display = field.source
        desc_display = field.description
        return name_display, type_display, value_display, source_display, desc_display

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Return context-sensitive action hints for the panel footer."""
        if not focused:
            return [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]
        if self._drill_down_field is not None:
            return [("Esc", "back")]
        return [
            ("Ctrl+Enter", "run"),
            ("j/k", "navigate"),
            ("i", "edit"),
            ("r", "reset"),
            ("/", "filter"),
            ("Enter", "detail"),
            ("Esc", "back"),
        ]

    def _sync_table_cursor(self) -> None:
        """Synchronize the DataTable's visual cursor with internal state."""
        if self._table is None or self._row_count == 0:
            return
        # DataTable may not be ready during early compose
        with contextlib.suppress(Exception):
            self._table.move_cursor(row=self._cursor_row)
