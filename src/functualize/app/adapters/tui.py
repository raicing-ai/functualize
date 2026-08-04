"""TUI delivery adapter using the inline TUI.

This module provides the TuiAdapter that wraps the CLI app with
the built-in inline terminal user interface.

Includes:
- ``TuiAdapter`` — AdapterPlugin-compliant TUI delivery adapter
- ``FunctualizeTUI`` — Multi-screen TUI application class
- ``_detect_app_name`` — helper to detect CLI app name from sys.argv
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize.app.core import FunctualizeApp

__all__ = ["TuiAdapter", "FunctualizeTUI"]


class TuiAdapter:
    """TUI delivery adapter using the built-in inline TUI.

    Satisfies the AdapterPlugin Protocol with adapter_type="tui".
    Wraps the CLI's Click app with the inline terminal UI
    for interactive command exploration and execution.
    """

    name: str = "functualize-tui"
    version: str = "1.0.0"
    description: str = "Built-in inline TUI adapter"
    adapter_type: str = "tui"

    def __init__(self) -> None:
        self._app: FunctualizeApp | None = None

    def __call__(self, app: FunctualizeApp) -> None:
        """Setup phase — store app reference."""
        self._app = app

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Run the TUI application.

        Requires the ``[cli]`` extras group to be installed.

        Raises:
            RuntimeError: If called before __call__(app).
        """
        if self._app is None:
            raise RuntimeError("TuiAdapter.run() called before __call__(app)")

        from functualize._cli.inline_tui import launch_inline_tui

        return launch_inline_tui(self._app)

    def shutdown(self) -> None:
        """No-op shutdown."""
        pass


def _detect_app_name() -> str:
    """Detect the CLI application name from sys.argv[0].

    Returns the basename of the first argument (the program path),
    or 'cli' if sys.argv is empty.
    """
    import os

    if not sys.argv:
        return "cli"
    return os.path.basename(sys.argv[0])


class FunctualizeTUI:
    """Multi-screen TUI application for functualize.

    Provides screen registration and cycling for the full-screen TUI mode.
    """

    BINDINGS = [("ctrl+tab", "cycle_screen", "Next Screen")]

    def __init__(self) -> None:
        self._registered_screens: list[tuple[Any, str]] = []
        self._current_screen_index: int = 0

    def register_screen(self, screen_class: Any, identifier: str) -> None:
        """Register a screen class with an identifier.

        Prevents duplicate registrations for the same identifier.
        """
        for _, existing_id in self._registered_screens:
            if existing_id == identifier:
                return
        self._registered_screens.append((screen_class, identifier))

    def action_cycle_screen(self) -> None:
        """Cycle to the next registered screen.

        Does nothing if no screens are registered.
        """
        if not self._registered_screens:
            return
        self._current_screen_index = (self._current_screen_index + 1) % len(
            self._registered_screens
        )
