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

from typing import Any

import pytest

from functualize._types.enums import RunStatus
from functualize._types.exit_codes import ExitCode, exit_code_for_status
from functualize.app.adapters.click_params import deliver_job_result


class _Result:
    """The parts of a ``JobResult`` the boundary reads."""

    def __init__(self, status: Any, *, return_value: Any = "VALUE") -> None:
        self.status = status
        self.return_value = return_value
        self.exception = None
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
