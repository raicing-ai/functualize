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
    ``app.extensions.get_plugin_commands()`` to include them in its command tree.

    Attributes:
        name: Command name (1-64 chars, lowercase alphanumeric + hyphens).
        callback: The callable to invoke when the command is executed.
        help_text: Help text for the command (max 256 chars).
        namespace: Optional flat CLI namespace the command is mounted under
            (e.g. ``"mcp"`` for ``func mcp serve``). None for top-level. This
            is deliberately NOT ``group`` — ``JobDescriptor.group`` is a dotted
            job hierarchy, a different concept.
        needs_terminal: True when running this command takes over the
            controlling terminal, so a TUI front-end must step aside rather
            than capture its output on a worker thread.

    **Why ``needs_terminal`` exists, and why it is a plain bool.** Until the
    command tree learned about plugin commands a TUI could not reach one, so
    the question never arose. It does now: ``func mcp serve`` runs an MCP
    server whose transport is *stdout itself*, and captured output does not
    merely look wrong — it corrupts the protocol and hangs the shell.

    The bool matches ``CommandNode.needs_terminal``, which chose a static value
    over a predicate because the tree splits command *families* into distinct
    nodes. That argument covers subcommands but not a **flag** on one node, so
    it is worth saying why it still holds: ``mcp serve`` selects its transport
    with ``--http``, and *both* transports block in the foreground. The flag
    picks stdio versus HTTP+SSE, not whether the command returns — so one node
    still has one answer.
    """

    name: str
    callback: Callable[..., Any]
    help_text: str
    namespace: str | None = None
    needs_terminal: bool = False
