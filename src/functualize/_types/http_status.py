"""The single ``RunStatus`` → HTTP status-code mapping.

An HTTP status code is a **contract with callers**, the same way an exit code
is a contract with scripts: a client greps it to decide whether to retry, poll,
escalate, or give up. Scattering ``return 200`` across trigger plugins is how
that contract silently drifts, so the table lives here — pure data, stdlib-only,
importable by every delivery surface without a cycle.

This module is the HTTP sibling of :mod:`functualize._types.exit_codes`, and it
deliberately mirrors that table's partition. Where the two disagree, they are
wrong; where they agree, the agreement is the point.

Why it exists at all
--------------------

``functualize-lambda``'s generated handler read ``result.status`` **not at
all**::

    result = app.execute(job_name, **job_kwargs)
    return {"statusCode": 200, "body": result.return_value}

Every outcome the engine *returns* — a failure, a refusal, a workflow paused at
a gate — arrived as ``{"statusCode": 200, "body": None}``, indistinguishable
from a job that succeeded and returned nothing. Only an exception that escaped
``execute()`` became a 500, and the engine's whole design is that failures do
**not** escape: they are returned so a surface can render them. So the branch
that reported failure was the one the engine tries hardest never to take.

That is why this is a table and not a helper on the plugin. A second surface
(``functualize-http``) already had its own partial answer, and the third would
have written a third.

``RUNNING`` is deliberately unmapped
------------------------------------

It is transient and never observed at a request boundary — a synchronous call
cannot return while its job is still running. Anything unmapped falls back to
``INTERNAL_SERVER_ERROR`` rather than inventing a code, because an unmapped
status is a bug in the caller, not a new outcome. This is the same choice, for
the same reason, that ``_STATUS_EXIT_CODES`` makes.
"""

from __future__ import annotations

from functualize._types.enums import RunStatus

__all__ = ["http_status_for_status"]


# Only the statuses a *request* can terminate on. Keep this aligned with
# `_types/exit_codes._STATUS_EXIT_CODES`: the two answer the same question for
# two different boundaries, and a divergence between them is a defect.
_STATUS_HTTP_CODES: dict[RunStatus, int] = {
    RunStatus.SUCCESS: 200,
    # A skipped job did what was asked — its guard said "nothing to do" — so it
    # is a success at the boundary, exactly as it is exit code 0. A caller
    # chaining requests must not treat "already up to date" as an error.
    RunStatus.SKIPPED: 200,
    # 202 Accepted: the walk ran and stopped at a declared pause point, and is
    # resumable. It is neither a success (the work is unfinished) nor an error
    # (nothing went wrong), and 202 is the only code that says exactly that.
    # This is the HTTP face of `RunStatus.resumable`.
    RunStatus.BLOCKED: 202,
    # 412 Precondition Failed: the job declined to start because a declared
    # precondition was not met. The semantics line up exactly, and keeping it
    # distinct from 500 preserves the same distinction exit code 3 preserves —
    # "I refused" is not "I ran and threw".
    RunStatus.REFUSED: 412,
    RunStatus.FAILURE: 500,
    # 504 Gateway Timeout: the run exceeded its budget. Distinguished from a
    # plain 500 because it is the one failure a caller can sensibly retry.
    RunStatus.TIMEOUT: 504,
    RunStatus.CANCELLED: 500,
    RunStatus.UNKNOWN: 500,
}


# The outcome authority is `functualize._types.outcome`. This table stays here —
# every existing caller imports it from this module — but `outcome.py` re-exports
# it, and the *rules* about what a status means at a boundary live there, not
# beside the numbers. A new consumer should ask `outcome.is_failure(status,
# family=...)` rather than reading this dict.


def http_status_for_status(status: RunStatus) -> int:
    """The HTTP status code a finished run should be reported with.

    Args:
        status: The terminal :class:`RunStatus` of the run.

    Returns:
        The HTTP status code. Unmapped statuses — only ``RUNNING``, which is
        never observed at a request boundary — fall back to ``500`` rather
        than inventing a code.
    """
    return _STATUS_HTTP_CODES.get(status, 500)
