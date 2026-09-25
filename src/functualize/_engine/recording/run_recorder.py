"""The run recorder — lifecycle moments as run commands.

FUN-17/T9. ``JobExecutionEngine`` owns the twenty-step lifecycle; this module
is where two of its moments become persistence commands. Thin by contract
(``plan.md`` §3: turning a lifecycle moment into a command is *"thin; no
decisions of its own"*): every method takes the facts a moment observed and
returns the command value for it — no clock reads, no conditionals, no state
between calls.

The recorder is a translator, not a writer. It holds no transaction because
it cannot: a ``RuntimeTransaction`` surrounds one short transition and
commits on exit, while a recorder outlives them all. The executor opens the
transaction and issues what these methods return —
``tx.runs.start_attempt(recorder.started(...))`` — which is T11's wiring,
not this module's.

Mapping sources: ``contracts.md`` §1.2 fixes the command shapes and
``tasks.md`` T9 names the two moments. Nothing constructs these values
anywhere in the tree yet, so the mapping is derived from the contract, not
copied from a call site.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from functualize._types.persistence import FinishAttempt, StartAttempt

__all__ = ["RunRecorder"]


class RunRecorder:
    """Two lifecycle moments, as ``StartAttempt`` / ``FinishAttempt`` values."""

    def started(
        self,
        *,
        job: str,
        surface: str,
        now: datetime,
        scope_id: str | None = None,
        parent_run_id: str | None = None,
        invoke_depth: int = 0,
        args_hash: str | None = None,
    ) -> StartAttempt:
        """A run is opening — one transition that inserts the run and its
        first attempt.

        The store mints the identity, and ``args_hash`` is a hash, never the
        arguments: both are ``StartAttempt``'s own contract, restated here
        only so a caller of the moment does not have to re-read it.
        """
        return StartAttempt(
            job=job,
            surface=surface,
            now=now,
            scope_id=scope_id,
            parent_run_id=parent_run_id,
            invoke_depth=invoke_depth,
            args_hash=args_hash,
        )

    def finished(
        self,
        *,
        run_id: str,
        attempt_no: int,
        status: str,
        now: datetime,
        failure_code: str | None = None,
        failure_detail: Any = None,
    ) -> FinishAttempt:
        """An attempt ended, and the run's outcome with it when terminal.

        ``status`` is the engine's observation passed through, not a value
        derived here: which statuses exist and how a run's outcome follows
        its last attempt is lifecycle meaning (ADR-025), which is the
        engine's to own. A retry never rewrites a finished attempt — it
        starts the next one.
        """
        return FinishAttempt(
            run_id=run_id,
            attempt_no=attempt_no,
            status=status,
            now=now,
            failure_code=failure_code,
            failure_detail=failure_detail,
        )
