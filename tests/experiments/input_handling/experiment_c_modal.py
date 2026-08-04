"""Experiment C: Modal Edit overlay.

When 'i' is pressed, mount a small overlay widget at `layer: modal` level.
Textual's modal layer captures all input, so focus is guaranteed.

This is similar to how QuickOverrideModal worked in the previous commit
(39901d1) — it was mounted at the app level and captured focus reliably.

Architecture:
    App
    ├── SmartBar (Input)
    ├── PanelContainer (Vertical)
    │   └── DataTable
    └── EditModal (Widget, layer: modal)  ← mounted on 'i', removed on confirm/cancel
        ├── Static (field label)
        └── Input (edit value)

Run:
    uv run python -m experiments.input_handling.experiment_c_modal
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Footer, Input, Static


class EditModal(Vertical):
    """Overlay modal for editing a single value.

    Mounted dynamically, captures focus via layer: modal.
    Posts EditConfirmed or EditCancelled when done.
    """

    DEFAULT_CSS = """
    EditModal {
        layer: modal;
        height: auto;
        max-height: 5;
        padding: 0 1;
        background: $surface;
        border: round green;
        margin: 1 4;
    }
    EditModal #modal-input {
        width: 100%;
    }
    """

    class EditConfirmed(Message):
        """User confirmed the edit."""

        def __init__(self, row_key: str, field_name: str, new_value: str) -> None:
            super().__init__()
            self.row_key = row_key
            self.field_name = field_name
            self.new_value = new_value

    class EditCancelled(Message):
        """User cancelled the edit."""

    def __init__(
        self, row_key: str, field_name: str, current_value: str
    ) -> None:
        super().__init__()
        self._row_key = row_key
        self._field_name = field_name
        self._current_value = current_value

    def compose(self) -> ComposeResult:
        yield Static(
            f" [bold]Edit:[/bold] {self._field_name}",
            markup=True,
        )
        yield Input(
            value=self._current_value,
            placeholder=f"New value for {self._field_name}",
            id="modal-input",
        )
        yield Static(
            " [dim]Enter[/dim] confirm  [dim]Esc[/dim] cancel",
            markup=True,
        )

    def on_mount(self) -> None:
        """Focus the input immediately after mounting."""
        inp = self.query_one("#modal-input", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_key(self, event) -> None:
        """Handle confirm/cancel at the modal level."""
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.post_message(self.EditCancelled())
            self.remove()
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            inp = self.query_one("#modal-input", Input)
            self.post_message(
                self.EditConfirmed(
                    self._row_key, self._field_name, inp.value.strip()
                )
            )
            self.remove()


class ModalEditApp(App[None]):
    """Option C: Modal overlay for INSERT mode editing."""

    CSS = """
    Screen { height: auto; }
    #header { height: 1; background: $primary; color: $text; padding: 0 1; }
    #smart-bar { width: 100%; }
    #panel-container { display: none; height: auto; min-height: 3; max-height: 10; }
    #panel-container.active { display: block; }
    #status { height: 1; background: $surface; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self._mode = "command"  # command | normal | insert
        self._table_data: dict[str, list[str]] = {
            "timeout": ["timeout", "30", "default"],
            "retries": ["retries", "3", "config.toml"],
            "verbose": ["verbose", "false", "env"],
            "output_dir": ["output_dir", "/tmp", "cli"],
        }

    def compose(self) -> ComposeResult:
        yield Static(" Option C: Modal Edit", id="header")
        yield Input(placeholder="SmartBar (type commands here)...", id="smart-bar")
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
            # Modal handles its own keys — we shouldn't get here normally
            # because the modal's on_key intercepts everything.
            # But just in case:
            pass

    def _enter_normal(self) -> None:
        self._mode = "normal"
        self.query_one("#panel-container").add_class("active")
        # Blur SmartBar so App's on_key gets printable keys in NORMAL mode
        self.set_focus(None)
        self._update_status()

    def _enter_insert(self) -> None:
        """Normal → Insert: mount a modal overlay."""
        table = self.query_one("#panel-table", DataTable)
        row_idx = table.cursor_row
        if row_idx < 0:
            return

        keys = list(self._table_data.keys())
        if row_idx >= len(keys):
            return

        row_key = keys[row_idx]
        field_name = self._table_data[row_key][0]
        current_value = self._table_data[row_key][1]

        self._mode = "insert"
        self._update_status()

        # Mount the modal — it handles its own focus
        modal = EditModal(row_key, field_name, current_value)
        self.mount(modal)

    def on_edit_modal_edit_confirmed(self, event: EditModal.EditConfirmed) -> None:
        """Modal confirmed — apply value."""
        if event.new_value and event.row_key in self._table_data:
            self._table_data[event.row_key][1] = event.new_value
            table = self.query_one("#panel-table", DataTable)
            table.update_cell(event.row_key, "value", event.new_value)
            self.notify(f"Set {event.field_name} = {event.new_value!r}")

        self._mode = "normal"
        # Blur so App's on_key gets j/k/i in NORMAL mode
        self.set_focus(None)
        self._update_status()

    def on_edit_modal_edit_cancelled(self, event: EditModal.EditCancelled) -> None:
        """Modal cancelled — return to normal."""
        self._mode = "normal"
        # Blur so App's on_key gets j/k/i in NORMAL mode
        self.set_focus(None)
        self._update_status()

    def _exit_to_command(self) -> None:
        self._mode = "command"
        self.query_one("#panel-container").remove_class("active")
        self.query_one("#smart-bar", Input).focus()
        self._update_status()

    def _update_status(self) -> None:
        mode_display = {
            "command": "[dim]COMMAND[/dim] — type in SmartBar, Ctrl+E opens panel",
            "normal": "[bold cyan]NORMAL[/bold cyan] — j/k navigate, i edit, Esc back",
            "insert": "[bold green]INSERT[/bold green] — editing in modal...",
        }
        self.query_one("#status", Static).update(f" {mode_display[self._mode]}")


if __name__ == "__main__":
    app = ModalEditApp()
    app.run(inline=True, inline_no_clear=True)
