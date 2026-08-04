"""FallbackCommand protocol for handling unmatched CLI commands.

Provides a public extension point for custom routing behavior when
no registered Click command matches the user's input.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from functualize.app.core import FunctualizeApp


@runtime_checkable
class FallbackCommand(Protocol):
    """Handler for CLI commands that don't match any registered Click command.

    Fallbacks are tried in order; first match wins. If no fallback matches,
    CliAdapter shows a "command not found" error with suggestions.
    """

    def matches(self, args: list[str], app: FunctualizeApp) -> bool:
        """Return True if this fallback can handle the given arguments."""
        ...

    def execute(self, args: list[str], app: FunctualizeApp) -> int:
        """Execute the fallback handler. Returns exit code (0 = success)."""
        ...
