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

import threading
import time
from typing import Annotated

import pytest
from pydantic import BaseModel
from tests._support.engine_run import register
from tests._support.engine_storage import engine_storage
from tests._support.stdin_fakes import fake_stdin, real_pipe_stdin

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
        **engine_storage(),
    )


def _run(engine: JobExecutionEngine, surface: str, **kwargs: object):
    register(engine, "shout", _shout)
    return engine.run(
        RunRequest(job_name="shout", surface=surface, kwargs=kwargs)  # type: ignore[arg-type]
    )


class TestAConsoleSurfaceReadsThePipe:
    def test_a_pipe_reaches_the_job(self, engine: JobExecutionEngine) -> None:
        with fake_stdin(tty=False, data="from the pipe"):
            result = _run(engine, "func.job")

        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "from the pipe"

    def test_an_explicit_value_beats_the_pipe(self, engine: JobExecutionEngine) -> None:
        """Explicit outranks implicit — the rule `Stdin`'s docstring states."""
        with fake_stdin(tty=False, data="from the pipe"):
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
        with fake_stdin(tty=True):
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
        with fake_stdin(tty=True):
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
        with fake_stdin(tty=False, data="from the pipe") as fake:
            result = _run(engine, surface)

        assert result.return_value == "the default"
        assert fake.read_calls == 0, "a non-console surface must not touch stdin"

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

    #: The doors where a user typed a **job invocation** and may have piped
    #: data into it. Named one by one rather than matched on a prefix: my first
    #: version of this test tested `surface.startswith("func")`, and
    #: `func.builtin` — `func builtin workflow resume`, a *control verb* — would
    #: then have been required to own stdin, which would make a resume read the
    #: terminal. A prefix is not a property.
    _OWNS_STDIN = frozenset({"func.job", "func.group", "func.single-file", "app.cli"})

    def test_no_other_door_owns_stdin(self) -> None:
        """The same claim from the table's side, so a door added to
        `RunSurface` with `owns_stdin=True` fails here even if someone updates
        the list above to match it."""
        from functualize._types.run_request import SURFACE_POLICY

        for surface, policy in SURFACE_POLICY.items():
            assert policy.owns_stdin is (surface in self._OWNS_STDIN), (
                f"{surface} declares owns_stdin={policy.owns_stdin}; only a "
                "door where the user typed a job invocation has a pipe"
            )


class _CollidingConfig(BaseModel):
    """A config model whose field name is also a `Stdin`-marked parameter."""

    data: str = "from the config file"


def _colliding(
    data: Annotated[str, Stdin()] = "the parameter default",
    config: _CollidingConfig = None,  # type: ignore[assignment]
) -> str:
    return f"param={data!r} config={config.data!r}"


class TestAMarkerThatSharesAConfigFieldsName:
    """`_request_kwargs` no longer splits config fields out of the resolution.

    It used to, defended by a claim in its own docstring — "a `Stdin` marker
    never sits on a config model's field" — that nothing asserted. The claim is
    false: the job below declares both, and the framework accepts it. These
    tests are what the split was measured against before it was deleted (rre
    F7), so reinstating it turns the last one red.
    """

    def _run(self, engine: JobExecutionEngine, **kwargs: object):
        register(engine, "collides", _colliding, config_class=_CollidingConfig)
        with fake_stdin(tty=False, data="from the pipe"):
            return engine.run(
                RunRequest(job_name="collides", surface="func.job", kwargs=kwargs)  # type: ignore[arg-type]
            )

    def test_the_collision_is_constructible_at_all(self) -> None:
        """The premise, asserted rather than assumed.

        If a future change makes this overlap impossible — refused at
        registration, say — this test fails and the rest of the class becomes
        moot, which is the right way to find that out.
        """
        from functualize._engine.stdin_reader import stdin_markers_for

        assert set(stdin_markers_for(_colliding)) & set(_CollidingConfig.model_fields)

    def test_the_pipe_reaches_the_colliding_name(
        self, engine: JobExecutionEngine
    ) -> None:
        """The name is a config field, so the pipe's value lands there.

        Not on the parameter: `_resolve_config_model` pops a config field's
        name out of the call kwargs, which is ordinary name shadowing between a
        config model and a parameter and has nothing to do with stdin.
        """
        result = self._run(engine)

        assert result.status is RunStatus.SUCCESS, result.exception
        assert result.return_value == (
            "param='the parameter default' config='from the pipe'"
        )

    def test_an_explicit_value_still_beats_the_pipe(
        self, engine: JobExecutionEngine
    ) -> None:
        result = self._run(engine, data="explicit")

        assert result.status is RunStatus.SUCCESS, result.exception
        assert result.return_value == (
            "param='the parameter default' config='explicit'"
        )

    def test_an_explicit_none_is_dropped_so_the_pipe_can_supply_it(
        self, engine: JobExecutionEngine
    ) -> None:
        """The one case the deleted split actually changed — and it broke it.

        The rule three lines above the split said an explicit `None` on a
        marked parameter is dropped so the pipe (or the default) can win. The
        split exempted config-field names from that rule, so `None` survived
        into the config model and failed its `str` validation. A run that
        should have read the pipe returned FAILURE instead.
        """
        result = self._run(engine, data=None)

        assert result.status is RunStatus.SUCCESS, result.exception
        assert result.return_value == (
            "param='the parameter default' config='from the pipe'"
        )


class TestNothingPipedKeepsTheDefault:
    """The rule the CLI suite pins, through `engine.run` — both suites agree.

    A silent pipe (`sleep 30 | func s`) and an empty stream (`func s <
    /dev/null`) are different shapes and stay distinguishable (the reader
    never reads the first; it reads the second and finds it empty). Both
    resolve nothing, so the parameter's default is what the job receives.
    """

    def test_a_silent_pipe_leaves_the_default(self, engine: JobExecutionEngine) -> None:
        with fake_stdin(tty=False, ready=False):
            result = _run(engine, "func.job")

        assert result.status is RunStatus.SUCCESS, result.exception
        assert result.return_value == "the default"

    def test_an_empty_stream_leaves_the_default(
        self, engine: JobExecutionEngine
    ) -> None:
        with fake_stdin(tty=False, data="", ready=True):
            result = _run(engine, "func.job")

        assert result.status is RunStatus.SUCCESS, result.exception
        assert result.return_value == "the default"

    def test_a_silent_real_pipe_returns_within_the_wall_clock(
        self, engine: JobExecutionEngine
    ) -> None:
        """`sleep 30 | func s` at the engine: default out, no wait, no read.

        The run happens on a daemon worker; a regression to a blocking read
        fails the join timeout instead of hanging the suite.
        """
        outcome: dict[str, object] = {}
        started = time.monotonic()

        def _go() -> None:
            result = _run(engine, "func.job")
            outcome["status"] = result.status
            outcome["value"] = result.return_value

        with real_pipe_stdin(None):
            worker = threading.Thread(target=_go, daemon=True)
            worker.start()
            worker.join(timeout=1.0)
        elapsed = time.monotonic() - started

        assert not worker.is_alive(), "the run blocked on a silent pipe"
        assert elapsed < 1.0
        assert outcome == {"status": RunStatus.SUCCESS, "value": "the default"}

    def test_a_required_param_with_an_empty_stream_fails_as_missing_argument(
        self, engine: JobExecutionEngine
    ) -> None:
        """An empty stream is not "" for a required parameter either.

        The stream resolves nothing, so the call is missing its argument — the
        ordinary error every other parameter raises, not a stdin-specific one.
        """

        def _required(data: Annotated[str, Stdin()]) -> str:
            return data

        register(engine, "required-shout-empty", _required)
        with fake_stdin(tty=False, data="", ready=True):
            result = engine.run(
                RunRequest(job_name="required-shout-empty", surface="func.job")
            )

        assert result.status is not RunStatus.SUCCESS
        assert result.exception is not None
        assert "data" in str(result.exception)

    def test_a_deliberately_empty_flag_is_still_a_value(
        self, engine: JobExecutionEngine
    ) -> None:
        """The distinction that stays visible at the job: explicit "" wins.

        The default would have been "the default"; the user typed "".
        """
        with fake_stdin(tty=False, data="from the pipe"):
            result = _run(engine, "func.job", data="")

        assert result.status is RunStatus.SUCCESS, result.exception
        assert result.return_value == ""
