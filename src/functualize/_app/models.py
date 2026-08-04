"""Core data models for FunctualizeApp kernel."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PluginCommand:
    """A command registered by a capability plugin.

    Represents a CLI (or adapter) command contributed by a plugin during
    the boot phase. The active adapter retrieves these via
    ``app.get_plugin_commands()`` to include them in its command tree.

    Attributes:
        name: Command name (1-64 chars, lowercase alphanumeric + hyphens).
        callback: The callable to invoke when the command is executed.
        help_text: Help text for the command (max 256 chars).
        namespace: Optional flat CLI namespace the command is mounted under
            (e.g. ``"mcp"`` for ``func mcp serve``). None for top-level. This
            is deliberately NOT ``group`` — ``JobDescriptor.group`` is a dotted
            job hierarchy, a different concept.
    """

    name: str
    callback: Callable[..., Any]
    help_text: str
    namespace: str | None = None
