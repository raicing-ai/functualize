"""Relational reader ports, indexes, and boot-selected reachability."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from functualize_substrate_sqlite import SqliteRuntimeStore, SQLiteSubstratePlugin
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory
from functualize_substrate_sqlite._readers import SqlRunReader, SqlWorkflowReader

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
)
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.plugin import (
    ClaimWorkflow,
    RunQuery,
    RuntimeStoreConfig,
    StartAttempt,
    SuspendAtGate,
    WorkflowQuery,
)

NOW = datetime(2026, 10, 6, 5, 0, tzinfo=UTC)
STAMP = NOW.isoformat(timespec="microseconds")


@pytest.fixture
def store(tmp_path: Path) -> SqliteRuntimeStore:
    config = RuntimeStoreConfig(
        url=f"sqlite://{tmp_path / 'state.db'}", scheme="sqlite", project_root=tmp_path
    )
    return cast("SqliteRuntimeStore", SqliteRuntimeStoreFactory().prepare(config).store)


def _run(store: SqliteRuntimeStore, run_id: str, *, parent: str | None = None) -> None:
    store.driver.batch(
        [
            (
                "INSERT INTO runs (namespace_id, id, parent_run_id, job, surface, "
                "status, started_at) VALUES ('default', ?, ?, ?, 'cli', 'success', ?)",
                (run_id, parent, run_id, STAMP),
            )
        ]
    )


def test_runs_filter_recent_history_and_build_a_tree(store: SqliteRuntimeStore) -> None:
    _run(store, "root")
    _run(store, "child", parent="root")
    _run(store, "grandchild", parent="child")
    _run(store, "other")

    assert [
        view.run_id for view in store.runs.recent(RunQuery(status="success", limit=2))
    ] == [
        "root",
        "other",
    ]
    assert [
        view.run_id for view in store.runs.recent(RunQuery(parent_run_id="root"))
    ] == ["child"]
    tree = store.runs.tree("root")
    assert tree.run.run_id == "root"
    assert tree.children[0].run.run_id == "child"
    assert tree.children[0].children[0].run.run_id == "grandchild"
    assert store.runs.run("missing") is None
    with pytest.raises(KeyError, match="missing"):
        store.runs.tree("missing")


def test_scope_views_events_and_raw_status_aggregation(
    store: SqliteRuntimeStore,
) -> None:
    store.driver.batch(
        [
            (
                "INSERT INTO workflow_scopes "
                "(namespace_id, id, workflow, status, lease_generation, created_at, updated_at) "
                "VALUES ('default', ?, 'flow', ?, 3, ?, ?)",
                (scope_id, status, STAMP, STAMP),
            )
            for scope_id, status in (
                ("s1", "blocked"),
                ("s2", "blocked"),
                ("s3", "completed"),
            )
        ]
        + [
            (
                "INSERT INTO scope_events (namespace_id, scope_id, seq, type, payload, "
                "occurred_at) VALUES ('default', 's1', ?, 'moved', ?, ?)",
                (seq, '{"n": 1}', STAMP),
            )
            for seq in (1, 2)
        ]
    )

    assert store.workflows.workflow("s1").generation == 3
    assert [
        view.scope_id
        for view in store.workflows.resumable(WorkflowQuery(status="blocked"))
    ] == [
        "s2",
        "s1",
    ]
    assert [event.seq for event in store.workflows.events_after("s1", 1)] == [2]
    # S-6: status is a column; the count needs no JSON function or blob scan.
    sql = "SELECT status, count(*) FROM workflow_scopes GROUP BY status ORDER BY status"
    assert "json" not in sql.lower()
    assert store.driver.query(sql) == [("blocked", 2), ("completed", 1)]


def test_recent_and_resumable_queries_use_the_schema_indexes(
    store: SqliteRuntimeStore,
) -> None:
    recent = store.driver.query(
        f"EXPLAIN QUERY PLAN SELECT {SqlRunReader._COLUMNS} FROM runs WHERE namespace_id = ? "
        "ORDER BY started_at DESC, id DESC LIMIT ?",
        ("default", 20),
    )
    resumable = store.driver.query(
        f"EXPLAIN QUERY PLAN SELECT {SqlWorkflowReader._COLUMNS} FROM workflow_scopes "
        "WHERE namespace_id = ? AND status = ? ORDER BY updated_at DESC",
        ("default", "blocked"),
    )
    assert any("runs_recent" in str(row[3]) for row in recent), recent
    assert any("workflow_scopes_status" in str(row[3]) for row in resumable), resumable


def test_input_requests_and_candidates_keep_recorded_evaluations(
    store: SqliteRuntimeStore,
) -> None:
    with store.transaction() as tx:
        claimed = tx.workflows.claim(ClaimWorkflow("s1", "worker", NOW, 60))
    with store.transaction() as tx:
        tx.workflows.suspend(
            SuspendAtGate("s1", claimed.generation, "approve", "r1", "approve", NOW)
        )
    assert store.inputs.open_for("s1").request_id == "r1"
    assert [request.request_id for request in store.inputs.awaiting()] == ["r1"]

    candidate = GateCandidate(
        "c1",
        "r1",
        1,
        "human",
        NOW,
        CandidateEvaluation(EvaluationOutcome.ACCEPTED, evidence={"source": "test"}),
        {"approved": True},
    )
    with store.transaction() as tx:
        tx.inputs.append(candidate)

    assert store.inputs.awaiting() == ()
    assert store.inputs.request("r1").status == "accepted"
    assert store.inputs.candidates_for("r1") == (candidate,)
    assert store.inputs.request("missing") is None


def test_boot_selected_sqlite_store_exposes_all_three_readers(tmp_path: Path) -> None:
    def alpha() -> None:
        """A job."""

    app = FunctualizeApp(
        "reader-sql",
        job_sources=JobSources(functions=[alpha]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain(
                [
                    DefaultSource(
                        {"runtime_store": {"url": f"sqlite://{tmp_path / 'state.db'}"}}
                    )
                ]
            )
        ),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[SQLiteSubstratePlugin()]
        ),
    )
    selected = cast("SqliteRuntimeStore", app.execution_engine._runtime_store)
    with selected.transaction() as tx:
        tx.runs.start_attempt(StartAttempt("alpha", "app", NOW))
        claimed = tx.workflows.claim(ClaimWorkflow("s1", "worker", NOW, 60))
    with selected.transaction() as tx:
        tx.workflows.suspend(
            SuspendAtGate("s1", claimed.generation, "approve", "r1", "approve", NOW)
        )

    assert selected.runs.recent(RunQuery())[0].job == "alpha"
    assert selected.workflows.workflow("s1").status == "blocked"
    assert selected.inputs.open_for("s1").request_id == "r1"
