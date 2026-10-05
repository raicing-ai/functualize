"""`WorkflowWriter` over the relational schema — the workflow aggregate, written.

Every scope mutation carries the held generation in its predicate (I-3), so a
writer whose lease was taken over matches zero rows and the live value
survives; every status move is checked against the scope machine in
`_types/lifecycle.py` before it is staged (``IllegalTransition``) and guarded
by its legal predecessor states in the statement itself.

``claim`` is the one writer that commits on the spot — data model §5's
conditional update, one batch of its own, then a read — because it is the one
that answers with a value: losing is ``Conflict``, never an exception. The
lease rule is §5's: free when unclaimed or expired, re-takeable by its own
holder, and taken regardless on ``force``.

The engine decides what a transition *means* (ADR-025); this module only
records the status a command carries, which is why no branch here depends on
which command produced a status.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from functualize._primitives.lease import LeaseHeldError
from functualize._primitives.transitions import require_transition
from functualize._types.lifecycle import SCOPE
from functualize.plugin import (
    CancelWorkflow,
    Claimed,
    ClaimWorkflow,
    CompleteStep,
    Conflict,
    ResumeWorkflow,
    StateBatch,
    SuspendAtGate,
)
from functualize_substrate_sqlite._transaction import (
    RequestRow,
    dumps,
    iso,
    parse_iso,
)

if TYPE_CHECKING:
    from functualize_substrate_sqlite._transaction import BufferedTransaction

__all__ = ["SqlWorkflowWriter"]

#: A gate's request is reused, never reopened, while one of these is on record:
#: a re-entering walk keeps the id it first blocked with.
_LIVE_REQUEST = ("open", "accepted", "consumed")


def _predecessors(target: str) -> tuple[str, ...]:
    """The states the scope machine lets move to ``target``."""
    return tuple(
        sorted(c for c, t in SCOPE.transitions if t == target and c is not None)
    )


def _status_sql(target: str, now: datetime) -> tuple[str, tuple[object, ...]]:
    """``SET`` fragment for a status move, keeping ``terminal_at`` honest.

    ``terminal_at`` is the only record of when a scope stopped, so retention's
    age query depends on it: set on entering an evictable status (kept if the
    scope was already there), cleared when a retry re-enters ``running``.
    """
    if target in SCOPE.evictable:
        return "status = ?, terminal_at = COALESCE(terminal_at, ?)", (target, iso(now))
    if target == "running":
        return "status = ?, terminal_at = NULL", (target,)
    return "status = ?", (target,)


class _Keep:
    """Sentinel: leave ``position`` as it is (a cancel does not move the walk)."""


class SqlWorkflowWriter:
    """`WorkflowWriter` — stages into the unit's batch, except `claim`."""

    def __init__(self, tx: BufferedTransaction) -> None:
        self._tx = tx

    def claim(self, cmd: ClaimWorkflow) -> Claimed | Conflict:
        """Take the scope now — one conditional update — and answer with the outcome."""
        tx = self._tx
        now, expires = iso(cmd.now), iso(cmd.now + timedelta(seconds=cmd.lease_seconds))
        counts = tx.driver.batch(
            [
                (
                    "INSERT INTO workflow_scopes (namespace_id, id, workflow, status, "
                    "lease_generation, created_at, updated_at) "
                    "VALUES (?, ?, '', 'running', 0, ?, ?) ON CONFLICT DO NOTHING",
                    (tx.namespace, cmd.scope_id, now, now),
                ),
                (
                    "UPDATE workflow_scopes SET lease_owner = ?, lease_expires_at = ?, "
                    "lease_generation = lease_generation + 1, updated_at = ? "
                    "WHERE namespace_id = ? AND id = ? AND (? OR lease_owner = ? "
                    "OR lease_expires_at IS NULL OR lease_expires_at <= ?)",
                    (
                        cmd.owner,
                        expires,
                        now,
                        tx.namespace,
                        cmd.scope_id,
                        int(cmd.force),
                        cmd.owner,
                        now,
                    ),
                ),
            ]
        )
        tx.forget_scope(cmd.scope_id)
        row = tx.scope(cmd.scope_id)
        if counts[1] == 1:
            return Claimed(
                scope_id=cmd.scope_id,
                generation=row.generation,
                expires_at=parse_iso(row.expires_at or expires),
            )
        return Conflict(
            scope_id=cmd.scope_id,
            held_by=row.owner or "",
            held_generation=row.generation,
        )

    def complete_step(self, cmd: CompleteStep) -> None:
        tx = self._tx
        tx.require_fence(cmd.scope_id, cmd.generation)
        current = tx.ensure_scope(cmd.scope_id, cmd.now)
        target = require_transition(SCOPE, current.status, cmd.scope_status)
        fence, fence_args = tx.fence_sql(cmd.scope_id, cmd.generation)
        tx.stage(
            "INSERT INTO workflow_steps (namespace_id, scope_id, step_key, iteration, "
            "status, result, completed_at) "
            f"SELECT ?, ?, ?, ?, ?, ?, ? WHERE {fence} "
            "ON CONFLICT (namespace_id, scope_id, step_key, iteration) DO UPDATE SET "
            "status = excluded.status, result = excluded.result, "
            f"completed_at = excluded.completed_at WHERE {fence}",
            (
                tx.namespace,
                cmd.scope_id,
                cmd.step_key,
                cmd.iteration,
                cmd.status,
                dumps(cmd.result),
                iso(cmd.now),
                *fence_args,
                *fence_args,
            ),
        )
        if cmd.decision_key is not None and cmd.chosen_target is not None:
            # Immutable once written: the first evaluation is what replay reads.
            tx.stage(
                "INSERT INTO workflow_branches (namespace_id, scope_id, decision_key, "
                f"chosen_target, chosen_at) SELECT ?, ?, ?, ?, ? WHERE {fence} "
                "ON CONFLICT DO NOTHING",
                (
                    tx.namespace,
                    cmd.scope_id,
                    cmd.decision_key,
                    cmd.chosen_target,
                    iso(cmd.now),
                    *fence_args,
                ),
            )
        self._move(cmd.scope_id, cmd.generation, target, cmd.now, position=cmd.position)

    def suspend(self, cmd: SuspendAtGate) -> None:
        tx = self._tx
        tx.require_fence(cmd.scope_id, cmd.generation)
        current = tx.ensure_scope(cmd.scope_id, cmd.now)
        target = require_transition(SCOPE, current.status, cmd.scope_status)
        if tx.open_requests_for(cmd.scope_id, cmd.gate_name, _LIVE_REQUEST) is None:
            fence, fence_args = tx.fence_sql(cmd.scope_id, cmd.generation)
            live = ", ".join(f"'{s}'" for s in _LIVE_REQUEST)
            tx.stage(
                "INSERT INTO input_requests (id, namespace_id, scope_id, gate_key, "
                "generation, status, schema, prompt, created_at) "
                f"SELECT ?, ?, ?, ?, ?, 'open', ?, ?, ? WHERE {fence} AND NOT EXISTS ("
                "SELECT 1 FROM input_requests WHERE namespace_id = ? AND scope_id = ? "
                f"AND gate_key = ? AND status IN ({live}))",
                (
                    cmd.request_id,
                    tx.namespace,
                    cmd.scope_id,
                    cmd.gate_name,
                    cmd.generation,
                    dumps(cmd.schema),
                    dumps(cmd.prompt),
                    iso(cmd.now),
                    *fence_args,
                    tx.namespace,
                    cmd.scope_id,
                    cmd.gate_name,
                ),
            )
            tx.update_request(
                cmd.request_id, RequestRow(cmd.scope_id, cmd.gate_name, "open")
            )
        self._move(cmd.scope_id, cmd.generation, target, cmd.now, position=cmd.position)

    def resume(self, cmd: ResumeWorkflow) -> None:
        """Reclaim the scope at a new generation and set it running, in this unit.

        Consumption is not here: ``ConsumeInput`` is the one writer of
        ``consumed``. Losing the lease raises ``LeaseHeldError``, as on the
        document store — this writer returns ``None`` by the port, so there is
        no value to answer with.
        """
        tx = self._tx
        current = tx.ensure_scope(cmd.scope_id, cmd.now)
        now = iso(cmd.now)
        held = (
            current.owner is not None
            and current.owner != cmd.owner
            and current.expires_at is not None
            and current.expires_at > now
        )
        if held and not cmd.force:
            raise LeaseHeldError(
                cmd.scope_id, current.owner or "", current.expires_at or ""
            )
        target = require_transition(SCOPE, current.status, "running")
        expires = iso(cmd.now + timedelta(seconds=cmd.lease_seconds))
        status_set, status_args = _status_sql(target, cmd.now)
        marks = ", ".join("?" for _ in _predecessors(target))
        tx.stage(
            "UPDATE workflow_scopes SET lease_owner = ?, lease_expires_at = ?, "
            f"lease_generation = lease_generation + 1, updated_at = ?, {status_set} "
            "WHERE namespace_id = ? AND id = ? AND (? OR lease_owner = ? "
            "OR lease_expires_at IS NULL OR lease_expires_at <= ?) "
            f"AND status IN ({marks})",
            (
                cmd.owner,
                expires,
                now,
                *status_args,
                tx.namespace,
                cmd.scope_id,
                int(cmd.force),
                cmd.owner,
                now,
                *_predecessors(target),
            ),
        )
        tx.update_scope(
            cmd.scope_id,
            status=target,
            generation=current.generation + 1,
            owner=cmd.owner,
            expires_at=expires,
        )

    def cancel(self, cmd: CancelWorkflow) -> None:
        """Move a non-terminal scope to ``cancelled``: the holder, or ``force``."""
        tx = self._tx
        generation = 0 if cmd.force else cmd.generation
        tx.require_fence(cmd.scope_id, generation)
        current = tx.ensure_scope(cmd.scope_id, cmd.now)
        target = require_transition(SCOPE, current.status, "cancelled")
        self._move(cmd.scope_id, generation, target, cmd.now)
        fence, fence_args = tx.fence_sql(cmd.scope_id, generation)
        # Recorded only if the move above landed, so a cancel that lost a race
        # leaves no event claiming it happened.
        tx.stage(
            "INSERT INTO scope_events (namespace_id, scope_id, seq, type, payload, "
            "occurred_at) SELECT ?, ?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM "
            "scope_events WHERE namespace_id = ? AND scope_id = ?), "
            "'workflow.cancelled', ?, ? WHERE EXISTS (SELECT 1 FROM workflow_scopes "
            f"WHERE namespace_id = ? AND id = ? AND status = 'cancelled') AND {fence}",
            (
                tx.namespace,
                cmd.scope_id,
                tx.namespace,
                cmd.scope_id,
                dumps({"reason": cmd.reason} if cmd.reason else None),
                iso(cmd.now),
                tx.namespace,
                cmd.scope_id,
                *fence_args,
            ),
        )

    def write_state(self, cmd: StateBatch) -> None:
        """Upsert and delete state keys; each statement carries the fence."""
        tx = self._tx
        tx.require_fence(cmd.scope_id, cmd.generation)
        tx.ensure_scope(cmd.scope_id, cmd.now)
        fence, fence_args = tx.fence_sql(cmd.scope_id, cmd.generation)
        for key, value in cmd.upserts.items():
            tx.stage(
                "INSERT INTO scope_state (namespace_id, scope_id, key, value, version, "
                f"updated_at) SELECT ?, ?, ?, ?, 1, ? WHERE {fence} "
                "ON CONFLICT (namespace_id, scope_id, key) DO UPDATE SET "
                "value = excluded.value, version = version + 1, "
                f"updated_at = excluded.updated_at WHERE {fence}",
                (
                    tx.namespace,
                    cmd.scope_id,
                    key,
                    dumps(value),
                    iso(cmd.now),
                    *fence_args,
                    *fence_args,
                ),
            )
        for key in cmd.deletes:
            tx.stage(
                "DELETE FROM scope_state WHERE namespace_id = ? AND scope_id = ? "
                f"AND key = ? AND {fence}",
                (tx.namespace, cmd.scope_id, key, *fence_args),
            )
        tx.update_scope(cmd.scope_id)

    def _move(
        self,
        scope_id: str,
        generation: int,
        target: str,
        now: datetime,
        *,
        position: str | None | type[_Keep] = _Keep,
    ) -> None:
        """Stage the scope row's status move, fenced and predecessor-guarded."""
        tx = self._tx
        status_set, status_args = _status_sql(target, now)
        sets, args = [status_set, "updated_at = ?"], [*status_args, iso(now)]
        if position is not _Keep:
            sets.append("position = ?")
            args.append(position)
        predecessors = _predecessors(target)
        marks = ", ".join("?" for _ in predecessors)
        fence = " AND lease_generation = ?" if generation > 0 else ""
        tx.stage(
            f"UPDATE workflow_scopes SET {', '.join(sets)} "
            f"WHERE namespace_id = ? AND id = ? AND status IN ({marks}){fence}",
            (
                *args,
                tx.namespace,
                scope_id,
                *predecessors,
                *((generation,) if generation > 0 else ()),
            ),
        )
        tx.update_scope(scope_id, status=target)
