"""Every terminal status takes its exit code from the one table (D-6).

`_types/exit_codes.py` describes itself as *"The single ``RunStatus`` → process
exit-code mapping"* and warns that scattering ``SystemExit`` "is how that
contract silently drifts". `deliver_job_result` then hand-coded `BLOCKED` and
`REFUSED` beside their messages and let **everything else** fall through to
``return result.return_value`` — exit 0.

Nothing reaches that fall-through today: `TIMEOUT` and `CANCELLED` are produced
only by `Invoke.parallel` and never terminate a top-level run. So this changes
no exit code anyone can currently observe, and the tests below are not about a
live bug. They are about the trap, which is the exact shape of D7 — the worst
defect the previous cycle fixed: one rule, stated in two places, one of which
quietly answered 0.

The last test is the one that matters most. It asks what happens to a status the
table does **not** know, and the answer must be 1. A future `RunStatus` member
that silently exited 0 is how a false clean gets reintroduced by addition rather
than by edit — and `GuardState`'s `.get(state, RunStatus.SKIPPED)` default,
twenty lines away in the executor, is the same trap still open.
"""

from __future__ import annotations

import logging
from typing import Any

import click
import pytest

from functualize._types.enums import RunStatus
from functualize._types.exit_codes import ExitCode, exit_code_for_status
from functualize._types.outcome import RAISED_BY_JOB
from functualize.app.adapters.click_params import deliver_job_result


class _Result:
    """The parts of a ``JobResult`` the boundary reads."""

    def __init__(self, status: Any, *, return_value: Any = "VALUE") -> None:
        self.status = status
        self.return_value = return_value
        self.exception: BaseException | None = None
        self.metadata: dict[str, Any] = {}


# Every status a *process* can terminate on. RUNNING is transient and never
# observed at the boundary, which is why the table omits it too.
TERMINAL = [
    RunStatus.SUCCESS,
    RunStatus.SKIPPED,
    RunStatus.BLOCKED,
    RunStatus.REFUSED,
    RunStatus.FAILURE,
    RunStatus.TIMEOUT,
    RunStatus.CANCELLED,
    RunStatus.UNKNOWN,
]


@pytest.mark.parametrize("status", TERMINAL, ids=lambda s: s.name)
def test_the_boundary_uses_the_table_for_every_status(status: RunStatus) -> None:
    expected = exit_code_for_status(status)

    if expected == ExitCode.OK:
        assert deliver_job_result(_Result(status), "j") == "VALUE"
        return

    with pytest.raises(SystemExit) as raised:
        deliver_job_result(_Result(status), "j")
    assert raised.value.code == expected


def test_an_unmapped_status_exits_one_not_zero() -> None:
    """The trap this change exists to remove.

    A status the table does not recognise used to fall through to
    ``return result.return_value``, which click renders as exit 0. A run that
    ended in a state the boundary cannot name is a failure; answering 0 is the
    false clean in miniature.
    """

    class _Invented:
        """Stands in for a `RunStatus` member added after this table was written."""

        name = "INVENTED"
        value = "Invented"

    with pytest.raises(SystemExit) as raised:
        deliver_job_result(_Result(_Invented()), "j")
    assert raised.value.code == ExitCode.JOB_RAISED


def test_the_two_statuses_that_speak_still_speak(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Moving the code to the table must not take the message with it.

    A refusal that exits 3 in silence is barely better than one that exits 0:
    the CI reader has to act on it, and the reason is the whole content.
    """
    with pytest.raises(SystemExit):
        deliver_job_result(_Result(RunStatus.REFUSED), "j")
    assert "Refused:" in capsys.readouterr().err

    blocked = _Result(RunStatus.BLOCKED)
    blocked.metadata = {"blocked_on": "commentary", "workflow_scope": "abc123"}
    with pytest.raises(SystemExit):
        deliver_job_result(blocked, "j")
    assert "Blocked:" in capsys.readouterr().err


def test_a_refusals_reason_reaches_stderr() -> None:
    """The refusal message is the declaration's own words, not a generic line."""
    result = _Result(RunStatus.REFUSED)
    result.metadata = {"skip_reason": "declared sources resolved to no files (a/*.tf)"}

    with pytest.raises(SystemExit) as raised:
        deliver_job_result(result, "j")
    assert raised.value.code == ExitCode.REFUSED


# ─── A job's own exception (raised_by_job) ─────────────────────────────────
#
# The engine marks a failed result whose exception escaped the job function
# call (`_types/outcome.py` `RAISED_BY_JOB`). The boundary renders exactly that
# case as one line at the "job raised" code and re-raises everything else, so
# a framework failure keeps the traceback its reporter needs.

_BOUNDARY_LOGGER = "functualize.app.adapters.click_params"


class _Domain:
    class BadInputError(Exception):
        pass


def _failed(exc: BaseException, *, marked: bool) -> _Result:
    result = _Result(RunStatus.FAILURE)
    result.exception = exc
    if marked:
        result.metadata = {RAISED_BY_JOB: True}
    return result


def test_the_jobs_own_exception_is_one_line_at_the_job_raised_code(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=_BOUNDARY_LOGGER)
    exc = RuntimeError("boom")

    with pytest.raises(SystemExit) as raised:
        deliver_job_result(_failed(exc, marked=True), "j")

    assert raised.value.code == ExitCode.JOB_RAISED
    assert raised.value.__cause__ is exc
    captured = capsys.readouterr()
    assert captured.err == "Error: RuntimeError: boom\n"
    assert captured.out == ""


def test_an_empty_message_prints_the_class_alone(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=_BOUNDARY_LOGGER)

    with pytest.raises(SystemExit):
        deliver_job_result(_failed(ValueError(), marked=True), "j")

    assert capsys.readouterr().err == "Error: ValueError\n"


def test_nested_exception_class_keeps_its_qualified_name_without_a_module(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=_BOUNDARY_LOGGER)

    with pytest.raises(SystemExit) as raised:
        deliver_job_result(_failed(_Domain.BadInputError("bad row"), marked=True), "j")

    assert raised.value.code == ExitCode.JOB_RAISED
    assert capsys.readouterr().err == "Error: _Domain.BadInputError: bad row\n"


def test_an_unmarked_exception_is_re_raised_untouched(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Not the job's own — a framework failure keeps its traceback."""
    caplog.set_level(logging.INFO, logger=_BOUNDARY_LOGGER)
    exc = RuntimeError("engine bug")

    with pytest.raises(RuntimeError) as raised:
        deliver_job_result(_failed(exc, marked=False), "j")

    assert raised.value is exc


def test_debug_is_the_opt_in_back_to_the_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_BOUNDARY_LOGGER)
    exc = RuntimeError("boom")

    with pytest.raises(RuntimeError) as raised:
        deliver_job_result(_failed(exc, marked=True), "j")

    assert raised.value is exc


@pytest.mark.parametrize(
    "exc",
    [
        click.ClickException("bad input"),
        click.exceptions.Abort(),
        click.exceptions.Exit(4),
        KeyboardInterrupt(),
    ],
    ids=lambda e: type(e).__name__,
)
def test_click_signals_and_base_exceptions_keep_their_own_rendering(
    exc: BaseException, caplog: pytest.LogCaptureFixture
) -> None:
    """A job raising a click signal chose click's rendering; leave it to click."""
    caplog.set_level(logging.INFO, logger=_BOUNDARY_LOGGER)

    with pytest.raises(type(exc)) as raised:
        deliver_job_result(_failed(exc, marked=True), "j")

    assert raised.value is exc
