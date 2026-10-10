"""Run, input, event and effect writers over the relational schema.

Each stages into the unit's batch and returns ``None`` (`contracts.md` §1.3):

- **runs** — a run is opened with its first attempt in one transition; an
  attempt is finished in place or, for a retry, inserted beside the others.
  Attempts are never rewritten once terminal (``(run_id, attempt_no)`` is
  unique);
- **inputs** — candidates are appended, never replaced; a request accepts at
  most one answer, and consumption is a separate, fenced, idempotent write;
- **events** — ``seq`` is assigned in the statement, per run or per scope,
  so it is strictly increasing even for several events in one batch, and the
  tables refuse ``UPDATE`` by trigger;
- **effects** — an outbox row is recorded in the transition's own batch, so it
  exists exactly when the transition does. Dispatch is someone else's
  (FUN-21); recording is all that happens here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from functualize._primitives.run_store import new_run_id
from functualize._primitives.transitions import require_transition
from functualize._types.errors import InputRequestNotOpenError
from functualize._types.gate_resolution import EvaluationOutcome
from functualize._types.lifecycle import ATTEMPT, RUN
from functualize_substrate_sqlite._transaction import RequestRow, dumps, iso

if TYPE_CHECKING:
    from functualize._types.gate_resolution import GateCandidate
    from functualize.plugin import ConsumeInput, FinishAttempt, StartAttempt
    from functualize_substrate_sqlite._transaction import BufferedTransaction

__all__ = ["SqlEffectWriter", "SqlEventWriter", "SqlInputWriter", "SqlRunWriter"]

#: ``FinishAttempt`` carries one ``status`` for two machines whose vocabularies
#: differ (a run *succeeds* as ``success``, an attempt as ``succeeded``). The
#: engine may send either spelling; the other is derived by these tables, and a
#: value in neither is refused by the run machine.
_ATTEMPT_FOR_RUN = {
    "success": "succeeded",
    "failure": "failed",
    "timeout": "failed",
    "refused": "failed",
    "unknown": "failed",
    "cancelled": "cancelled",
    "skipped": "skipped",
}
_RUN_FOR_ATTEMPT = {
    "succeeded": "success",
    "failed": "failure",
    "cancelled": "cancelled",
    "skipped": "skipped",
}


def _statuses(status: str) -> tuple[str, str | None]:
    """``(run status, attempt status)`` for one ``FinishAttempt.status``.

    The attempt status is ``None`` when the run moves without its attempt
    ending — ``blocked`` at a gate, or ``running``.
    """
    value = status.lower()
    if value in _RUN_FOR_ATTEMPT and value not in _ATTEMPT_FOR_RUN:
        return _RUN_FOR_ATTEMPT[value], value
    return value, _ATTEMPT_FOR_RUN.get(value)


class SqlRunWriter:
    """`RunWriter` — the runs-and-attempts aggregate."""

    def __init__(self, tx: BufferedTransaction) -> None:
        self._tx = tx

    def start_attempt(self, cmd: StartAttempt) -> None:
        """Open the run and attempt 1. The store mints the run id; the port
        hands nothing back, as on the document store."""
        tx = self._tx
        run_id = new_run_id()
        run_status = require_transition(RUN, None, "running")
        attempt_status = require_transition(ATTEMPT, None, "running")
        tx.stage(
            "INSERT INTO runs (namespace_id, id, scope_id, parent_run_id, job, surface, "
            "status, args_hash, invoke_depth, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tx.namespace,
                run_id,
                cmd.scope_id,
                cmd.parent_run_id,
                cmd.job,
                cmd.surface,
                run_status,
                cmd.args_hash,
                cmd.invoke_depth,
                iso(cmd.now),
            ),
        )
        tx.stage(
            "INSERT INTO run_attempts (id, namespace_id, run_id, attempt_no, status, "
            "started_at) VALUES (?, ?, ?, 1, ?, ?)",
            (f"{run_id}#1", tx.namespace, run_id, attempt_status, iso(cmd.now)),
        )
        tx.update_run(run_id, run_status)
        tx.update_attempt(run_id, 1, attempt_status)

    def finish_attempt(self, cmd: FinishAttempt) -> None:
        """Settle one attempt and the run's status in the same batch.

        A run this store never opened is ignored, as on the document store:
        the record is an observation, and raising would turn a lost
        observation into a failed run.
        """
        tx = self._tx
        current_run = tx.run_status(cmd.run_id)
        if current_run is None:
            return
        run_target, attempt_target = _statuses(cmd.status)
        run_target = require_transition(RUN, current_run, run_target)
        if attempt_target is not None:
            self._finish(cmd, attempt_target)
        tx.stage(
            "UPDATE runs SET status = ?, ended_at = ? "
            "WHERE namespace_id = ? AND id = ? AND status = ?",
            (run_target, iso(cmd.now), tx.namespace, cmd.run_id, current_run),
        )
        tx.update_run(cmd.run_id, run_target)

    def _finish(self, cmd: FinishAttempt, target: str) -> None:
        tx = self._tx
        current = tx.attempt_status(cmd.run_id, cmd.attempt_no)
        if current is None:
            # A retry the store never saw open: opened and closed in one unit,
            # through both of the machine's edges.
            current = require_transition(ATTEMPT, None, "running")
            tx.stage(
                "INSERT INTO run_attempts (id, namespace_id, run_id, attempt_no, "
                "status, started_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"{cmd.run_id}#{cmd.attempt_no}",
                    tx.namespace,
                    cmd.run_id,
                    cmd.attempt_no,
                    current,
                    iso(cmd.now),
                ),
            )
        target = require_transition(ATTEMPT, current, target)
        tx.stage(
            "UPDATE run_attempts SET status = ?, ended_at = ?, failure_code = ?, "
            "failure_detail = ? WHERE namespace_id = ? AND run_id = ? "
            "AND attempt_no = ? AND status = ?",
            (
                target,
                iso(cmd.now),
                cmd.failure_code,
                dumps(cmd.failure_detail),
                tx.namespace,
                cmd.run_id,
                cmd.attempt_no,
                current,
            ),
        )
        tx.update_attempt(cmd.run_id, cmd.attempt_no, target)


class SqlInputWriter:
    """`InputWriter` — candidates appended, one accepted answer, fenced consumption."""

    def __init__(self, tx: BufferedTransaction) -> None:
        self._tx = tx

    def append(self, candidate: GateCandidate) -> None:
        """Record one candidate; refuse — with nothing applied — unless the request is open.

        One exception, as on the document store: the ``not_reached`` rungs
        behind an accepted candidate land, because they belong to the ladder
        that produced the answer and change nothing.
        """
        tx = self._tx
        request = tx.request(candidate.request_id)
        if request is None:
            raise InputRequestNotOpenError(candidate.request_id, "missing")
        outcome = candidate.evaluation.outcome
        tail = request.status == "accepted" and outcome is EvaluationOutcome.NOT_REACHED
        if request.status != "open" and not tail:
            raise InputRequestNotOpenError(candidate.request_id, request.status)
        evaluation = candidate.evaluation
        tx.stage(
            "INSERT INTO input_candidates (id, request_id, ordinal, source, outcome, "
            "detail, errors, payload, evidence, created_at) "
            "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM "
            "input_requests WHERE id = ? AND (status = 'open' OR (status = 'accepted' "
            "AND ? = 'not_reached')))",
            (
                candidate.candidate_id,
                candidate.request_id,
                candidate.ordinal,
                candidate.source,
                outcome.value,
                evaluation.detail,
                dumps([list(pair) for pair in evaluation.errors]),
                dumps(candidate.payload),
                dumps(dict(evaluation.evidence))
                if evaluation.evidence is not None
                else None,
                iso(candidate.submitted_at),
                candidate.request_id,
                outcome.value,
            ),
        )
        if outcome is EvaluationOutcome.ACCEPTED:
            tx.stage(
                "UPDATE input_requests SET status = 'accepted', resolved_at = ? "
                "WHERE id = ? AND status = 'open'",
                (iso(candidate.submitted_at), candidate.request_id),
            )
            tx.update_request(
                candidate.request_id,
                RequestRow(request.scope_id, request.gate_key, "accepted"),
            )
        else:
            tx.scopes_written.add(request.scope_id)

    def consume(self, cmd: ConsumeInput) -> None:
        """Retire the accepted answer the walk moved on; idempotent when consumed."""
        tx = self._tx
        tx.require_fence(cmd.scope_id, cmd.generation)
        request = tx.request(cmd.request_id)
        if request is None or request.scope_id != cmd.scope_id:
            raise ValueError(
                f"scope {cmd.scope_id!r} holds no request {cmd.request_id!r}"
            )
        if request.status == "consumed":
            return
        if request.status != "accepted":
            raise ValueError(
                f"request {cmd.request_id!r} is {request.status!r}, not accepted — "
                "nothing to consume"
            )
        fence, fence_args = tx.fence_sql(cmd.scope_id, cmd.generation)
        tx.stage(
            "UPDATE input_requests SET status = 'consumed' "
            f"WHERE id = ? AND status = 'accepted' AND {fence}",
            (cmd.request_id, *fence_args),
        )
        tx.update_request(
            cmd.request_id, RequestRow(request.scope_id, request.gate_key, "consumed")
        )


class SqlEventWriter:
    """`EventWriter` — the run's log when a run is named, else the unit's one scope."""

    def __init__(self, tx: BufferedTransaction) -> None:
        self._tx = tx

    def append(self, type: str, payload: Any = None, run_id: str | None = None) -> None:  # noqa: A002 — the port's name
        tx = self._tx
        now = iso(datetime.now(UTC))
        if run_id is not None:
            # An event for a run nobody opened lands nowhere, like the attempt
            # it would describe: the log is an observation.
            tx.stage(
                "INSERT INTO run_events (namespace_id, run_id, seq, type, payload, "
                "occurred_at) SELECT ?, ?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM "
                "run_events WHERE namespace_id = ? AND run_id = ?), ?, ?, ? "
                "WHERE EXISTS (SELECT 1 FROM runs WHERE namespace_id = ? AND id = ?)",
                (
                    tx.namespace,
                    run_id,
                    tx.namespace,
                    run_id,
                    type,
                    dumps(payload),
                    now,
                    tx.namespace,
                    run_id,
                ),
            )
            return
        if len(tx.scopes_written) != 1:
            raise ValueError(
                f"event {type!r} names no run and this transaction wrote "
                f"{sorted(tx.scopes_written)} — there is no single log it belongs to."
            )
        (scope_id,) = tx.scopes_written
        tx.stage(
            "INSERT INTO scope_events (namespace_id, scope_id, seq, type, payload, "
            "occurred_at) SELECT ?, ?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM "
            "scope_events WHERE namespace_id = ? AND scope_id = ?), ?, ?, ?",
            (tx.namespace, scope_id, tx.namespace, scope_id, type, dumps(payload), now),
        )


class SqlEffectWriter:
    """`EffectWriter` — an outbox row, committed with its transition or not at all.

    ``namespace`` on the port names the kind of aggregate the intent is about
    (``aggregate_type``); the row's own ``namespace_id`` is the store's. The
    aggregate is the scope this unit wrote when there is exactly one. A second
    intent with the same ``idempotency_key`` is the same intent, and records
    nothing new.
    """

    def __init__(self, tx: BufferedTransaction) -> None:
        self._tx = tx

    def append(
        self,
        namespace: str,
        topic: str,
        payload: Any = None,
        idempotency_key: str | None = None,
    ) -> None:
        tx = self._tx
        written = sorted(tx.scopes_written)
        aggregate = written[0] if len(written) == 1 else ""
        now = iso(datetime.now(UTC))
        # A takeover after the writer's pre-check can make its state/step
        # statement match zero rows. The intent must miss with it, not become
        # an outbox row for a transition that never happened.
        fence, fence_args = tx.fence_sql(aggregate, tx.held_generation(aggregate))
        tx.stage(
            "INSERT INTO outbox (id, namespace_id, aggregate_type, aggregate_id, topic, "
            "payload, idempotency_key, status, available_at) "
            f"SELECT ?, ?, ?, ?, ?, ?, ?, 'pending', ? WHERE {fence} "
            "ON CONFLICT DO NOTHING",
            (
                uuid4().hex,
                tx.namespace,
                namespace,
                aggregate,
                topic,
                dumps(payload),
                idempotency_key,
                now,
                *fence_args,
            ),
        )
