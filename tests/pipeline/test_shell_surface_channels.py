"""Shell's two surface channels, and why they are two (S6b T-S6b-3 / §C.1).

A shell call produces two very different kinds of text, and a task runner that
sends them to one place is unusable in a pipeline:

* the **command echo** (``$ git status``) — diagnostic. Shares ``log()``'s
  destination: **stderr** when piped. Suppressed by ``silent=True``.
* the **command output** under ``stream=True`` — data. **stdout** when piped,
  which is what makes ``func build | grep …`` work at all.

Conflating them puts ``$ git status`` into the caller's data stream. That is
the whole reason `WiredShell` takes two sinks rather than one, and these tests
exist to keep them from being merged back together by someone tidying up.

The echo is **on by default** (`silent=False`), matching make/invoke/just — a
task runner that hides what it ran is the one thing every user of those tools
notices missing.
"""

from __future__ import annotations

from functualize._engine.capabilities.shell import WiredShell
from functualize._types.redaction import Secret


def _shell(**kw):
    echoed: list[str] = []
    streamed: list[str] = []
    sh = WiredShell(
        echo_sink=echoed.append,
        output_sink=streamed.append,
        **kw,
    )
    return sh, echoed, streamed


class TestCommandEcho:
    def test_the_command_is_echoed_by_default(self) -> None:
        sh, echoed, _ = _shell()

        sh(["echo", "hi"])

        assert any("echo hi" in line for line in echoed)

    def test_the_echo_is_prefixed_so_it_reads_as_a_command(self) -> None:
        sh, echoed, _ = _shell()

        sh(["echo", "hi"])

        assert echoed[0].startswith("$ ")

    def test_silent_suppresses_the_echo(self) -> None:
        sh, echoed, _ = _shell()

        sh(["echo", "hi"], silent=True)

        assert echoed == []

    def test_silent_does_not_suppress_the_output(self) -> None:
        """They are independent channels: quieting the *command* must not
        quiet the *data*, or `silent` would break pipelines."""
        sh, echoed, streamed = _shell()

        sh(["echo", "hi"], stream=True, silent=True)

        assert echoed == []
        assert "".join(streamed).strip() == "hi"

    def test_a_secret_is_masked_in_the_echo(self) -> None:
        """The echo must not leak what `ShellResult.command` already hides."""
        sh, echoed, _ = _shell()

        sh(["echo", Secret("hunter2")])

        assert "hunter2" not in "".join(echoed)


class TestOutputChannel:
    def test_stream_true_routes_to_the_surface_channel(self) -> None:
        sh, _, streamed = _shell()

        sh(["echo", "payload"], stream=True)

        assert "payload" in "".join(streamed)

    def test_an_explicit_callable_sink_still_wins(self) -> None:
        """T9's contract is unchanged — `stream=` a callable is the explicit
        sink and must not be redirected to the surface."""
        sh, _, surface = _shell()
        mine: list[str] = []

        sh(["echo", "payload"], stream=mine.append)

        assert "payload" in "".join(mine)
        assert surface == []

    def test_stream_false_streams_nowhere(self) -> None:
        sh, _, streamed = _shell()

        sh(["echo", "payload"], stream=False)

        assert streamed == []

    def test_output_is_still_captured_while_streaming(self) -> None:
        """Tee semantics (§B.2): streaming and capturing are independent, so a
        live build can be watched *and* reported on afterwards."""
        sh, _, streamed = _shell()

        result = sh(["echo", "payload"], stream=True)

        assert "payload" in result.stdout
        assert "payload" in "".join(streamed)


class TestTheChannelsAreDistinct:
    def test_the_echo_never_reaches_the_output_channel(self) -> None:
        """The pipeline-corruption guard: `$ echo payload` in a caller's data
        stream is the failure this whole two-sink design prevents."""
        sh, echoed, streamed = _shell()

        sh(["echo", "payload"], stream=True)

        assert any("$ " in line for line in echoed)
        assert not any("$ " in chunk for chunk in streamed)

    def test_no_sinks_bound_is_silent_not_a_crash(self) -> None:
        """A WiredShell built without an engine (tests, embedders) must still
        run — the channels are an enhancement, not a requirement."""
        sh = WiredShell()

        result = sh(["echo", "fine"], stream=True)

        assert result.returncode == 0
