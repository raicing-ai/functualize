"""Experiment A: EditBar at App Level (programmatic key forwarding).

A dedicated top-level Input widget (sibling to SmartBar) that becomes visible
during INSERT mode. Instead of relying on Textual's focus system (which is
broken for dynamically shown widgets), we PROGRAMMATICALLY forward keystrokes
from the App's on_key handler directly to the EditBar.

Key insight: The SmartBar works because it ALREADY has focus before the user
types. For a newly-shown Input, focus doesn't reliably move. Solution: keep
the SmartBar focused but intercept keys in INSERT mode and feed them to the
EditBar programmatically.

Architecture:
    App.on_key()
      └── INSERT mode: forward printable chars to EditBar.insert_text_at_cursor()

Run:
    uv run python -m experiments.input_handling.experiment_a_editbar
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Input, Static


class EditBar(Input):
    """Top-level edit input — visible only during INSERT mode.

    Receives characters programmatically from the App's on_key handler.
    Does NOT rely on Textual focus for receiving input.
    """

    DEFAULT_CSS = """
    EditBar {
        display: none;
        border: tall green;
    }
    EditBar.-visible {
        display: block;
    }
    """

    def show_for_edit(self, field_name: str, current_value: str) -> None:
        """Make visible and pre-fill with the current value."""
        self.value = current_value
        self.placeholder = f"Edit {field_name} (current: {current_value})"
        self.add_class("-visible")

    def hide(self) -> None:
        """Hide and clear."""
        self.remove_class("-visible")
        self.value = ""
        self.placeholder = ""


class EditBarApp(App[None]):
    """Option A: EditBar with programmatic key forwarding."""

    CSS = """
    Screen { height: auto; }
    #header { height: 1; background: $primary; color: $text; padding: 0 1; }
    #smart-bar { width: 100%; }
    #edit-context { height: 1; display: none; color: $text-muted; padding: 0 1; }
    #edit-context.-visible { display: block; }
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
        # Table data: key → [setting, value, source]
        self._table_data: dict[str, list[str]] = {
            "timeout": ["timeout", "30", "default"],
            "retries": ["retries", "3", "config.toml"],
            "verbose": ["verbose", "false", "env"],
            "output_dir": ["output_dir", "/tmp", "cli"],
        }

    def compose(self) -> ComposeResult:
        yield Static(" Option A: EditBar (programmatic forwarding)", id="header")
        yield Input(placeholder="SmartBar (type commands here)...", id="smart-bar")
        yield Static("", id="edit-context")
        yield EditBar(placeholder="", id="edit-bar")
        with Vertical(id="panel-container"):
            yield DataTable(id="panel-table", cursor_type="row")
        yield Static("", id="status", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#smart-bar", Input).focus()

        # Populate table
        table = self.query_one("#panel-table", DataTable)
        table.can_focus = False
        table.add_column("Setting", key="setting")
        table.add_column("Value", key="value")
        table.add_column("Source", key="source")
        for key, cells in self._table_data.items():
            table.add_row(*cells, key=key)

        self._update_status()

    def on_key(self, event) -> None:
        """Centralized key handler with programmatic INSERT mode forwarding."""
        if self._mode == "command":
            if event.key == "ctrl+e":
                event.prevent_default()
                event.stop()
                self._enter_normal()
            # Other keys pass through to SmartBar naturally (it has focus)

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
                # Suppress all other keys in NORMAL mode
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
            elif event.key == "backspace":
                event.prevent_default()
                event.stop()
                edit_bar = self.query_one("#edit-bar", EditBar)
                if edit_bar.value:
                    # Delete character before cursor
                    pos = edit_bar.cursor_position
                    if pos > 0:
                        edit_bar.value = (
                            edit_bar.value[: pos - 1] + edit_bar.value[pos:]
                        )
                        edit_bar.cursor_position = pos - 1
            elif event.key == "delete":
                event.prevent_default()
                event.stop()
                edit_bar = self.query_one("#edit-bar", EditBar)
                pos = edit_bar.cursor_position
                if pos < len(edit_bar.value):
                    edit_bar.value = (
                        edit_bar.value[:pos] + edit_bar.value[pos + 1 :]
                    )
            elif event.key == "left":
                event.prevent_default()
                event.stop()
                edit_bar = self.query_one("#edit-bar", EditBar)
                if edit_bar.cursor_position > 0:
                    edit_bar.cursor_position -= 1
            elif event.key == "right":
                event.prevent_default()
                event.stop()
                edit_bar = self.query_one("#edit-bar", EditBar)
                if edit_bar.cursor_position < len(edit_bar.value):
                    edit_bar.cursor_position += 1
            elif event.key == "home" or event.key == "ctrl+a":
                event.prevent_default()
                event.stop()
                edit_bar = self.query_one("#edit-bar", EditBar)
                edit_bar.cursor_position = 0
            elif event.key == "end" or event.key == "ctrl+e":
                event.prevent_default()
                event.stop()
                edit_bar = self.query_one("#edit-bar", EditBar)
                edit_bar.cursor_position = len(edit_bar.value)
            elif len(event.key) == 1 and event.key.isprintable():
                # PROGRAMMATIC FORWARDING: insert the character into EditBar
                event.prevent_default()
                event.stop()
                edit_bar = self.query_one("#edit-bar", EditBar)
                pos = edit_bar.cursor_position
                edit_bar.value = (
                    edit_bar.value[:pos] + event.key + edit_bar.value[pos:]
                )
                edit_bar.cursor_position = pos + 1
            else:
                # Suppress unknown keys
                event.prevent_default()
                event.stop()

    def _enter_normal(self) -> None:
        """Command → Normal: show panel, blur SmartBar so App gets all keys."""
        self._mode = "normal"
        self.query_one("#panel-container").add_class("active")
        # Remove focus from SmartBar so it doesn't consume printable keys
        self.set_focus(None)
        self._update_status()

    def _enter_insert(self) -> None:
        """Normal → Insert: show EditBar with field context."""
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

        self._mode = "insert"

        # Show EditBar with current value
        edit_bar = self.query_one("#edit-bar", EditBar)
        edit_bar.show_for_edit(self._edit_field_name, current_value)

        # Show context line
        ctx = self.query_one("#edit-context", Static)
        ctx.add_class("-visible")
        ctx.update(f" [dim]Editing:[/dim] [bold]{self._edit_field_name}[/bold]")

        self._update_status()

    def _confirm_edit(self) -> None:
        """Insert → Normal: apply value."""
        edit_bar = self.query_one("#edit-bar", EditBar)
        new_value = edit_bar.value.strip()

        if new_value and self._edit_row_key:
            self._table_data[self._edit_row_key][1] = new_value
            table = self.query_one("#panel-table", DataTable)
            table.update_cell(self._edit_row_key, "value", new_value)
            self.notify(f"Set {self._edit_field_name} = {new_value!r}")

        self._dismiss_edit()

    def _cancel_edit(self) -> None:
        """Insert → Normal: discard."""
        self._dismiss_edit()

    def _dismiss_edit(self) -> None:
        """Common cleanup."""
        self._mode = "normal"
        self._edit_row_key = None
        self._edit_field_name = None

        self.query_one("#edit-bar", EditBar).hide()
        ctx = self.query_one("#edit-context", Static)
        ctx.remove_class("-visible")
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
            "insert": "[bold green]INSERT[/bold green] — type in EditBar, Enter confirm, Esc cancel",
        }
        self.query_one("#status", Static).update(f" {mode_display[self._mode]}")


if __name__ == "__main__":
    app = EditBarApp()
    app.run(inline=True, inline_no_clear=True)
