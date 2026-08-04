"""Reusable editable table widget built on Textual's DataTable.

Provides:
- Proper column alignment via DataTable with cursor row navigation
- 'e' to edit the current row's value column
- Choices shown as OptionList when field has enum values
- Enter to confirm, Esc to cancel
- Messages: ValueEdited, BackRequested
- get_available_actions(focused) for PanelHost integration

This module is in the ``_cli/`` layer — it imports ONLY from public API.
Textual imports are guarded behind try/except ImportError.
"""

from __future__ import annotations

from typing import Any

try:
    from textual.app import ComposeResult  # noqa: TC002
    from textual.message import Message  # noqa: TC002
    from textual.widget import Widget  # noqa: TC002
    from textual.widgets import DataTable, Input, OptionList
    from textual.widgets._data_table import CellDoesNotExist
    from textual.widgets.option_list import Option
except ImportError as _exc:
    raise ImportError(
        "EditableTable requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc


class EditableTable(Widget):
    """Reusable table widget with inline editing and choice autocomplete.

    Provides:
    - Proper column alignment via DataTable
    - ↑↓ row navigation with cursor highlighting
    - 'e' to edit the current row's value
    - Choices shown as OptionList when field has enum values
    - Enter to confirm, Esc to cancel
    - Messages: ValueEdited, BackRequested
    - get_available_actions(focused) for PanelHost integration
    """

    can_focus = True

    DEFAULT_CSS = """
    EditableTable {
        height: auto;
        min-height: 3;
    }
    EditableTable DataTable {
        height: auto;
        min-height: 2;
        max-height: 8;
    }
    EditableTable .edit-input {
        height: 1;
        display: none;
    }
    EditableTable .edit-input.visible {
        display: block;
    }
    EditableTable .edit-choices {
        height: auto;
        max-height: 4;
        display: none;
    }
    EditableTable .edit-choices.visible {
        display: block;
    }
    """

    class ValueEdited(Message):
        """Posted when a row's value is confirmed via inline edit."""

        def __init__(self, row_key: str, new_value: str) -> None:
            self.row_key = row_key
            self.new_value = new_value
            super().__init__()

    class BackRequested(Message):
        """Posted when user presses Esc in normal mode."""

    class InsertModeEntered(Message):
        """Posted when entering INSERT mode (editing starts)."""

    class InsertModeExited(Message):
        """Posted when leaving INSERT mode (edit confirmed or cancelled)."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._rows_data: list[tuple[str, list[str], list[str] | None]] = []
        self._columns: list[str] = []
        self._editing: bool = False
        self._edit_row_key: str | None = None
        self._edit_choices: list[str] | None = None
        self._filtered_choices: list[str] = []

    def compose(self) -> ComposeResult:
        """Compose: DataTable + hidden Input + hidden OptionList."""
        table: DataTable[Any] = DataTable(id="et-table", cursor_type="row")
        table.show_header = True
        yield table
        yield Input(
            placeholder="Enter value...",
            id="et-input",
            classes="edit-input",
            disabled=True,
        )
        yield OptionList(id="et-choices", classes="edit-choices")

    def on_mount(self) -> None:
        """Configure the DataTable on mount."""
        table = self.query_one("#et-table", DataTable)
        # Prevent DataTable from capturing focus away from us
        table.can_focus = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_columns(self, columns: list[str]) -> None:
        """Set column headers (e.g., ['Setting', 'Value', 'Source']).

        Args:
            columns: List of column header strings.
        """
        self._columns = columns
        table = self.query_one("#et-table", DataTable)
        table.clear(columns=True)
        for col in columns:
            table.add_column(col, key=col)

    def set_rows(self, rows: list[tuple[str, list[str], list[str] | None]]) -> None:
        """Set row data: list of (row_key, cell_values, choices_for_value | None).

        Args:
            rows: Each row is (key, [col1, col2, ...], choices_or_none).
                  choices_or_none: if not None, editing shows these as autocomplete options.
        """
        self._rows_data = rows
        table = self.query_one("#et-table", DataTable)
        table.clear()
        for row_key, cell_values, _choices in rows:
            table.add_row(*cell_values, key=row_key)

    def update_row(self, row_key: str, cell_values: list[str]) -> None:
        """Update a single row's cell values without full rebuild.

        Args:
            row_key: The key identifying the row to update.
            cell_values: New cell values for each column.
        """
        # Update internal data
        for i, (key, _cells, choices) in enumerate(self._rows_data):
            if key == row_key:
                self._rows_data[i] = (row_key, cell_values, choices)
                break

        # Update the DataTable row
        table = self.query_one("#et-table", DataTable)
        try:
            for col_idx, col_key in enumerate(self._columns):
                if col_idx < len(cell_values):
                    table.update_cell(row_key, col_key, cell_values[col_idx])
        except CellDoesNotExist:
            # Row may not exist yet — fall back to full refresh
            pass

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Return actions for PanelHost DynamicFooter.

        Args:
            focused: Whether this widget currently has focus.

        Returns:
            List of (key_label, action_label) tuples.
        """
        if not focused:
            return []

        if self._editing:
            return [("Enter", "confirm"), ("Tab", "complete"), ("Esc", "cancel")]

        actions: list[tuple[str, str]] = []
        if self._rows_data:
            actions.append(("j/k", "navigate"))
            actions.append(("i", "edit"))
            actions.append(("/", "filter"))
        actions.append(("Esc", "back"))
        return actions

    # ------------------------------------------------------------------
    # Action methods (called by App's centralized on_key handler)
    # ------------------------------------------------------------------

    def action_cursor_down(self) -> None:
        """Move table cursor down one row."""
        self._move_cursor_down()

    def action_cursor_up(self) -> None:
        """Move table cursor up one row."""
        self._move_cursor_up()

    def action_enter_insert(self) -> None:
        """Enter INSERT mode — show Input for current row."""
        self._start_edit()

    def action_exit_insert(self) -> None:
        """Exit INSERT mode — cancel edit."""
        if self._editing:
            self._cancel_edit()

    def action_confirm_edit(self) -> None:
        """Confirm the edit — post ValueEdited."""
        if self._editing:
            self._confirm_edit()

    def action_select_choice(self) -> None:
        """Tab — select highlighted choice from OptionList."""
        if self._editing:
            self._select_highlighted_choice()

    def action_choice_up(self) -> None:
        """Navigate choices up."""
        if self._editing:
            self._navigate_choices_up()

    def action_choice_down(self) -> None:
        """Navigate choices down."""
        if self._editing:
            self._navigate_choices_down()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _move_cursor_up(self) -> None:
        """Move DataTable cursor up."""
        table = self.query_one("#et-table", DataTable)
        if table.cursor_row > 0:
            table.move_cursor(row=table.cursor_row - 1)

    def _move_cursor_down(self) -> None:
        """Move DataTable cursor down."""
        table = self.query_one("#et-table", DataTable)
        if table.cursor_row < table.row_count - 1:
            table.move_cursor(row=table.cursor_row + 1)

    # ------------------------------------------------------------------
    # Edit flow
    # ------------------------------------------------------------------

    def _start_edit(self) -> None:
        """Begin inline editing of the value column for the cursor row."""
        if not self._rows_data:
            return

        table = self.query_one("#et-table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row < 0 or cursor_row >= len(self._rows_data):
            return

        row_key, cell_values, choices = self._rows_data[cursor_row]
        self._editing = True
        self._edit_row_key = row_key
        self._edit_choices = choices

        # Pre-fill input with the current value (column index 1 = Value column)
        current_value = cell_values[1] if len(cell_values) > 1 else ""

        input_widget = self.query_one("#et-input", Input)
        input_widget.value = current_value
        input_widget.placeholder = f"Edit: {row_key}"
        input_widget.add_class("visible")
        input_widget.disabled = False
        # Use app-level focus to ensure it takes effect
        if self.app:
            self.app.set_focus(input_widget)
        else:
            input_widget.focus()

        # Notify app of mode change
        self.post_message(self.InsertModeEntered())

        # Show choices if available
        if choices:
            self._filtered_choices = list(choices)
            self._refresh_choices_list(choices)
            self.query_one("#et-choices", OptionList).add_class("visible")
        else:
            self._filtered_choices = []

    def _confirm_edit(self) -> None:
        """Confirm the edit — post ValueEdited message."""
        input_widget = self.query_one("#et-input", Input)
        value = input_widget.value.strip()

        if value and self._edit_row_key is not None:
            self.post_message(self.ValueEdited(self._edit_row_key, value))

        self._dismiss_edit()

    def _cancel_edit(self) -> None:
        """Cancel the edit — hide Input/OptionList, restore normal mode."""
        self._dismiss_edit()

    def _dismiss_edit(self) -> None:
        """Clean up edit state and hide edit widgets."""
        self._editing = False
        self._edit_row_key = None
        self._edit_choices = None
        self._filtered_choices = []

        input_widget = self.query_one("#et-input", Input)
        input_widget.value = ""
        input_widget.remove_class("visible")
        input_widget.disabled = True

        option_list = self.query_one("#et-choices", OptionList)
        option_list.remove_class("visible")
        option_list.clear_options()

        # Notify app of mode change
        self.post_message(self.InsertModeExited())

        self.focus()

    # ------------------------------------------------------------------
    # OptionList / choices management
    # ------------------------------------------------------------------

    def _refresh_choices_list(self, choices: list[str]) -> None:
        """Populate the OptionList with the given choices."""
        option_list = self.query_one("#et-choices", OptionList)
        option_list.clear_options()
        for choice in choices:
            option_list.add_option(Option(choice))
        if choices:
            option_list.highlighted = 0

    def _filter_choices(self, text: str) -> None:
        """Filter the choices based on current input text."""
        if not self._edit_choices:
            return

        if not text:
            self._filtered_choices = list(self._edit_choices)
        else:
            lower_text = text.lower()
            self._filtered_choices = [
                c for c in self._edit_choices if lower_text in c.lower()
            ]

        self._refresh_choices_list(self._filtered_choices)

    def _navigate_choices_up(self) -> None:
        """Move OptionList highlight up."""
        option_list = self.query_one("#et-choices", OptionList)
        if not self._filtered_choices:
            return
        current = option_list.highlighted
        if current is not None and current > 0:
            option_list.highlighted = current - 1

    def _navigate_choices_down(self) -> None:
        """Move OptionList highlight down."""
        option_list = self.query_one("#et-choices", OptionList)
        if not self._filtered_choices:
            return
        current = option_list.highlighted
        if current is not None and current < len(self._filtered_choices) - 1:
            option_list.highlighted = current + 1

    def _select_highlighted_choice(self) -> None:
        """Insert the highlighted choice into the Input."""
        option_list = self.query_one("#et-choices", OptionList)
        if not self._filtered_choices:
            return
        highlighted = option_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self._filtered_choices):
            selected_value = self._filtered_choices[highlighted]
            input_widget = self.query_one("#et-input", Input)
            input_widget.value = selected_value
            # Move cursor to end
            input_widget.cursor_position = len(selected_value)

    # ------------------------------------------------------------------
    # Input change handler — filter choices as user types
    # ------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter choices when input text changes."""
        if self._editing and self._edit_choices:
            self._filter_choices(event.value)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def is_editing(self) -> bool:
        """Whether the table is currently in edit/INSERT mode."""
        return self._editing
