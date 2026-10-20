"""Question-shaped readers over the relational runtime tables."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    EvidenceRef,
    GateCandidate,
    GateDecision,
)
from functualize.plugin import (
    EventView,
    InputRequest,
    RunQuery,
    RunTree,
    RunView,
    StepView,
    WorkflowQuery,
    WorkflowView,
)
from functualize_substrate_sqlite._transaction import parse_iso

if TYPE_CHECKING:
    from functualize_substrate_sqlite._driver import SqlDriver

__all__ = ["SqlInputReader", "SqlRunReader", "SqlWorkflowReader"]


def _json(value: str | None) -> Any:
    return None if value is None else json.loads(value)


def _time(value: str | None) -> datetime | None:
    return None if value is None else parse_iso(value)


class SqlRunReader:
    """Runs, newest-first history, and nested invocation trees."""

    _COLUMNS = (
        "id, job, surface, status, started_at, scope_id, parent_run_id, "
        "invoke_depth, args_hash, ended_at"
    )

    def __init__(self, driver: SqlDriver, namespace: str) -> None:
        self._driver = driver
        self._namespace = namespace

    @staticmethod
    def _view(row: tuple[Any, ...]) -> RunView:
        return RunView(
            run_id=row[0],
            job=row[1],
            surface=row[2] or "",
            status=row[3],
            started_at=parse_iso(row[4]),
            scope_id=row[5],
            parent_run_id=row[6],
            invoke_depth=row[7],
            args_hash=row[8],
            ended_at=_time(row[9]),
        )

    def run(self, run_id: str) -> RunView | None:
        rows = self._driver.query(
            f"SELECT {self._COLUMNS} FROM runs WHERE namespace_id = ? AND id = ?",
            (self._namespace, run_id),
        )
        return self._view(rows[0]) if rows else None

    def recent(self, query: RunQuery) -> tuple[RunView, ...]:
        clauses = ["namespace_id = ?"]
        args: list[object] = [self._namespace]
        for column, value in (
            ("job", query.job),
            ("status", query.status),
            ("scope_id", query.scope_id),
            ("parent_run_id", query.parent_run_id),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                args.append(value)
        limit = 20 if query.limit is None else max(0, query.limit)
        rows = self._driver.query(
            f"SELECT {self._COLUMNS} FROM runs WHERE {' AND '.join(clauses)} "
            "ORDER BY started_at DESC, id DESC LIMIT ?",
            (*args, limit),
        )
        return tuple(map(self._view, rows))

    def tree(self, root_run_id: str) -> RunTree:
        root = self.run(root_run_id)
        if root is None:
            raise KeyError(root_run_id)
        seen = {root_run_id}

        def build(run: RunView) -> RunTree:
            children = []
            rows = self._driver.query(
                f"SELECT {self._COLUMNS} FROM runs "
                "WHERE namespace_id = ? AND parent_run_id = ? "
                "ORDER BY started_at, id",
                (self._namespace, run.run_id),
            )
            for row in rows:
                child = self._view(row)
                if child.run_id not in seen:
                    seen.add(child.run_id)
                    children.append(build(child))
            return RunTree(run, tuple(children))

        return build(root)


class SqlWorkflowReader:
    """Scope status, resumable views, and events after a sequence number."""

    _COLUMNS = (
        "id, workflow, status, position, lease_generation, lease_owner, "
        "lease_expires_at, created_at, updated_at, terminal_at, graph_digest"
    )

    def __init__(self, driver: SqlDriver, namespace: str) -> None:
        self._driver = driver
        self._namespace = namespace

    @staticmethod
    def _view(row: tuple[Any, ...]) -> WorkflowView:
        return WorkflowView(
            scope_id=row[0],
            workflow=row[1],
            status=row[2],
            position=row[3],
            generation=row[4] or None,
            owner=row[5],
            expires_at=_time(row[6]),
            created_at=_time(row[7]),
            updated_at=_time(row[8]),
            terminal_at=_time(row[9]),
            graph_digest=row[10],
        )

    def workflow(self, scope_id: str) -> WorkflowView | None:
        rows = self._driver.query(
            f"SELECT {self._COLUMNS} FROM workflow_scopes "
            "WHERE namespace_id = ? AND id = ?",
            (self._namespace, scope_id),
        )
        return self._view(rows[0]) if rows else None

    def resumable(self, query: WorkflowQuery) -> tuple[WorkflowView, ...]:
        clauses = ["namespace_id = ?"]
        args: list[object] = [self._namespace]
        for column, value in (("status", query.status), ("workflow", query.workflow)):
            if value is not None:
                clauses.append(f"{column} = ?")
                args.append(value)
        sql = (
            f"SELECT {self._COLUMNS} FROM workflow_scopes WHERE {' AND '.join(clauses)}"
        )
        sql += " ORDER BY updated_at DESC, id DESC"
        if query.limit is not None:
            sql += " LIMIT ?"
            args.append(max(0, query.limit))
        return tuple(self._view(row) for row in self._driver.query(sql, args))

    def events_after(self, scope_id: str, seq: int) -> tuple[EventView, ...]:
        rows = self._driver.query(
            "SELECT seq, type, occurred_at, payload, run_id FROM scope_events "
            "WHERE namespace_id = ? AND scope_id = ? AND seq > ? ORDER BY seq",
            (self._namespace, scope_id, seq),
        )
        return tuple(
            EventView(row[0], row[1], parse_iso(row[2]), _json(row[3]), row[4])
            for row in rows
        )

    _STEP_COLUMNS = (
        "step_key, iteration, status, result, reusable, result_kind, "
        "result_type, inputs, effecting, completed_at"
    )

    @staticmethod
    def _step(scope_id: str, row: tuple[Any, ...]) -> StepView:
        return StepView(
            scope_id=scope_id,
            step_key=row[0],
            iteration=row[1],
            status=row[2],
            result=_json(row[3]),
            reusable=bool(row[4]),
            result_kind=row[5],
            result_type=row[6],
            inputs=_json(row[7]),
            effecting=bool(row[8]),
            completed_at=_time(row[9]),
        )

    def step(self, scope_id: str, step_key: str, iteration: int = 0) -> StepView | None:
        rows = self._driver.query(
            f"SELECT {self._STEP_COLUMNS} FROM workflow_steps "
            "WHERE namespace_id = ? AND scope_id = ? AND step_key = ? "
            "AND iteration = ?",
            (self._namespace, scope_id, step_key, iteration),
        )
        return self._step(scope_id, rows[0]) if rows else None

    def steps(self, scope_id: str) -> tuple[StepView, ...]:
        rows = self._driver.query(
            f"SELECT {self._STEP_COLUMNS} FROM workflow_steps "
            "WHERE namespace_id = ? AND scope_id = ? "
            "ORDER BY completed_at, step_key, iteration",
            (self._namespace, scope_id),
        )
        return tuple(self._step(scope_id, row) for row in rows)

    def branch(self, scope_id: str, decision_key: str) -> str | None:
        rows = self._driver.query(
            "SELECT chosen_target FROM workflow_branches "
            "WHERE namespace_id = ? AND scope_id = ? AND decision_key = ?",
            (self._namespace, scope_id, decision_key),
        )
        return str(rows[0][0]) if rows else None

    def state(self, scope_id: str) -> dict[str, Any]:
        rows = self._driver.query(
            "SELECT key, value FROM scope_state "
            "WHERE namespace_id = ? AND scope_id = ?",
            (self._namespace, scope_id),
        )
        return {str(key): _json(value) for key, value in rows}


class SqlInputReader:
    """Open requests, workspace-wide waiting, and recorded candidates."""

    _COLUMNS = (
        "id, scope_id, gate_key, generation, status, created_at, schema, prompt, "
        "resolved_at, run_id, position"
    )

    def __init__(self, driver: SqlDriver, namespace: str) -> None:
        self._driver = driver
        self._namespace = namespace

    @staticmethod
    def _view(row: tuple[Any, ...]) -> InputRequest:
        return InputRequest(
            request_id=row[0],
            scope_id=row[1],
            gate_name=row[2],
            generation=row[3],
            status=row[4],
            created_at=parse_iso(row[5]),
            schema=_json(row[6]),
            prompt=_json(row[7]),
            resolved_at=_time(row[8]),
            run_id=row[9],
            position=row[10],
        )

    def open_for(self, scope_id: str) -> InputRequest | None:
        rows = self._driver.query(
            f"SELECT {self._COLUMNS} FROM input_requests WHERE namespace_id = ? "
            "AND scope_id = ? AND status IN ('open', 'accepted') "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (self._namespace, scope_id),
        )
        return self._view(rows[0]) if rows else None

    def awaiting(self) -> tuple[InputRequest, ...]:
        rows = self._driver.query(
            f"SELECT {self._COLUMNS} FROM input_requests WHERE namespace_id = ? "
            "AND status = 'open' ORDER BY created_at, id",
            (self._namespace,),
        )
        return tuple(map(self._view, rows))

    def request(self, request_id: str) -> InputRequest | None:
        rows = self._driver.query(
            f"SELECT {self._COLUMNS} FROM input_requests WHERE namespace_id = ? AND id = ?",
            (self._namespace, request_id),
        )
        return self._view(rows[0]) if rows else None

    def for_gate(self, scope_id: str, gate_name: str) -> InputRequest | None:
        """The newest request on this scope's gate, whatever its status."""
        rows = self._driver.query(
            f"SELECT {self._COLUMNS} FROM input_requests "
            "WHERE namespace_id = ? AND scope_id = ? AND gate_key = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (self._namespace, scope_id, gate_name),
        )
        return self._view(rows[0]) if rows else None

    # TRANSITIONAL(FUN-21): removed with the legacy deposit path (ruling R-1).
    def deposited_answer(self, scope_id: str, gate_name: str) -> Any | None:
        """Always None: this store has no legacy deposit path.

        Its importer turns a legacy deposit into the one accepted candidate
        it was (`"{request_id}#legacy"`), and that candidate is what replay
        reads — so there is no bare payload here for a reader to find.
        Returning None is a fact about this store, not a degradation.
        """
        del scope_id, gate_name
        return None

    def candidates_for(self, request_id: str) -> tuple[GateCandidate, ...]:
        rows = self._driver.query(
            "SELECT c.id, c.ordinal, c.source, c.outcome, c.detail, c.errors, "
            "c.payload, c.evidence, c.created_at, c.resolver_class, c.channel, "
            "c.schema_id, c.schema_version, c.payload_hash, "
            "c.supersedes_candidate_id FROM input_candidates AS c "
            "JOIN input_requests AS r ON r.id = c.request_id "
            "WHERE r.namespace_id = ? AND c.request_id = ? ORDER BY c.ordinal",
            (self._namespace, request_id),
        )
        evidence = self._evidence(request_id)
        return tuple(
            GateCandidate(
                candidate_id=row[0],
                request_id=request_id,
                ordinal=row[1],
                source=row[2] or "",
                submitted_at=parse_iso(row[8]),
                evaluation=CandidateEvaluation(
                    outcome=EvaluationOutcome(row[3]),
                    detail=row[4] or "",
                    errors=tuple(tuple(pair) for pair in (_json(row[5]) or ())),
                    evidence=_json(row[7]),
                ),
                payload=_json(row[6]),
                resolver_class=row[9] or "",
                channel=row[10] or "",
                schema_id=row[11] or "",
                schema_version=row[12] or "",
                payload_hash=row[13] or "",
                supersedes_candidate_id=row[14],
                evidence_refs=evidence.get(row[0], ()),
            )
            for row in rows
        )

    def _evidence(self, request_id: str) -> dict[str, tuple[EvidenceRef, ...]]:
        """Every evidence reference on the request's candidates, by candidate."""
        rows = self._driver.query(
            "SELECT a.candidate_id, a.uri, a.digest, a.media_type, a.size "
            "FROM artifact_refs AS a JOIN input_candidates AS c "
            "ON c.id = a.candidate_id WHERE a.namespace_id = ? AND "
            "c.request_id = ? AND a.kind = 'gate-evidence' ORDER BY a.id",
            (self._namespace, request_id),
        )
        found: dict[str, list[EvidenceRef]] = {}
        for candidate_id, uri, digest, media_type, size in rows:
            found.setdefault(candidate_id, []).append(
                EvidenceRef(
                    ref=uri, digest=digest or "", media_type=media_type, size=size
                )
            )
        return {key: tuple(value) for key, value in found.items()}

    def decision(self, request_id: str) -> GateDecision | None:
        rows = self._driver.query(
            "SELECT d.accepted_id, d.policy_id, d.policy_version, d.decided_at "
            "FROM input_decisions AS d JOIN input_requests AS r "
            "ON r.id = d.request_id WHERE r.namespace_id = ? AND d.request_id = ?",
            (self._namespace, request_id),
        )
        if not rows:
            return None
        accepted_id, policy_id, policy_version, decided_at = rows[0]
        observed = self._driver.query(
            "SELECT candidate_id FROM input_decision_observations "
            "WHERE request_id = ? ORDER BY position",
            (request_id,),
        )
        return GateDecision(
            request_id=request_id,
            accepted_id=accepted_id,
            policy_id=policy_id,
            policy_version=policy_version,
            observed_candidate_ids=tuple(row[0] for row in observed),
            decided_at=parse_iso(decided_at),
        )
