"""`engine.run()` resolves stdin, and only for a console surface (T11).

Stdin resolution used to live in `app/adapters/click_params.py`, where it ran
for click and nothing else. run-request-entry/T11 moved it into the one entry,
which means *every* surface now reaches it — so the rule that used to be
implicit in where the code lived has to be explicit and tested.

Nothing covered this before. `tests/cli/test_stdin_*` exercise
`resolve_stdin_params` directly, so they stay green even when the engine never
calls it: disabling `stdin_markers_for` entirely left all 27 of them passing.
A unit test of the helper is not a test of the wiring.
"""

from __future__ import annotations

from typing import Annotated
from unittest.mock import patch

import pytest
from tests._support.engine_run import register

from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry
from functualize._primitives.di import DIRegistry
from functualize._types.enums import RunStatus
from functualize._types.run_request import CONSOLE_SURFACES, RunRequest
from functualize.job import Stdin


def _shout(data: Annotated[str, Stdin()] = "the default") -> str:
    """Return whatever arrived, so the test can see which source won."""
    return data


@pytest.fixture
def engine() -> JobExecutionEngine:
    return JobExecutionEngine(
        di_registry=DIRegistry(),
        event_bus=EventBus(),
        hook_registry=HookRegistry(),
        middleware_chain=ExecutionMiddlewareChain(),
    )


def _run(engine: JobExecutionEngine, surface: str, **kwargs: object):
    register(engine, "shout", _shout)
    return engine.run(
        RunRequest(job_name="shout", surface=surface, kwargs=kwargs)  # type: ignore[arg-type]
    )


class TestAConsoleSurfaceReadsThePipe:
    def test_a_pipe_reaches_the_job(self, engine: JobExecutionEngine) -> None:
        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty",
                return_value=False,
            ),
            patch(
                "functualize._engine.stdin_reader.sys.stdin.read",
                return_value="from the pipe",
            ),
        ):
            result = _run(engine, "func.job")

        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "from the pipe"

    def test_an_explicit_value_beats_the_pipe(self, engine: JobExecutionEngine) -> None:
        """Explicit outranks implicit — the rule `Stdin`'s docstring states."""
        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty",
                return_value=False,
            ),
            patch(
                "functualize._engine.stdin_reader.sys.stdin.read",
                return_value="from the pipe",
            ),
        ):
            result = _run(engine, "func.job", data="explicit")

        assert result.return_value == "explicit"

    def test_a_terminal_with_no_value_leaves_the_default(
        self, engine: JobExecutionEngine
    ) -> None:
        """No pipe, no flag, a parameter with a default: the default wins.

        This test previously pinned the **opposite** behaviour, and said so:
        `resolve_stdin_params` exited 1 here even though the parameter declared
        a default, under a comment claiming it was signalling to a caller that
        could decide. It was not signalling; it was exiting, and no caller could.

        The maintainer's decision (2026-09-10): a default means optional here as
        it does everywhere else in the framework. So the assertion is inverted
        rather than deleted — what was recorded as a defect is now recorded as
        the rule, in the same place, so a reader sees which way it went.
        """
        with patch(
            "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=True
        ):
            result = _run(engine, "func.job")

        assert result.status is RunStatus.SUCCESS, result.exception
        assert result.return_value == "the default"

    def test_a_parameter_with_no_default_still_fails(
        self, engine: JobExecutionEngine
    ) -> None:
        """One rule, not two.

        Dropping the exit does not make a *required* stdin parameter optional —
        it makes it fail the way every other unsatisfied parameter fails, as a
        missing-argument error, rather than through a bespoke exit inside the
        stdin reader.
        """

        def _required(data: Annotated[str, Stdin()]) -> str:
            return data

        register(engine, "required-shout", _required)
        with patch(
            "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=True
        ):
            result = engine.run(
                RunRequest(job_name="required-shout", surface="func.job")
            )

        assert result.status is not RunStatus.SUCCESS
        assert result.exception is not None


class TestANonConsoleSurfaceDoesNot:
    """The reason `CONSOLE_SURFACES` exists.

    A server's stdin is usually `/dev/null`: not a tty, so the `isatty` guard
    does not save it, and an HTTP request that omits the parameter would be
    handed an empty string rather than the job's default.
    """

    @pytest.mark.parametrize("surface", ["http", "lambda", "mcp.tool", "tui.inline"])
    def test_the_job_keeps_its_default(
        self, engine: JobExecutionEngine, surface: str
    ) -> None:
        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty",
                return_value=False,
            ),
            patch(
                "functualize._engine.stdin_reader.sys.stdin.read",
                return_value="from the pipe",
            ) as read,
        ):
            result = _run(engine, surface)

        assert result.return_value == "the default"
        assert read.call_count == 0, "a non-console surface must not touch stdin"

    def test_the_set_names_only_console_doors(self) -> None:
        """A door that owns stdin is a door that may read the user's pipe.

        Written out here on purpose — this is the **claim**, and the policy
        table is the implementation. Four doors, and each one is a person at a
        terminal. Anything else reading the process's stdin is reading the
        server's `/dev/null` (or stealing a TUI's keystrokes).

        This used to be the *third* hand-typed copy of the same list, beside
        `RunSurface` and `CONSOLE_SURFACES`; there is now one table and this
        assertion checks it rather than agreeing with a sibling copy (rre F6).
        """
        assert (
            frozenset(
                {
                    "func.job",
                    "func.group",
                    "func.single-file",
                    "app.cli",
                }
            )
            == CONSOLE_SURFACES
        )

    def test_no_other_door_owns_stdin(self) -> None:
        """The same claim from the table's side, so a door added to
        `RunSurface` with `owns_stdin=True` fails here even if someone updates
        the list above to match it."""
        from functualize._types.run_request import SURFACE_POLICY

        for surface, policy in SURFACE_POLICY.items():
            expected = surface.split(".")[0] in {"func"} or surface == "app.cli"
            assert policy.owns_stdin is expected, (
                f"{surface} declares owns_stdin={policy.owns_stdin}; only the "
                "console doors (`func.*`, `app.cli`) have a pipe of their own"
            )
