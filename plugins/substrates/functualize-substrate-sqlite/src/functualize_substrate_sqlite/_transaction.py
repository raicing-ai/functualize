"""The buffered transaction: writers stage statements, ``__exit__`` sends one batch.

A transaction surrounds one short transition and nothing else. Writers issue
no SQL of their own: each call appends statements here, and the whole list is
applied as one `driver.batch()` when the ``with`` block exits cleanly — and
discarded, with nothing applied, when it raises. That single batch is why the
store declares ``cross_aggregate_atomicity=True`` (one ``BEGIN IMMEDIATE …
COMMIT`` locally) while needing no interactive transaction (AC-5).

**Two guards, on purpose.** A writer *checks* its command when it is called —
fence, lifecycle edge, request status — against this unit's pending view (the
committed rows, overlaid with what the unit has already staged), and raises
the same errors the document store raises, before anything is buffered. Every
statement it stages then *carries* the same conditions in its predicate (the
held generation, the legal predecessor states), so a writer that slipped in
between the check and the commit makes the statement match zero rows: the
stale write cannot land (data model §5), it is only not reported.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from functualize._primitives.lease import StaleGenerationError

if TYPE_CHECKING:
    from functualize.plugin import (
        EffectWriter,
        EventWriter,
        InputWriter,
        RunWriter,
        WorkflowWriter,
    )
    from functualize_substrate_sqlite._driver import SqlDriver, Statement

__all__ = [
    "BufferedTransaction",
    "NotYetImplemented",
    "ScopeRow",
    "dumps",
    "iso",
    "parse_iso",
]


def iso(when: datetime) -> str:
    """A timestamp as stored: UTC, fixed width, so text order is time order.

    The lease predicate compares ``lease_expires_at <= :now`` as text; that is
    only chronological when every value has the same zone and precision.
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).isoformat(timespec="microseconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def dumps(value: Any) -> str | None:
    """An opaque payload as JSON text; ``None`` stays SQL ``NULL``.

    Strict: a value JSON cannot represent raises here, at the writer call,
    rather than being stored as something it was not.
    """
    return None if value is None else json.dumps(value, sort_keys=True)


@dataclass(frozen=True)
class ScopeRow:
    """What a writer needs to know about a scope before it stages a change."""

    exists: bool
    status: str = "running"
    generation: int = 0
    owner: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True)
class RequestRow:
    """An input request as this unit currently sees it."""

    scope_id: str
    gate_key: str
    status: str


class NotYetImplemented:
    """A port member whose SQL lands in a later task; refuses every use loudly.

    Stands in so the store satisfies its port from the moment boot can select
    it, and so a call that arrives early raises rather than doing nothing.
    """

    def __init__(self, member: str, task: str) -> None:
        self._member = member
        self._task = task

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError(
            f"SqliteRuntimeStore.{self._member}.{name} lands with {self._task}; "
            f"select the documents store until then."
        )


class BufferedTransaction:
    """The statements one transition stages, applied together or not at all."""

    def __init__(self, driver: SqlDriver, namespace: str) -> None:
        # The writers import this module's helpers; binding them here, not at
        # import time, is what keeps that one-directional.
        from functualize_substrate_sqlite._run_sql import (
            SqlEffectWriter,
            SqlEventWriter,
            SqlInputWriter,
            SqlRunWriter,
        )
        from functualize_substrate_sqlite._workflow_sql import SqlWorkflowWriter

        self.driver = driver
        self.namespace = namespace
        self._statements: list[Statement] = []
        self._scopes: dict[str, ScopeRow] = {}
        self._requests: dict[str, RequestRow] = {}
        self._runs: dict[str, str] = {}
        self._attempts: dict[tuple[str, int], str] = {}
        self._held_generations: dict[str, int] = {}
        #: Scopes this unit staged a write for, or claimed — where an event
        #: that names no run belongs, when there is exactly one.
        self.scopes_written: set[str] = set()
        self.runs: RunWriter = SqlRunWriter(self)
        self.workflows: WorkflowWriter = SqlWorkflowWriter(self)
        self.inputs: InputWriter = SqlInputWriter(self)
        self.events: EventWriter = SqlEventWriter(self)
        self.effects: EffectWriter = SqlEffectWriter(self)

    # -- staging ----------------------------------------------------

    def stage(self, sql: str, parameters: Sequence[object] = ()) -> None:
        """Append one statement to this transition's batch. Issues nothing."""
        self._statements.append((sql, tuple(parameters)))

    def commit(self, driver: SqlDriver) -> None:
        """Send everything staged as one batch; an empty transaction sends nothing."""
        if self._statements:
            driver.batch(self._statements)
        self._statements = []

    # -- the pending view: committed rows, overlaid by this unit ------

    def scope(self, scope_id: str) -> ScopeRow:
        if scope_id in self._scopes:
            return self._scopes[scope_id]
        rows = self.driver.query(
            "SELECT status, lease_generation, lease_owner, lease_expires_at "
            "FROM workflow_scopes WHERE namespace_id = ? AND id = ?",
            (self.namespace, scope_id),
        )
        if not rows:
            return ScopeRow(exists=False)
        status, generation, owner, expires = rows[0]
        return ScopeRow(True, str(status), int(generation), owner, expires)

    def update_scope(self, scope_id: str, **changes: Any) -> None:
        self._scopes[scope_id] = replace(self.scope(scope_id), exists=True, **changes)
        self.scopes_written.add(scope_id)

    def forget_scope(self, scope_id: str) -> None:
        """Drop the overlay for a scope whose row was just committed by a claim."""
        self._scopes.pop(scope_id, None)
        self.scopes_written.add(scope_id)

    def request(self, request_id: str) -> RequestRow | None:
        if request_id in self._requests:
            return self._requests[request_id]
        rows = self.driver.query(
            "SELECT scope_id, gate_key, status FROM input_requests "
            "WHERE namespace_id = ? AND id = ?",
            (self.namespace, request_id),
        )
        return RequestRow(*map(str, rows[0])) if rows else None

    def open_requests_for(
        self, scope_id: str, gate_key: str, statuses: Sequence[str]
    ) -> str | None:
        """The id of a request for this gate in one of ``statuses``, if any."""
        for request_id, row in self._requests.items():
            if (row.scope_id, row.gate_key) == (
                scope_id,
                gate_key,
            ) and row.status in statuses:
                return request_id
        marks = ", ".join("?" for _ in statuses)
        rows = self.driver.query(
            f"SELECT id FROM input_requests WHERE namespace_id = ? AND scope_id = ? "
            f"AND gate_key = ? AND status IN ({marks}) ORDER BY created_at DESC LIMIT 1",
            (self.namespace, scope_id, gate_key, *statuses),
        )
        return str(rows[0][0]) if rows else None

    def update_request(self, request_id: str, row: RequestRow) -> None:
        self._requests[request_id] = row
        self.scopes_written.add(row.scope_id)

    def run_status(self, run_id: str) -> str | None:
        if run_id in self._runs:
            return self._runs[run_id]
        rows = self.driver.query(
            "SELECT status FROM runs WHERE namespace_id = ? AND id = ?",
            (self.namespace, run_id),
        )
        return str(rows[0][0]) if rows else None

    def update_run(self, run_id: str, status: str) -> None:
        self._runs[run_id] = status

    def attempt_status(self, run_id: str, attempt_no: int) -> str | None:
        if (run_id, attempt_no) in self._attempts:
            return self._attempts[(run_id, attempt_no)]
        rows = self.driver.query(
            "SELECT status FROM run_attempts WHERE namespace_id = ? AND run_id = ? AND attempt_no = ?",
            (self.namespace, run_id, attempt_no),
        )
        return str(rows[0][0]) if rows else None

    def update_attempt(self, run_id: str, attempt_no: int, status: str) -> None:
        self._attempts[(run_id, attempt_no)] = status

    # -- the fence ----------------------------------------------------

    def require_fence(self, scope_id: str, generation: int) -> None:
        """Raise unless ``generation`` holds ``scope_id`` — the document store's refusal.

        Generation 0 fences nothing, as on the document store: leases count
        from 1, so 0 is "no generation held" — an unclaimed walk, or a forced
        cancel.
        """
        if generation <= 0:
            return
        row = self.scope(scope_id)
        if not row.exists or row.generation != generation:
            raise StaleGenerationError(
                scope_id,
                held=row.generation,
                offered=generation,
                owner=row.owner or "nobody",
            )
        self._held_generations[scope_id] = generation

    def held_generation(self, scope_id: str) -> int:
        """The generation this unit checked for a scoped transition, if any."""
        return self._held_generations.get(scope_id, 0)

    def fence_sql(
        self, scope_id: str, generation: int
    ) -> tuple[str, tuple[object, ...]]:
        """The fence as a predicate on a scope's child rows; ``1`` when unfenced."""
        if generation <= 0:
            return "1", ()
        return (
            "(SELECT lease_generation FROM workflow_scopes "
            "WHERE namespace_id = ? AND id = ?) = ?",
            (self.namespace, scope_id, generation),
        )

    def ensure_scope(self, scope_id: str, now: datetime) -> ScopeRow:
        """Stage the scope's row when it does not exist yet; return the pending row.

        As on the document store, a write to a scope nobody created makes it,
        ``running`` and unclaimed. The port carries no workflow name, so the
        column is empty until a later writer has one to give.
        """
        row = self.scope(scope_id)
        if not row.exists:
            self.stage(
                "INSERT INTO workflow_scopes (namespace_id, id, workflow, status, "
                "lease_generation, created_at, updated_at) "
                "VALUES (?, ?, '', 'running', 0, ?, ?) ON CONFLICT DO NOTHING",
                (self.namespace, scope_id, iso(now), iso(now)),
            )
            self.update_scope(scope_id)
            row = self.scope(scope_id)
        return row
