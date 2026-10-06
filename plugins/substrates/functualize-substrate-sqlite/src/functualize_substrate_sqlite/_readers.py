"""Question-shaped readers over the relational runtime tables."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
)
from functualize.plugin import (
    EventView,
    InputRequest,
    RunQuery,
    RunTree,
    RunView,
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
        "lease_expires_at, created_at, updated_at, terminal_at"
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


class SqlInputReader:
    """Open requests, workspace-wide waiting, and recorded candidates."""

    _COLUMNS = "id, scope_id, gate_key, generation, status, created_at, schema, prompt, resolved_at"

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

    def candidates_for(self, request_id: str) -> tuple[GateCandidate, ...]:
        rows = self._driver.query(
            "SELECT c.id, c.ordinal, c.source, c.outcome, c.detail, c.errors, "
            "c.payload, c.evidence, c.created_at FROM input_candidates AS c "
            "JOIN input_requests AS r ON r.id = c.request_id "
            "WHERE r.namespace_id = ? AND c.request_id = ? ORDER BY c.ordinal",
            (self._namespace, request_id),
        )
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
            )
            for row in rows
        )
