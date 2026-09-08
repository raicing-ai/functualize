"""``PluginCommand.needs_terminal`` — a plugin declaring it owns the terminal.

Until the command tree learned about plugin commands, a TUI front-end could not
reach one, so whether a plugin command owns the controlling terminal never came
up. It does now, and the answer is not cosmetic: ``func mcp serve`` runs an MCP
server whose transport is *stdout itself*. A shell that captured that output on
a worker thread would not merely render it oddly — it would corrupt the protocol
and hang.

The field is additive with a ``False`` default, so every plugin written before
it keeps working and keeps the safe answer.
"""

from __future__ import annotations

import pytest

from functualize.app import FunctualizeApp


def _app() -> FunctualizeApp:
    return FunctualizeApp(name="t")


def _find(app: FunctualizeApp, namespace: str | None, name: str):
    """Look a command up by its full address, never by name alone.

    An app picks up every plugin installed in the environment, so a bare
    ``name == "serve"`` search finds `functualize-mcp`'s command when that
    plugin happens to be installed and this test's own when it is not. Keying
    on ``(namespace, name)`` — the pair that actually identifies a command —
    keeps the test about what it registered.
    """
    return next(
        c
        for c in app.get_plugin_commands()
        if c.name == name and c.namespace == namespace
    )


class TestDefault:
    def test_defaults_to_false(self) -> None:
        """A plugin that never heard of the field gets the safe answer."""
        app = _app()
        app.register_plugin_command("plain", lambda: None, help_text="h")

        cmd = _find(app, None, "plain")
        assert cmd.needs_terminal is False

    def test_existing_positional_call_still_works(self) -> None:
        """The pre-existing four-argument call is unchanged."""
        app = _app()
        app.register_plugin_command("legacy", lambda: None, "help text", "ns")

        cmd = _find(app, "ns", "legacy")
        assert (cmd.help_text, cmd.namespace, cmd.needs_terminal) == (
            "help text",
            "ns",
            False,
        )


class TestRoundTrip:
    @pytest.mark.parametrize("declared", [True, False])
    def test_declaration_survives_registration(self, declared: bool) -> None:
        app = _app()
        app.register_plugin_command(
            "serve",
            lambda: None,
            help_text="Start a server",
            namespace="demo",
            needs_terminal=declared,
        )

        cmd = _find(app, "demo", "serve")
        assert cmd.needs_terminal is declared

    def test_declaration_is_per_command_not_per_namespace(self) -> None:
        """Two commands in one namespace answer independently.

        This is the shape `functualize-mcp` needs: `serve` blocks in the
        foreground, `start` spawns a subprocess and returns.
        """
        app = _app()
        app.register_plugin_command(
            "serve", lambda: None, namespace="demo", needs_terminal=True
        )
        app.register_plugin_command(
            "start", lambda: None, namespace="demo", needs_terminal=False
        )

        assert _find(app, "demo", "serve").needs_terminal is True
        assert _find(app, "demo", "start").needs_terminal is False
