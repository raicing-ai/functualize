"""Experiment: The ACTUAL broken case (SmartBar stays focused in NORMAL mode).

This reproduces the REAL bug in the current TUI codebase. The issue is NOT
that nested Inputs can't receive focus — it's that the SmartBar (an Input
widget) stays focused when entering NORMAL mode, so:

1. Key events go to SmartBar first (it has focus)
2. SmartBar consumes printable characters (Input.on_key stops them)
3. App's on_key never sees 'j', 'k', 'i', '/' etc.
4. Panel navigation and INSERT mode entry are impossible

The fix is simple: `self.set_focus(None)` when entering NORMAL mode.

Run:
    uv run python -m experiments.input_handling.experiment_truly_broken
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Input, Static


class TrulyBrokenApp(App[None]):
    """The actual broken scenario: SmartBar keeps focus in NORMAL mode."""

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
        self._mode = "command"

    def compose(self) -> ComposeResult:
        yield Static(" BROKEN: SmartBar stays focused", id="header")
        yield Input(placeholder="SmartBar...", id="smart-bar")
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
        table.add_row("timeout", "30", key="timeout")
        self._update_status()

    def on_key(self, event) -> None:
        if self._mode == "command":
            if event.key == "ctrl+e":
                event.prevent_default()
                event.stop()
                self._mode = "normal"
                self.query_one("#panel-container").add_class("active")
                # BUG: We do NOT blur SmartBar here!
                # SmartBar keeps focus, so 'j', 'k', 'i' go to SmartBar, not here
                self._update_status()

        elif self._mode == "normal":
            # This code is UNREACHABLE for printable keys because
            # SmartBar (Input) consumes them before they reach App.on_key
            if event.key == "i":
                event.prevent_default()
                event.stop()
                self._mode = "insert"
                self._update_status()
            elif event.key == "escape":
                event.prevent_default()
                event.stop()
                self._mode = "command"
                self.query_one("#panel-container").remove_class("active")
                self._update_status()

    def _update_status(self) -> None:
        self.query_one("#status", Static).update(f" mode={self._mode}")


if __name__ == "__main__":
    app = TrulyBrokenApp()
    app.run(inline=True, inline_no_clear=True)
