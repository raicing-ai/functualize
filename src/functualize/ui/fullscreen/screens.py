"""Main split-pane screen for the fullscreen TUI shell.

The prompt modal now lives in ``functualize.ui._prompt_modal`` (shared by every
``TextualApp`` via ``collect``); this module keeps only the fullscreen-specific
main screen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen

from functualize.ui.fullscreen.widgets import (
    FlowTreeWidget,
    LogPanelWidget,
    StatusBarWidget,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

__all__ = ["MainScreen"]


class MainScreen(Screen[None]):
    """Main screen with split-pane layout: flow tree (30%) + log panel (70%)."""

    DEFAULT_CSS = """
    MainScreen {
        layout: vertical;
    }
    MainScreen > Horizontal {
        height: 1fr;
    }
    MainScreen > Horizontal > #flow-tree-pane {
        width: 30%;
    }
    MainScreen > Horizontal > #log-pane {
        width: 70%;
    }
    """

    BINDINGS = [
        Binding("q", "quit_app", "Quit", show=True),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield FlowTreeWidget(id="flow-tree-pane")
            yield LogPanelWidget(id="log-pane")
        yield StatusBarWidget()

    @property
    def flow_tree(self) -> FlowTreeWidget:
        """Access the flow tree widget."""
        return self.query_one("#flow-tree-pane", FlowTreeWidget)

    @property
    def log_panel(self) -> LogPanelWidget:
        """Access the log panel widget."""
        return self.query_one("#log-pane", LogPanelWidget)

    @property
    def status_bar(self) -> StatusBarWidget:
        """Access the status bar widget."""
        return self.query_one(StatusBarWidget)

    def action_quit_app(self) -> None:
        """Quit the application."""
        self.app.exit()
