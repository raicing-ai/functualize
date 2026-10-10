"""The legacy runtime documents, read, judged and turned into relational rows.

The source is the ``documents(key, payload, revision)`` table that installing
this plugin used to fill (shape M-2): the ``runs`` envelope, the ``scopes``
envelope and one ``scope-state/<id>`` document per scope. They are read through
the framework's own document stores over a `SQLiteSubstrate` on a **snapshot**
of the file — so the importer interprets every record exactly as the engine
that wrote it did, and nothing it reads can touch the source.

Legality is FUN-18's (`_types/lifecycle.py`): a status outside its machine, or
a terminal scope still holding a live lease (the B4 symptom), is a refused
record. One refused record refuses the whole import; every one is listed.

Each legacy run becomes one attempt, ``attempt_no = 1`` (shape M-1).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from functualize._primitives.gate_requests import _request_id, _status
from functualize._primitives.run_store import RunStore
from functualize._primitives.scope_store import ScopeStore
from functualize._types.lifecycle import INPUT_REQUEST, RUN, SCOPE
from functualize_substrate_sqlite._transaction import dumps, iso
from functualize_substrate_sqlite.substrate import SQLiteSubstrate

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from functualize_substrate_sqlite._driver import Statement

__all__ = ["LegacySnapshot", "Refusal", "collisions", "read_snapshot"]

#: An attempt's status for each run status; a run still open has its attempt open.
_ATTEMPT_FOR_RUN = {
    "success": "succeeded",
    "failure": "failed",
    "timeout": "failed",
    "refused": "failed",
    "unknown": "failed",
    "cancelled": "cancelled",
    "skipped": "skipped",
    "running": "running",
    "blocked": "running",
}

#: Where a legacy deposit's answer goes when no candidate recorded it.
LEGACY_SOURCE = "legacy-import"


@dataclass(frozen=True)
class Refusal:
    """One record the import will not carry, and why."""

    kind: str
    record: str
    reason: str

    def __str__(self) -> str:
        return f"{self.kind} {self.record}: {self.reason}"


@dataclass
class LegacySnapshot:
    """Everything runtime in the legacy documents, as rows and as a manifest."""

    namespace: str
    imported_at: str
    rows: list[Statement] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    scope_ids: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    request_ids: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    synthesized_candidates: int = 0

    @property
    def digest(self) -> str:
        """One digest of everything imported: identities, statuses, payloads."""
        text = json.dumps(self.manifest, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dict(value: Any) -> dict[str, Any]:
    """A legacy sub-record, or an empty one when it is absent or not a mapping."""
    return value if isinstance(value, dict) else {}


def _when(value: Any, fallback: str | None) -> str | None:
    """A legacy timestamp in the store's format; ``fallback`` when absent or junk."""
    if not isinstance(value, str) or not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return fallback
    return iso(parsed)


def _digest(value: Any) -> str:
    return hashlib.sha256((dumps(value) or "null").encode("utf-8")).hexdigest()


def read_snapshot(
    snapshot: Path, namespace: str, now: datetime | None = None
) -> LegacySnapshot:
    """Read the snapshot's runtime documents into rows, refusals and a manifest."""
    moment = iso(now or datetime.now(UTC))
    out = LegacySnapshot(namespace=namespace, imported_at=moment)
    substrate = SQLiteSubstrate(snapshot)
    scopes, runs = ScopeStore(substrate), RunStore(substrate)
    out.rows.append(
        (
            "INSERT INTO namespaces (id, project_key, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT DO NOTHING",
            (namespace, namespace, moment),
        )
    )
    for scope_id in sorted(scopes.scope_ids()):
        record = scopes.get_scope(scope_id) or {}
        _scope(out, scopes, scope_id, record)
    for run_id in sorted(runs.run_ids()):
        record = runs.get_run(run_id) or {}
        _run(out, run_id, record, runs.events_for(run_id))
    return out


def _scope(
    out: LegacySnapshot, scopes: ScopeStore, scope_id: str, record: dict[str, Any]
) -> None:
    ns, now = out.namespace, out.imported_at
    status = str(record.get("status") or "running")
    lease = _dict(record.get("lease"))
    expires = _when(lease.get("expires_at"), None)
    if status not in SCOPE.states:
        out.refusals.append(
            Refusal("scope", scope_id, f"status {status!r} is not a scope state")
        )
    elif status in SCOPE.evictable and expires is not None and expires > now:
        out.refusals.append(
            Refusal(
                "scope",
                scope_id,
                f"{status!r} yet holding a live lease ({lease.get('owner')!r} until "
                f"{expires}) — a terminal scope cannot be held",
            )
        )
    generation = int(lease.get("generation") or 0)
    out.scope_ids.append(scope_id)
    out.rows.append(
        (
            "INSERT INTO workflow_scopes (namespace_id, id, workflow, graph_digest, status, "
            "position, lease_owner, lease_expires_at, lease_generation, created_at, "
            "updated_at, terminal_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ns,
                scope_id,
                str(record.get("workflow") or ""),
                record.get("graph_digest"),
                status,
                record.get("position"),
                lease.get("owner"),
                expires,
                generation,
                _when(record.get("created_at"), now),
                _when(record.get("updated_at"), now),
                _when(record.get("terminal_at"), now)
                if status in SCOPE.evictable
                else None,
            ),
        )
    )
    steps = _dict(record.get("steps"))
    for step_key, step in sorted(steps.items()):
        step = step if isinstance(step, dict) else {}
        out.rows.append(
            (
                "INSERT INTO workflow_steps (namespace_id, scope_id, step_key, iteration, "
                "status, result, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ns,
                    scope_id,
                    step_key,
                    int(step.get("iteration") or 0),
                    str(step.get("status") or "success"),
                    dumps(step.get("result")),
                    _when(step.get("at"), None),
                ),
            )
        )
    branches = _dict(record.get("branches"))
    for decision, target in sorted(branches.items()):
        out.rows.append(
            (
                "INSERT INTO workflow_branches (namespace_id, scope_id, decision_key, "
                "chosen_target, chosen_at) VALUES (?, ?, ?, ?, ?)",
                (ns, scope_id, decision, str(target), now),
            )
        )
    state = scopes.state_snapshot(scope_id)
    for key, value in sorted(state.items()):
        out.rows.append(
            (
                "INSERT INTO scope_state (namespace_id, scope_id, key, value, version, "
                "updated_at) VALUES (?, ?, ?, ?, 1, ?)",
                (ns, scope_id, key, dumps(value), now),
            )
        )
    events = _sequenced(record.get("events"))
    for seq, event in events:
        out.rows.append(
            (
                "INSERT INTO scope_events (namespace_id, scope_id, seq, type, payload, "
                "occurred_at, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ns,
                    scope_id,
                    seq,
                    str(event.get("type") or ""),
                    dumps(event.get("payload")),
                    _when(event.get("at"), now),
                    event.get("run_id"),
                ),
            )
        )
    gates = _dict(record.get("gates"))
    requests: dict[str, str] = {}
    for gate_name, gate in sorted(gates.items()):
        if isinstance(gate, dict):
            for archived in gate.get("superseded") or ():
                if isinstance(archived, dict):
                    requests.update(
                        _request(
                            out, scope_id, gate_name, archived, generation, "cancelled"
                        )
                    )
            requests.update(_request(out, scope_id, gate_name, gate, generation, None))
    out.manifest[f"scope:{scope_id}"] = {
        "status": status,
        "position": record.get("position"),
        "generation": generation,
        "owner": lease.get("owner"),
        "steps": {
            k: _digest(v.get("result") if isinstance(v, dict) else None)
            for k, v in steps.items()
        },
        "branches": dict(branches),
        "state": {k: _digest(v) for k, v in state.items()},
        "events": [
            [seq, str(e.get("type") or ""), _digest(e.get("payload"))]
            for seq, e in events
        ],
        "requests": requests,
    }


def _request(
    out: LegacySnapshot,
    scope_id: str,
    gate_name: str,
    gate: dict[str, Any],
    generation: int,
    forced_status: str | None,
) -> dict[str, str]:
    now = out.imported_at
    request_id = _request_id(scope_id, gate_name, gate)
    status = forced_status or _status(gate)
    if status not in INPUT_REQUEST.states:
        out.refusals.append(
            Refusal("request", request_id, f"status {status!r} is not a request state")
        )
    out.request_ids.append(request_id)
    out.rows.append(
        (
            "INSERT INTO input_requests (id, namespace_id, scope_id, gate_key, generation, "
            "status, schema, prompt, created_at, resolved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request_id,
                out.namespace,
                scope_id,
                gate_name,
                generation,
                status,
                dumps(gate.get("input_schema")),
                dumps(gate.get("prompt")),
                _when(gate.get("blocked_at"), now),
                _when(gate.get("consumed_at"), None),
            ),
        )
    )
    candidates = [c for c in gate.get("candidates") or () if isinstance(c, dict)]
    if (
        not candidates
        and status in ("accepted", "consumed")
        and gate.get("payload") is not None
    ):
        # A legacy deposit holds its answer as a bare payload; carried as the
        # one accepted candidate it was, so replay reads it the same way.
        candidates = [
            {
                "candidate_id": f"{request_id}#legacy",
                "ordinal": 0,
                "source": LEGACY_SOURCE,
                "outcome": "accepted",
                "payload": gate.get("payload"),
                "submitted_at": gate.get("blocked_at"),
            }
        ]
        out.synthesized_candidates += 1
    for candidate in candidates:
        out.rows.append(
            (
                "INSERT INTO input_candidates (id, request_id, ordinal, source, outcome, detail, "
                "errors, payload, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(candidate.get("candidate_id")),
                    request_id,
                    int(candidate.get("ordinal") or 0),
                    candidate.get("source"),
                    str(candidate.get("outcome") or "accepted"),
                    candidate.get("detail"),
                    dumps(candidate.get("errors") or []),
                    dumps(candidate.get("payload")),
                    dumps(candidate.get("evidence")),
                    _when(candidate.get("submitted_at"), now),
                ),
            )
        )
    return {request_id: status}


def _run(
    out: LegacySnapshot,
    run_id: str,
    record: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    ns, now = out.namespace, out.imported_at
    status = str(record.get("status") or "running").lower()
    started = _when(record.get("started_at"), None)
    if status not in RUN.states:
        out.refusals.append(
            Refusal("run", run_id, f"status {status!r} is not a run state")
        )
    if started is None:
        out.refusals.append(Refusal("run", run_id, "no readable started_at"))
    ended = _when(record.get("ended_at"), None)
    out.run_ids.append(run_id)
    out.rows.append(
        (
            "INSERT INTO runs (namespace_id, id, scope_id, parent_run_id, job, surface, status, "
            "args_hash, invoke_depth, started_at, ended_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ns,
                run_id,
                record.get("scope_id"),
                record.get("parent_run_id"),
                str(record.get("job") or ""),
                record.get("surface"),
                status,
                record.get("args_hash"),
                int(record.get("invoke_depth") or 0),
                started or now,
                ended,
            ),
        )
    )
    out.rows.append(
        (
            "INSERT INTO run_attempts (id, namespace_id, run_id, attempt_no, status, started_at, "
            "ended_at, failure_code) VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
            (
                f"{run_id}#1",
                ns,
                run_id,
                _ATTEMPT_FOR_RUN.get(status, "failed"),
                started or now,
                ended,
                record.get("failure_code"),
            ),
        )
    )
    sequenced = _sequenced(events)
    for seq, event in sequenced:
        out.rows.append(
            (
                "INSERT INTO run_events (namespace_id, run_id, seq, type, payload, occurred_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ns,
                    run_id,
                    seq,
                    str(event.get("type") or ""),
                    dumps(event.get("payload")),
                    _when(event.get("at"), now),
                ),
            )
        )
    out.manifest[f"run:{run_id}"] = {
        "status": status,
        "job": str(record.get("job") or ""),
        "scope_id": record.get("scope_id"),
        "parent_run_id": record.get("parent_run_id"),
        "events": [
            [seq, str(e.get("type") or ""), _digest(e.get("payload"))]
            for seq, e in sequenced
        ],
    }


def _sequenced(events: Any) -> list[tuple[int, dict[str, Any]]]:
    """Events in ``seq`` order; one without a number takes the next free one."""
    entries = [e for e in (events or ()) if isinstance(e, dict)]
    out: list[tuple[int, dict[str, Any]]] = []
    last = 0
    for entry in sorted(entries, key=lambda e: int(e.get("seq") or 0)):
        seq = int(entry.get("seq") or 0)
        seq = seq if seq > last else last + 1
        out.append((seq, entry))
        last = seq
    return out


class _Reads(Protocol):
    def query(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> list[tuple[Any, ...]]: ...


def collisions(driver: _Reads, snapshot: LegacySnapshot) -> list[Refusal]:
    """Legacy identities the relational store already holds — never overwritten."""
    found: list[Refusal] = []
    for table, kind, ids in (
        ("workflow_scopes", "scope", snapshot.scope_ids),
        ("runs", "run", snapshot.run_ids),
    ):
        for identity in ids:
            if driver.query(
                f"SELECT 1 FROM {table} WHERE namespace_id = ? AND id = ?",
                (snapshot.namespace, identity),
            ):
                found.append(
                    Refusal(kind, identity, "already present in the relational store")
                )
    return found
