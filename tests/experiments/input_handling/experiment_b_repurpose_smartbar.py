"""Experiment B: Repurpose SmartBar for editing.

When 'i' is pressed, temporarily repurpose the existing SmartBar as the edit
input (like vim's `:` command line):
  1. Save SmartBar state (current text, cursor position)
  2. Replace SmartBar content with the cell's current value
  3. Change placeholder to "Edit: {field_name}"
  4. Change border color to green (indicating edit mode)
  5. On Enter: restore SmartBar, apply value to table
  6. On Esc: restore SmartBar, discard

No new widgets needed — the SmartBar already has focus and works perfectly.
This is the zero-risk approach: if SmartBar typing works in COMMAND mode,
it works in INSERT mode too (it's the same widget).

Run:
    uv run python -m experiments.input_handling.experiment_b_repurpose_smartbar
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Input, Static


class RepurposeSmartBarApp(App[None]):
    """Option B: Reuse the SmartBar Input for INSERT mode editing."""

    CSS = """
    Screen { height: auto; }
    #header { height: 1; background: $primary; color: $text; padding: 0 1; }
    #smart-bar { width: 100%; }
    #smart-bar.editing { border: tall green; }
    #panel-container { display: none; height: auto; min-height: 3; max-height: 10; }
    #panel-container.active { display: block; }
    #status { height: 1; background: $surface; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self._mode = "command"  # command | normal | insert
        self._edit_row_key: str | None = None
        self._edit_field_name: str | None = None
        # Saved SmartBar state for restore
        self._saved_bar_text: str = ""
        self._saved_bar_cursor: int = 0
        self._saved_bar_placeholder: str = ""
        # Table data
        self._table_data: dict[str, list[str]] = {
            "timeout": ["timeout", "30", "default"],
            "retries": ["retries", "3", "config.toml"],
            "verbose": ["verbose", "false", "env"],
            "output_dir": ["output_dir", "/tmp", "cli"],
        }

    def compose(self) -> ComposeResult:
        yield Static(" Option B: Repurpose SmartBar", id="header")
        yield Input(
            placeholder="SmartBar (type commands here)...", id="smart-bar"
        )
        with Vertical(id="panel-container"):
            yield DataTable(id="panel-table", cursor_type="row")
        yield Static("", id="status", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#smart-bar", Input).focus()

        table = self.query_one("#panel-table", DataTable)
        table.can_focus = False
        table.add_column("Setting", key="setting")
        table.add_column("Value", key="value")
        table.add_column("Source", key="source")
        for key, cells in self._table_data.items():
            table.add_row(*cells, key=key)

        self._update_status()

    def on_key(self, event) -> None:
        """Centralized key handler."""
        if self._mode == "command":
            if event.key == "ctrl+e":
                event.prevent_default()
                event.stop()
                self._enter_normal()

        elif self._mode == "normal":
            if event.key == "j":
                event.prevent_default()
                event.stop()
                table = self.query_one("#panel-table", DataTable)
                if table.cursor_row < table.row_count - 1:
                    table.move_cursor(row=table.cursor_row + 1)
            elif event.key == "k":
                event.prevent_default()
                event.stop()
                table = self.query_one("#panel-table", DataTable)
                if table.cursor_row > 0:
                    table.move_cursor(row=table.cursor_row - 1)
            elif event.key == "i":
                event.prevent_default()
                event.stop()
                self._enter_insert()
            elif event.key == "escape":
                event.prevent_default()
                event.stop()
                self._exit_to_command()
            else:
                if len(event.key) == 1 and event.key.isprintable():
                    event.prevent_default()
                    event.stop()

        elif self._mode == "insert":
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._cancel_edit()
            elif event.key == "enter":
                event.prevent_default()
                event.stop()
                self._confirm_edit()
            # All other keys pass through to SmartBar (it already has focus!)

    def _enter_normal(self) -> None:
        """Command → Normal: show panel, blur SmartBar."""
        self._mode = "normal"
        self.query_one("#panel-container").add_class("active")
        # Blur SmartBar so App's on_key gets printable keys in NORMAL mode
        self.set_focus(None)
        self._update_status()

    def _enter_insert(self) -> None:
        """Normal → Insert: save SmartBar state, repurpose for editing."""
        table = self.query_one("#panel-table", DataTable)
        row_idx = table.cursor_row
        if row_idx < 0:
            return

        keys = list(self._table_data.keys())
        if row_idx >= len(keys):
            return

        self._edit_row_key = keys[row_idx]
        self._edit_field_name = self._table_data[self._edit_row_key][0]
        current_value = self._table_data[self._edit_row_key][1]

        # Save current SmartBar state
        bar = self.query_one("#smart-bar", Input)
        self._saved_bar_text = bar.value
        self._saved_bar_cursor = bar.cursor_position
        self._saved_bar_placeholder = bar.placeholder

        # Repurpose SmartBar for editing
        bar.value = current_value
        bar.placeholder = f"Edit: {self._edit_field_name}"
        bar.cursor_position = len(current_value)
        bar.add_class("editing")
        # Re-focus the SmartBar (was blurred in _enter_normal)
        self.set_focus(bar)

        self._mode = "insert"
        self._update_status()

    def _confirm_edit(self) -> None:
        """Insert → Normal: apply value, restore SmartBar."""
        bar = self.query_one("#smart-bar", Input)
        new_value = bar.value.strip()

        if new_value and self._edit_row_key:
            self._table_data[self._edit_row_key][1] = new_value
            table = self.query_one("#panel-table", DataTable)
            table.update_cell(self._edit_row_key, "value", new_value)
            self.notify(f"Set {self._edit_field_name} = {new_value!r}")

        self._restore_smartbar()

    def _cancel_edit(self) -> None:
        """Insert → Normal: discard, restore SmartBar."""
        self._restore_smartbar()

    def _restore_smartbar(self) -> None:
        """Restore SmartBar to its pre-edit state."""
        self._mode = "normal"
        bar = self.query_one("#smart-bar", Input)
        bar.value = self._saved_bar_text
        bar.placeholder = self._saved_bar_placeholder
        bar.cursor_position = self._saved_bar_cursor
        bar.remove_class("editing")
        self._edit_row_key = None
        self._edit_field_name = None
        # Blur so App's on_key gets j/k/i in NORMAL mode
        self.set_focus(None)
        self._update_status()

    def _exit_to_command(self) -> None:
        """Normal → Command: hide panel, focus SmartBar."""
        self._mode = "command"
        self.query_one("#panel-container").remove_class("active")
        self.query_one("#smart-bar", Input).focus()
        self._update_status()

    def _update_status(self) -> None:
        mode_display = {
            "command": "[dim]COMMAND[/dim] — type in SmartBar, Ctrl+E opens panel",
            "normal": "[bold cyan]NORMAL[/bold cyan] — j/k navigate, i edit, Esc back",
            "insert": "[bold green]INSERT[/bold green] — type in SmartBar, Enter confirm, Esc cancel",
        }
        self.query_one("#status", Static).update(f" {mode_display[self._mode]}")


if __name__ == "__main__":
    app = RepurposeSmartBarApp()
    app.run(inline=True, inline_no_clear=True)
