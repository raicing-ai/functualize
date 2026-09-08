"""Which `func mcp ...` commands own the controlling terminal.

`serve` does, and a shell front-end must step aside for it rather than capture
its output on a worker thread. The other five return promptly and are safe to
run captured.

The distinction is not cosmetic for `serve`: its default transport is stdio,
where stdout *is* the MCP protocol channel. Capturing that does not render
badly — it corrupts the protocol and hangs the shell.
"""

from __future__ import annotations

import pytest
from functualize_mcp import MCPAdapterPlugin

from functualize.app import FunctualizeApp


@pytest.fixture
def commands():
    """The `mcp` namespace as this plugin registers it.

    Built from a fresh app with the plugin applied explicitly, then filtered to
    `namespace == "mcp"` — an app also picks up whatever else is installed in
    the environment, and a name-only lookup would drift with the dev env.
    """
    app = FunctualizeApp(name="t")
    MCPAdapterPlugin()(app)
    return {c.name: c for c in app.get_plugin_commands() if c.namespace == "mcp"}


def test_serve_owns_the_terminal(commands) -> None:
    assert commands["serve"].needs_terminal is True


@pytest.mark.parametrize("name", ["start", "stop", "list", "tools", "schema"])
def test_the_rest_do_not(commands, name: str) -> None:
    """`start` spawns a background subprocess and returns; the rest just print."""
    assert commands[name].needs_terminal is False


def test_every_registered_command_is_accounted_for(commands) -> None:
    """A new command must make a deliberate choice, not inherit one silently."""
    assert set(commands) == {"serve", "start", "stop", "list", "tools", "schema"}
