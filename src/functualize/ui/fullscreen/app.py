"""FullscreenTuiApp — a shipped TextualApp subclass (the fullscreen shell).

A full-screen split-pane app (flow tree + streaming log panel) that renders
engine events into its log panel via ``on_func_event``. It is both a worked
example of subclassing :class:`~functualize.ui.TextualApp` and the fullscreen
shell the orchestrator can push onto the surface stack.

Was the ``functualize-fullscreen-tui`` plugin; folded into ``functualize.ui``
(the [cli] extra) — the plugin's bespoke ``collect``/event-marshaling now comes
from the ``TextualApp`` base.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from functualize.ui._prompt_modal import MODAL_CSS
from functualize.ui.fullscreen.screens import MainScreen
from functualize.ui.textual_app import TextualApp

if TYPE_CHECKING:
    from functualize.ui.textual_app import FuncEvent

__all__ = ["FullscreenTuiApp"]

logger = logging.getLogger(__name__)


class FullscreenTuiApp(TextualApp[None]):
    """Full-screen split-pane app: flow tree (30%) + streaming log panel (70%)."""

    CSS = f"""
    Screen {{
        layout: vertical;
    }}
    {MODAL_CSS}
    """

    TITLE = "functualize"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._main_screen: MainScreen | None = None

    def on_mount(self) -> None:
        """Push the main screen on mount.

        Buffer flushing is handled separately by the base via @on(events.Mount),
        so defining on_mount here is safe.
        """
        self._main_screen = MainScreen()
        self.push_screen(self._main_screen)

    @property
    def main_screen(self) -> MainScreen | None:
        """Access the main screen."""
        return self._main_screen

    def on_func_event(self, message: FuncEvent) -> None:
        """Render one engine event into the log panel (loop thread)."""
        if self._main_screen is None:
            return
        event = message.event
        try:
            self._main_screen.log_panel.write_info(
                f"⚡ Event: {getattr(event, 'event_name', event)} "
                f"(resource={getattr(event, 'resource', '')})"
            )
        except Exception as exc:  # pragma: no cover - defensive UI guard
            logger.debug("Event display error: %s", exc)
