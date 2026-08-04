"""Settings panel for the TUI General Ring.

Displays a navigable table of **every** functualize setting — ``[tui]``,
``[cli]``, ``[discovery]``, and the top-level keys — with cell-level cursor
control and INSERT mode editing via the SmartBar autocomplete pattern,
matching the ConfigTablePanel's idiomatic approach.

Values come from ``FuncSettingsStore`` (defaults < global config.toml <
project file(s) < FUNCTUALIZE_* env — the same layers ``resolve_cli_config``
merges), so the Source column reports where a value actually came from.
Enter on a row drills into the shared ``SourceChainDetailView`` to see and
edit that setting's whole chain.

This is a General Ring panel with panel_priority = 90.

This module is in the ``_cli/`` layer — it imports ONLY from public API.
Textual imports are guarded behind try/except ImportError.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

try:
    from textual.app import ComposeResult  # noqa: TC002
    from textual.message import Message  # noqa: TC002
    from textual.widget import Widget  # noqa: TC002
    from textual.widgets import DataTable
except ImportError as _exc:
    raise ImportError(
        "SettingsPanel requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

from functualize._cli.data.func_settings import (
    DEFAULT_VALUES,
    FUNC_SETTINGS,
    SETTINGS_ORDER,
    validate_func_setting,
)
from functualize._cli.data.settings_schema import validate_against
from functualize._cli.tui.panels.config_table import FieldDef

if TYPE_CHECKING:
    from pathlib import Path

    from functualize._cli.data.config_target import ConfigTarget

# The settings and their defaults live in the catalog, which is the thing
# that actually resolves them — duplicating the lists here is how the panel
# and the rest of the app drift apart. Names are dotted (``tui.theme``).
_SETTINGS_ORDER: Sequence[str] = SETTINGS_ORDER
_DEFAULT_VALUES: Mapping[str, str] = DEFAULT_VALUES

# Column indices. The table really does have four columns; comments and
# docstrings here used to claim three and stop at Source.
_COL_NAME = 0
_COL_VALUE = 1
_COL_SOURCE = 2
_COL_DESC = 3
_NUM_COLUMNS = 4


class SettingsPanel(Widget):
    """Navigable settings table with SmartBar-based INSERT mode editing.

    Displays all 9 TUI settings with columns: Setting, Value, Source.
    Uses a DataTable with cell-level cursor and posts InsertRequested
    messages so the app can wire editing through the SmartBar +
    FunctualizeAutoComplete autocomplete flow — identical to ConfigTablePanel.

    This is a General Ring panel with panel_priority = 90.
    """

    can_focus = True

    DEFAULT_CSS = """
    SettingsPanel {
        height: auto;
        min-height: 3;
        max-height: 10;
    }
    SettingsPanel DataTable {
        height: auto;
        min-height: 2;
        max-height: 10;
        overflow-x: hidden;
    }
    """

    class SettingChanged(Message):
        """A setting value was changed in the table (not yet persisted)."""

        def __init__(self, setting_name: str, value: str, target: ConfigTarget) -> None:
            self.setting_name = setting_name
            self.value = value
            self.target = target
            super().__init__()

    class InsertRequested(Message):
        """Posted when INSERT mode should be initiated for a field value."""

        def __init__(self, field_def: FieldDef) -> None:
            self.field_def = field_def
            super().__init__()

    class DrillDownRequested(Message):
        """Enter was pressed on a row — show that setting's full source chain."""

        def __init__(self, setting_name: str) -> None:
            self.setting_name = setting_name
            super().__init__()

    def __init__(
        self,
        *,
        cwd: Path | None = None,
        id: str | None = None,
        catalog: tuple[Any, ...] | None = None,
    ) -> None:
        """
        Args:
            cwd: Project root the settings resolve against.
            id: Widget id.
            catalog: The settings this panel shows. Defaults to func's. Held as
                **instance state**, not read from a module global, so two apps
                (or two panels) can show different catalogs in one process —
                which is what makes the panel reusable by a second app (C2).
        """
        super().__init__(id=id)
        entries = FUNC_SETTINGS if catalog is None else catalog
        self._catalog: tuple[Any, ...] = tuple(entries)
        self._settings: list[str] = [s.name for s in self._catalog]
        # Some settings genuinely have no default (most [discovery] filters);
        # they display as empty until a file or env var sets them.
        self._values: dict[str, str] = {
            s.name: (s.default or "") for s in self._catalog
        }
        self._sources: dict[str, str] = {s.name: "default" for s in self._catalog}
        self._cwd = cwd
        self._fields: list[FieldDef] = []
        self._cursor_row: int = 0
        self._cursor_col: int = _COL_VALUE  # Start on value column
        self._row_count: int = 0
        self._table: DataTable[str] | None = None
        self._populated: bool = False

    # ------------------------------------------------------------------
    # Compose / Mount
    # ------------------------------------------------------------------

    # ── catalog lookups (instance-scoped, not module-global) ─────────────

    def _setting(self, name: str) -> Any | None:
        """The catalog entry for ``name``, from **this panel's** catalog."""
        for entry in self._catalog:
            if entry.name == name:
                return entry
        return None

    def _validate(self, name: str, value: str) -> Any:
        """Validate against this panel's catalog rather than func's globals."""
        entry = self._setting(name)
        if entry is None:
            return validate_func_setting(name, value)
        return validate_against(entry.schema, value)

    def compose(self) -> ComposeResult:
        """Render a DataTable for settings."""
        table: DataTable[str] = DataTable(cursor_type="cell")
        table.add_columns("Setting", "Value", "Source", "Description")
        self._table = table
        self._populated = False
        yield table

    def on_mount(self) -> None:
        """Populate the table after mount."""
        self._build_fields()
        self._populate_table()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cursor_field(self) -> FieldDef | None:
        """Return the FieldDef at the current cursor row, or None if empty."""
        if not self._fields or self._cursor_row >= len(self._fields):
            return None
        return self._fields[self._cursor_row]

    def get_cursor_column(self) -> int:
        """Return the current column index (0=Name, 1=Value, 2=Source, 3=Description)."""
        return self._cursor_col

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Return currently available actions for the DynamicFooter."""
        if not focused:
            return []
        return [
            ("j/k", "navigate"),
            ("i", "edit"),
            ("Enter", "sources"),
            ("/", "filter"),
            ("Esc", "back"),
        ]

    def action_drill_down(self) -> None:
        """Show the full source chain for the highlighted setting (Enter)."""
        name = self.selected_setting
        if name is not None:
            self.post_message(self.DrillDownRequested(name))

    def update_setting(self, name: str, value: str, source: str) -> None:
        """Update a setting's value and source from external state.

        Args:
            name: Setting name (must be in _SETTINGS_ORDER).
            value: Current effective value.
            source: Source label (e.g., "default", "unsaved", "file").
        """
        if name in self._values:
            self._values[name] = value
            self._sources[name] = source
            # Update the matching FieldDef
            for f in self._fields:
                if f.name == name:
                    f.value = value
                    f.source = source
                    break
            self._reload_table()

    @property
    def selected_setting(self) -> str | None:
        """Return the currently highlighted setting name, or None if empty."""
        if 0 <= self._cursor_row < len(self._settings):
            return self._settings[self._cursor_row]
        return None

    # ------------------------------------------------------------------
    # Cell navigation — rows wrap, columns clamp
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

    def action_cursor_right(self) -> None:
        """Move cursor right one column, clamping at last column."""
        self._cursor_col = min(self._cursor_col + 1, _NUM_COLUMNS - 1)
        self._sync_table_cursor()

    def action_cursor_left(self) -> None:
        """Move cursor left one column, clamping at first column."""
        self._cursor_col = max(self._cursor_col - 1, 0)
        self._sync_table_cursor()

    # ------------------------------------------------------------------
    # Column-aware 'i' action — posts InsertRequested for SmartBar flow
    # ------------------------------------------------------------------

    def action_enter_insert(self) -> None:
        """Column-aware edit action.

        - col 0 (Name) and col 3 (Description): jump to col 1 (Value) and
          initiate INSERT. Neither is editable itself, and silently doing
          nothing there reads as a broken key — the value is what the user
          means to edit from anywhere on the row.
        - col 1 (Value): initiate INSERT mode for field value
        - col 2 (Source): no-op — use Enter to pick a source from the chain
        """
        field_def = self.get_cursor_field()
        if field_def is None:
            return

        if self._cursor_col in (_COL_NAME, _COL_DESC):
            self._cursor_col = _COL_VALUE
            self._sync_table_cursor()
            self.post_message(self.InsertRequested(field_def))
        elif self._cursor_col == _COL_VALUE:
            self.post_message(self.InsertRequested(field_def))
        # col 2 (Source): the source chooser is the Enter drill-down.

    def load_from_store(self, values: dict[str, str], sources: dict[str, str]) -> None:
        """Replace the displayed state with a resolution from the store.

        Without this the panel only ever showed its hardcoded defaults, and
        the Source column read "default" no matter what any file or env var
        said.
        """
        for name in self._settings:
            if name in values:
                self._values[name] = values[name]
            if name in sources:
                self._sources[name] = sources[name]
        self._build_fields()
        self._reload_table()

    # ------------------------------------------------------------------
    # Apply edit (called by app's _on_insert_edit_applied callback)
    # ------------------------------------------------------------------

    def apply_value_edit(self, field: FieldDef, new_value: str) -> None:
        """Apply value edit with linked source change to 'unsaved'.

        Validates the new value against the setting schema. If invalid,
        the edit is silently rejected. If valid, updates the field,
        refreshes the table, and posts SettingChanged.

        an edited-but-not-persisted TUI setting is labelled
        ``"unsaved"`` (in-memory only for this process), distinct from a
        job-config value's provenance.
        """
        # Validate the value against the setting schema
        result = self._validate(field.name, new_value)
        if not result.valid:
            return  # Reject invalid values silently

        field.value = new_value
        field.source = "unsaved"

        # Update internal state
        self._values[field.name] = new_value
        self._sources[field.name] = "unsaved"

        self._reload_table()

        # Post message to app
        from functualize._cli.data.config_target import ConfigTarget

        target = ConfigTarget(type="unsaved", label="Unsaved — this session only")
        self.post_message(self.SettingChanged(field.name, new_value, target))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_fields(self) -> None:
        """Build FieldDef list from current settings state."""
        self._fields = []
        for name in self._settings:
            setting = self._setting(name)
            schema = setting.schema if setting else None
            value = self._values[name]
            source = self._sources[name]

            # Determine choices for this setting
            choices: list[str] | None = None
            if schema is not None:
                if schema.type == "enum":
                    choices = schema.choices
                elif schema.type == "bool":
                    choices = ["true", "false"]

            field = FieldDef(
                name=name,
                value=value,
                source=source,
                choices=choices,
                description=schema.description if schema else "",
                type_annotation=schema.type if schema else "str",
                original_value=value,
                original_source=source,
            )
            self._fields.append(field)

        self._row_count = len(self._fields)

    def _populate_table(self) -> None:
        """Add rows to the DataTable if it's ready and not yet populated."""
        if self._populated or not self._fields or self._table is None:
            return
        self._table.clear()
        for f in self._fields:
            self._table.add_row(f.name, f.value, f.source, f.description)
        self._populated = True
        self._sync_table_cursor()

    def _reload_table(self) -> None:
        """Clear and repopulate the DataTable with current field values."""
        if self._table is None:
            return
        self._table.clear()
        for f in self._fields:
            self._table.add_row(f.name, f.value, f.source, f.description)
        self._populated = True
        self._sync_table_cursor()

    def _sync_table_cursor(self) -> None:
        """Synchronize the DataTable's visual cursor with internal state."""
        if self._table is None or self._row_count == 0:
            return
        with contextlib.suppress(Exception):
            self._table.move_cursor(row=self._cursor_row, column=self._cursor_col)

    # ------------------------------------------------------------------
    # Focus delegation
    # ------------------------------------------------------------------

    def on_focus(self, event: object) -> None:
        """Delegate focus to the inner DataTable."""
        if self._table is not None:
            with contextlib.suppress(Exception):
                self._table.focus()
