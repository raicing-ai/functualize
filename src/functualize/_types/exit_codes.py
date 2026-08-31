"""The single ``RunStatus`` → process exit-code mapping (S5 T39).

Exit codes are a **contract with scripts and agents**, not a UI detail: a
caller greps them to decide whether to retry, escalate, or resume. Scattering
``SystemExit(1)`` across handlers is how that contract silently drifts, so the
table lives here — pure data, stdlib-only, importable from ``_cli``, ``app``
and ``_engine`` alike without a cycle.

The pinned table (`schema.md §4`, reconciled onto `contracts.md §5`):

===  ==========================================================
  0  success
  1  the job raised
  2  usage / config error
  3  refused pre-flight (including ``requires_tty`` while piped)
  4  stale-check failure (``--check``)
  5  blocked awaiting gate input
===  ==========================================================

**5 is deliberately not 3.** A workflow that paused at a gate *ran
successfully* and is resumable; a pre-flight refusal never started. Giving them
one code would force every caller to parse stderr to tell "waiting for a human"
from "I refused" — the distinction a scripted pipeline most needs to act on.
That was decision D-a.
"""

from __future__ import annotations

from enum import IntEnum

from functualize._types.enums import RunStatus

__all__ = ["ExitCode", "exit_code_for_status"]


class ExitCode(IntEnum):
    """Process exit codes functualize commits to."""

    OK = 0
    JOB_RAISED = 1
    USAGE = 2
    REFUSED = 3
    STALE = 4
    BLOCKED = 5


# Only the statuses a *process* can terminate on. RUNNING is transient and
# never observed at the boundary; anything unmapped is a bug in the caller,
# not a new exit code, so it falls back to JOB_RAISED rather than inventing one.
_STATUS_EXIT_CODES: dict[RunStatus, ExitCode] = {
    RunStatus.SUCCESS: ExitCode.OK,
    # A skipped job did what was asked (its guard said "nothing to do"), so it
    # is a success at the process boundary — `func build && func deploy` must
    # not stop because `build` was already up to date.
    RunStatus.SKIPPED: ExitCode.OK,
    RunStatus.BLOCKED: ExitCode.BLOCKED,
    # A refusal is not a skip and not a raise: the job declined to start
    # because a declared precondition for running it was not met. Without this
    # entry it would fall back to JOB_RAISED and be indistinguishable from a
    # job that ran and threw — and REFUSED (3) has been in this table's
    # docstring, reachable only from `requires_tty`, since the table was
    # pinned.
    RunStatus.REFUSED: ExitCode.REFUSED,
    RunStatus.FAILURE: ExitCode.JOB_RAISED,
    RunStatus.TIMEOUT: ExitCode.JOB_RAISED,
    RunStatus.CANCELLED: ExitCode.JOB_RAISED,
    RunStatus.UNKNOWN: ExitCode.JOB_RAISED,
}


def exit_code_for_status(status: RunStatus) -> ExitCode:
    """The process exit code a finished run should terminate with.

    Args:
        status: The terminal :class:`RunStatus` of the run.

    Returns:
        The pinned :class:`ExitCode`. Unmapped statuses answer
        ``JOB_RAISED`` — a run that ended in a state the boundary does not
        recognise is a failure, and inventing a code here would put an
        unpinned number into the contract.
    """
    return _STATUS_EXIT_CODES.get(status, ExitCode.JOB_RAISED)
