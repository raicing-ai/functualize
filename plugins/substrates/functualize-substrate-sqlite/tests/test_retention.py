"""Boot-time relational retention and its cascade boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

from functualize_substrate_sqlite._driver import LocalSqliteDriver
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory
from functualize_substrate_sqlite._retention import apply_retention

from functualize._types.retention import RetentionPolicy
from functualize.plugin import Claimed, ClaimWorkflow, CompleteStep, RuntimeStoreConfig

if TYPE_CHECKING:
    from functualize_substrate_sqlite import SqliteRuntimeStore

STAMP = datetime(2026, 10, 6, tzinfo=UTC).isoformat(timespec="microseconds")


def _config(root: Path, db: Path) -> RuntimeStoreConfig:
    return RuntimeStoreConfig(url=f"sqlite://{db}", scheme="sqlite", project_root=root)


def _seed(driver: LocalSqliteDriver, *, scopes: int, runs: int) -> None:
    statements = [
        (
            "INSERT INTO workflow_scopes (namespace_id, id, workflow, status, "
            "created_at, updated_at, terminal_at) "
            "VALUES ('default', ?, 'flow', 'completed', ?, ?, ?)",
            (f"s{n:03d}", STAMP, STAMP, STAMP),
        )
        for n in range(scopes)
    ]
    statements += [
        (
            "INSERT INTO runs (namespace_id, id, job, status, started_at, ended_at) "
            "VALUES ('default', ?, 'job', 'success', ?, ?)",
            (f"r{n:03d}", STAMP, STAMP),
        )
        for n in range(runs)
    ]
    driver.batch(statements)


def test_prepare_prunes_old_terminal_rows_and_cascades_children_only(
    tmp_path: Path,
) -> None:
    db = tmp_path / "state.db"
    first = cast(
        "SqliteRuntimeStore",
        SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db)).store,
    )
    first.close()
    driver = LocalSqliteDriver(db)
    blob = tmp_path / "shared-artifact.bin"
    blob.write_bytes(b"still here")
    _seed(driver, scopes=600, runs=600)
    driver.batch(
        [
            (
                "INSERT INTO workflow_scopes (namespace_id, id, workflow, status, "
                "created_at, updated_at) VALUES ('default', ?, 'flow', 'blocked', ?, ?)",
                (f"blocked-{n}", STAMP, STAMP),
            )
            for n in range(10)
        ]
        + [
            (
                "INSERT INTO workflow_scopes (namespace_id, id, workflow, status, created_at, updated_at) VALUES ('default', 'running', 'flow', 'running', ?, ?)",
                (STAMP, STAMP),
            ),
            (
                "INSERT INTO workflow_steps (namespace_id, scope_id, step_key, status) VALUES ('default', 's000', 'step', 'done')",
                (),
            ),
            (
                "INSERT INTO scope_state (namespace_id, scope_id, key, updated_at) VALUES ('default', 's000', 'key', ?)",
                (STAMP,),
            ),
            (
                "INSERT INTO workflow_branches (namespace_id, scope_id, decision_key, chosen_target, chosen_at) VALUES ('default', 's000', 'choice', 'end', ?)",
                (STAMP,),
            ),
            (
                "INSERT INTO input_requests (id, namespace_id, scope_id, gate_key, generation, status, created_at) VALUES ('q', 'default', 's000', 'gate', 1, 'open', ?)",
                (STAMP,),
            ),
            (
                "INSERT INTO input_candidates (id, request_id, ordinal, outcome, created_at) VALUES ('candidate', 'q', 1, 'accepted', ?)",
                (STAMP,),
            ),
            (
                "INSERT INTO scope_events (namespace_id, scope_id, seq, type, occurred_at) VALUES ('default', 's000', 1, 'done', ?)",
                (STAMP,),
            ),
            (
                "INSERT INTO run_attempts (id, namespace_id, run_id, attempt_no, status, started_at) VALUES ('attempt', 'default', 'r000', 1, 'succeeded', ?)",
                (STAMP,),
            ),
            (
                "INSERT INTO run_events (namespace_id, run_id, seq, type, occurred_at) VALUES ('default', 'r000', 1, 'done', ?)",
                (STAMP,),
            ),
            (
                "INSERT INTO artifact_refs (id, namespace_id, scope_id, kind, uri, created_at) VALUES ('scope-ref', 'default', 's000', 'file', ?, ?)",
                (str(blob), STAMP),
            ),
            (
                "INSERT INTO artifact_refs (id, namespace_id, run_id, kind, uri, created_at) VALUES ('run-ref', 'default', 'r000', 'file', ?, ?)",
                (str(blob), STAMP),
            ),
            (
                "INSERT INTO runs (namespace_id, id, job, status, started_at) VALUES ('default', 'active', 'job', 'running', ?)",
                (STAMP,),
            ),
        ]
    )
    driver.close()

    store = cast(
        "SqliteRuntimeStore",
        SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db)).store,
    )
    query = store.driver.query
    assert query(
        "SELECT status, count(*) FROM workflow_scopes GROUP BY status ORDER BY status"
    ) == [
        ("blocked", 10),
        ("completed", 500),
        ("running", 1),
    ]
    assert query(
        "SELECT status, count(*) FROM runs GROUP BY status ORDER BY status"
    ) == [
        ("running", 1),
        ("success", 500),
    ]
    for table in (
        "workflow_steps",
        "scope_state",
        "workflow_branches",
        "input_requests",
        "input_candidates",
        "scope_events",
        "run_attempts",
        "run_events",
        "artifact_refs",
    ):
        assert query(f"SELECT count(*) FROM {table}") == [(0,)], table
    assert blob.read_bytes() == b"still here"


def test_a_step_write_never_runs_retention(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    store = cast(
        "SqliteRuntimeStore",
        SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db)).store,
    )
    _seed(cast("LocalSqliteDriver", store.driver), scopes=501, runs=0)
    with store.transaction() as tx:
        claimed = tx.workflows.claim(
            ClaimWorkflow("active", "worker", datetime.now(UTC), 60)
        )
    assert isinstance(claimed, Claimed)
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("active", claimed.generation, "step", datetime.now(UTC))
        )
    assert store.driver.query(
        "SELECT count(*) FROM workflow_scopes WHERE status = 'completed'"
    ) == [(501,)]


def test_age_horizon_uses_terminal_timestamps(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    store = cast(
        "SqliteRuntimeStore",
        SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db)).store,
    )
    old = datetime(2025, 1, 1, tzinfo=UTC).isoformat(timespec="microseconds")
    store.driver.batch(
        [
            (
                "INSERT INTO workflow_scopes (namespace_id, id, workflow, status, "
                "created_at, updated_at, terminal_at) "
                "VALUES ('default', ?, 'flow', 'completed', ?, ?, ?)",
                (scope_id, timestamp, timestamp, timestamp),
            )
            for scope_id, timestamp in (("old", old), ("new", STAMP))
        ]
        + [
            (
                "INSERT INTO runs (namespace_id, id, job, status, started_at, ended_at) "
                "VALUES ('default', ?, 'job', 'success', ?, ?)",
                (run_id, timestamp, timestamp),
            )
            for run_id, timestamp in (("old-run", old), ("new-run", STAMP))
        ]
    )
    removed = apply_retention(
        store.driver,
        "default",
        RetentionPolicy(max_records=500, max_age=timedelta(days=30)),
        now=datetime(2026, 10, 7, tzinfo=UTC),
    )

    assert removed == (1, 1)
    assert store.driver.query("SELECT id FROM workflow_scopes") == [("new",)]
    assert store.driver.query("SELECT id FROM runs") == [("new-run",)]
