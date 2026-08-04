"""Experiment: Broken nested Input (reproduces the current issue).

This demonstrates the bug: an Input widget nested inside a container
that uses CSS `display: none` → `display: block` toggling does NOT
reliably receive keyboard focus in Textual's inline mode.

Architecture:
    App
    ├── SmartBar (Input, top-level) ← works fine
    └── PanelContainer (Vertical, display:none initially)
        └── EditablePanel (Widget)
            ├── DataTable (cursor_type="row")
            └── EditInput (Input, display:none, toggled visible on 'i')

Run:
    uv run python -m experiments.input_handling.experiment_broken_nested
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Input, Static


class EditablePanel(Vertical):
    """Panel with a DataTable and a hidden Input for editing."""

    DEFAULT_CSS = """
    EditablePanel {
        height: auto;
        min-height: 4;
        max-height: 12;
    }
    EditablePanel .edit-input {
        display: none;
        height: 1;
    }
    EditablePanel .edit-input.visible {
        display: block;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._editing = False
        self._edit_row: int = -1

    def compose(self) -> ComposeResult:
        table = DataTable(id="panel-table", cursor_type="row")
        table.can_focus = False
        yield table
        yield Input(
            placeholder="Edit value...",
            id="panel-edit-input",
            classes="edit-input",
            disabled=True,
        )

    def on_mount(self) -> None:
        table = self.query_one("#panel-table", DataTable)
        table.add_columns("Setting", "Value", "Source")
        table.add_row("timeout", "30", "default", key="timeout")
        table.add_row("retries", "3", "config.toml", key="retries")
        table.add_row("verbose", "false", "env", key="verbose")
        table.add_row("output_dir", "/tmp", "cli", key="output_dir")

    def start_edit(self) -> None:
        """Try to enter edit mode — shows the Input and attempts focus."""
        table = self.query_one("#panel-table", DataTable)
        row_idx = table.cursor_row
        if row_idx < 0:
            return

        self._editing = True
        self._edit_row = row_idx

        inp = self.query_one("#panel-edit-input", Input)
        inp.value = ""
        inp.placeholder = f"Edit row {row_idx}..."
        inp.add_class("visible")
        inp.disabled = False

        # This is what the current code does — and it doesn't work reliably
        self.app.set_focus(inp)

    def cancel_edit(self) -> None:
        """Cancel editing."""
        self._editing = False
        inp = self.query_one("#panel-edit-input", Input)
        inp.remove_class("visible")
        inp.disabled = True
        inp.value = ""
        # Blur so App's on_key gets keys in NORMAL mode
        self.app.set_focus(None)

    @property
    def is_editing(self) -> bool:
        return self._editing


class BrokenNestedApp(App[None]):
    """Demonstrates the broken nested Input issue."""

    CSS = """
    Screen { height: auto; }
    #header { height: 1; background: $primary; color: $text; padding: 0 1; }
    #smart-bar { width: 100%; }
    #panel-container { display: none; height: auto; }
    #panel-container.active { display: block; }
    #status { height: 1; background: $surface; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self._mode = "command"  # command | normal | insert

    def compose(self) -> ComposeResult:
        yield Static(" Broken Nested Input Experiment", id="header")
        yield Input(placeholder="SmartBar (type commands here)...", id="smart-bar")
        with Vertical(id="panel-container"):
            yield EditablePanel()
        yield Static(" [mode: command]", id="status", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#smart-bar", Input).focus()
        self._update_status()

    def on_key(self, event) -> None:
        """Centralized key handler mimicking the real TUI."""
        if self._mode == "command":
            if event.key == "ctrl+e":
                # Open panel
                event.prevent_default()
                event.stop()
                self._mode = "normal"
                self.query_one("#panel-container").add_class("active")
                # Blur SmartBar so App's on_key gets all printable keys
                self.set_focus(None)
                self._update_status()
            # Other keys pass through to SmartBar

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
                self._mode = "insert"
                panel = self.query_one(EditablePanel)
                panel.start_edit()
                self._update_status()
            elif event.key == "escape":
                event.prevent_default()
                event.stop()
                self._mode = "command"
                self.query_one("#panel-container").remove_class("active")
                self.query_one("#smart-bar", Input).focus()
                self._update_status()
            else:
                # Suppress printable chars in normal mode
                if len(event.key) == 1 and event.key.isprintable():
                    event.prevent_default()
                    event.stop()

        elif self._mode == "insert":
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._mode = "normal"
                panel = self.query_one(EditablePanel)
                panel.cancel_edit()
                self._update_status()
            elif event.key == "enter":
                event.prevent_default()
                event.stop()
                # Confirm edit
                inp = self.query_one("#panel-edit-input", Input)
                value = inp.value
                self._mode = "normal"
                panel = self.query_one(EditablePanel)
                panel.cancel_edit()
                self._update_status()
                self.notify(f"Confirmed: {value!r}")
            # In INSERT mode, all other keys should pass to the Input
            # BUT they don't — that's the bug!

    def _update_status(self) -> None:
        mode_display = {
            "command": "[dim]COMMAND[/dim] — type in SmartBar, Ctrl+E opens panel",
            "normal": "[bold cyan]NORMAL[/bold cyan] — j/k navigate, i edit, Esc back",
            "insert": "[bold green]INSERT[/bold green] — type to edit, Enter confirm, Esc cancel",
        }
        self.query_one("#status", Static).update(
            f" {mode_display[self._mode]}"
        )


if __name__ == "__main__":
    app = BrokenNestedApp()
    app.run(inline=True, inline_no_clear=True)
