"""Textual inline applications for prompt rendering.

Uses Textual's `inline=True` mode to render widgets inline within the terminal
without taking over the full screen. Each prompt spawns a short-lived inline app
that returns the user's response.
"""

from __future__ import annotations

from typing import Any

from textual import on
from textual.app import App, ComposeResult

from functualize_inline.widgets import (
    PromptResult,
)


class InlinePromptApp(App[tuple[Any, str]]):
    """A short-lived Textual app that renders a prompt widget inline.

    Returns a tuple of (value, source) when the user interacts with the widget.
    The app runs in inline mode and exits once a PromptResult message is received.
    """

    CSS = """
    Screen {
        layout: vertical;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        ("ctrl+c", "force_cancel", "Cancel"),
    ]

    def __init__(
        self,
        widget_class: type,
        widget_kwargs: dict[str, Any],
        timeout: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(inline=True, **kwargs)
        self._widget_class = widget_class
        self._widget_kwargs = widget_kwargs
        self._timeout = timeout
        self._timeout_timer: Any = None

    def compose(self) -> ComposeResult:
        yield self._widget_class(**self._widget_kwargs)

    def on_mount(self) -> None:
        """Start timeout timer if configured."""
        if self._timeout is not None and self._timeout > 0:
            self._timeout_timer = self.set_timer(self._timeout, self._on_timeout)

    def _on_timeout(self) -> None:
        """Auto-dismiss on timeout."""
        self.exit((None, "timeout"))

    @on(PromptResult)
    def _on_prompt_result(self, message: PromptResult) -> None:
        """Handle result from the prompt widget."""
        if self._timeout_timer is not None:
            self._timeout_timer.stop()
        self.exit((message.value, message.source))

    def action_force_cancel(self) -> None:
        """Handle Ctrl+C."""
        if self._timeout_timer is not None:
            self._timeout_timer.stop()
        self.exit((None, "cancelled"))
