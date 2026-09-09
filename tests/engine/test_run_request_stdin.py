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

    def test_a_terminal_with_no_value_refuses_rather_than_blocking(
        self, engine: JobExecutionEngine
    ) -> None:
        """Pinned as it behaves, not as it arguably should.

        `resolve_stdin_params` exits 1 when stdin is a terminal and a marked
        parameter is unresolved — **even though this one has a default**. Its
        own comment says "the caller is responsible for determining whether the
        param has a default … signal this so the caller can decide", and then it
        raises `SystemExit` instead of signalling, so no caller ever could.

        That contradiction predates T11 — the click adapter reached the same
        line with the same arguments — so this test records the behaviour rather
        than changing it. See OPEN-QUESTIONS 13.
        """
        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=True
            ),
            pytest.raises(SystemExit) as exc,
        ):
            _run(engine, "func.job")

        assert exc.value.code == 1


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
        """A door added to the set is a door that may read the user's pipe."""
        assert (
            frozenset(
                {
                    "func.job",
                    "func.group",
                    "func.single-file",
                    "func.bare",
                    "func.builtin",
                    "app.cli",
                }
            )
            == CONSOLE_SURFACES
        )
