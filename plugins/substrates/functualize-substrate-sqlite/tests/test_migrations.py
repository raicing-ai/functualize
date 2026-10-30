"""The migration runner and revisions — data model §2 and §7."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from functualize_substrate_sqlite._driver import LocalSqliteDriver
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory
from functualize_substrate_sqlite._migrations import (
    SHIPPED_MIGRATIONS,
    Migration,
    MigrationRefused,
    migrate,
)

from functualize._types.lifecycle import ATTEMPT, INPUT_REQUEST, RUN, SCOPE, Machine
from functualize.plugin import RuntimeStoreConfig, StartAttempt

REVISION_1 = SHIPPED_MIGRATIONS[0]

#: Data model §2, every table; plus `runtime_cutover` (contracts §6).
TABLES = {
    "schema_migrations",
    "namespaces",
    "runs",
    "run_attempts",
    "run_events",
    "workflow_scopes",
    "workflow_steps",
    "workflow_branches",
    "scope_state",
    "scope_events",
    "input_requests",
    "input_candidates",
    "input_decisions",
    "input_decision_observations",
    "outbox",
    "artifact_refs",
    "runtime_cutover",
    "run_tags",
}

#: Data model §2's indexes and uniqueness rules, by name.
INDEXES = {
    "namespaces_project_key",
    "runs_recent",
    "runs_job",
    "runs_scope",
    "runs_parent",
    "run_attempts_run_attempt_no",
    "run_events_run_seq",
    "workflow_scopes_status",
    "workflow_scopes_lease_expires",
    "workflow_steps_scope_step_iteration",
    "workflow_branches_scope_decision",
    "scope_state_scope_key",
    "scope_events_scope_seq",
    "input_requests_one_open_per_gate",
    "input_candidates_request_ordinal",
    "outbox_idempotency_key",
    "outbox_status_available",
    "input_decision_observations_candidate",
    "artifact_refs_candidate",
    "run_tags_lookup",
}


@pytest.fixture
def driver(tmp_path: Path) -> LocalSqliteDriver:
    return LocalSqliteDriver(tmp_path / "state.db")


def _names(driver: LocalSqliteDriver, kind: str) -> set[str]:
    rows = driver.query("SELECT name FROM sqlite_master WHERE type = ?", (kind,))
    return {name for (name,) in rows if not name.startswith("sqlite_")}


def test_an_empty_database_becomes_version_5_with_five_ledger_rows(
    driver: LocalSqliteDriver,
) -> None:
    assert migrate(driver) == 5

    rows = driver.query("SELECT version, name, checksum FROM schema_migrations")
    assert rows == [
        (1, "runtime_schema", REVISION_1.checksum),
        (2, "step_record_metadata", SHIPPED_MIGRATIONS[1].checksum),
        (3, "step_attempt", SHIPPED_MIGRATIONS[2].checksum),
        (4, "gate_interactions", SHIPPED_MIGRATIONS[3].checksum),
        (5, "run_tags", SHIPPED_MIGRATIONS[4].checksum),
    ]
    columns = {row[1]: row for row in driver.query("PRAGMA table_info(workflow_steps)")}
    assert columns["attempt"][2:5] == ("INTEGER", 1, "0")  # type, NOT NULL, default


def test_prepare_upgrades_a_version_1_file_and_defaults_step_metadata(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.db"
    driver = LocalSqliteDriver(path)
    try:
        assert migrate(driver, SHIPPED_MIGRATIONS[:1]) == 1
        version_1_checksum = driver.query(
            "SELECT checksum FROM schema_migrations WHERE version = 1"
        )[0][0]
    finally:
        driver.close()

    prepared = SqliteRuntimeStoreFactory().prepare(
        RuntimeStoreConfig(
            url=f"sqlite://{path}", scheme="sqlite", project_root=tmp_path
        )
    )
    try:
        driver = LocalSqliteDriver(path)
        try:
            assert driver.query("SELECT max(version) FROM schema_migrations") == [(5,)]
            columns = {
                row[1]: row for row in driver.query("PRAGMA table_info(workflow_steps)")
            }
            assert {"result_kind", "result_type", "effecting"} <= columns.keys()
            assert columns["effecting"][4] == "0"
            assert driver.query(
                "SELECT checksum FROM schema_migrations WHERE version = 1"
            ) == [(version_1_checksum,)]
        finally:
            driver.close()
    finally:
        prepared.store.close()


def test_a_populated_version_2_database_upgrades_with_attempt_0(
    driver: LocalSqliteDriver,
) -> None:
    assert migrate(driver, SHIPPED_MIGRATIONS[:2]) == 2
    driver.batch(
        [
            ("INSERT INTO namespaces VALUES ('default', 'p', 'now')", ()),
            (
                "INSERT INTO workflow_scopes (namespace_id, id, workflow, status, "
                "created_at, updated_at) VALUES ('default', 's1', 'f', 'running', "
                "'now', 'now')",
                (),
            ),
            (
                "INSERT INTO workflow_steps (namespace_id, scope_id, step_key, "
                "status, effecting, started_at) VALUES "
                "('default', 's1', 'charge::', 'success', 1, '2026-10-01T00:00:00')",
                (),
            ),
        ]
    )

    assert migrate(driver) == 5
    assert driver.query(
        "SELECT step_key, status, effecting, attempt, started_at FROM workflow_steps"
    ) == [("charge::", "success", 1, 0, "2026-10-01T00:00:00")]
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        driver.batch([("UPDATE workflow_steps SET attempt = -1", ())])


def test_an_applied_revision_whose_column_is_gone_is_refused(
    driver: LocalSqliteDriver,
) -> None:
    migrate(driver)
    driver.batch([("ALTER TABLE workflow_steps DROP COLUMN attempt", ())])

    with pytest.raises(MigrationRefused, match=r"workflow_steps\.attempt") as refused:
        migrate(driver)
    assert refused.value.version == 3


def test_a_pre_merge_revision_3_gate_database_is_refused_naming_the_renumber(
    driver: LocalSqliteDriver,
) -> None:
    """A database built while the gate SQL was revision 3 refuses at boot.

    Before the branch merged with the step-attempt work, this package shipped
    the gate-interactions SQL as revision 3; the merged set keeps step_attempt
    at 3 and moves the same bytes to 4. A pre-merge database records them
    under version 3, so boot refuses — nothing applied, the renumbering
    named, and one remedy: rebuild. No data migration shipped for it.
    """
    pre_merge = [
        *SHIPPED_MIGRATIONS[:2],
        Migration(3, "gate_interactions", SHIPPED_MIGRATIONS[3].sql),
    ]
    assert migrate(driver, pre_merge) == 3
    ledger_before = driver.query(
        "SELECT version, checksum FROM schema_migrations WHERE version = 3"
    )

    with pytest.raises(MigrationRefused, match="renumbered") as refused:
        migrate(driver)

    assert refused.value.version == 3
    assert refused.value.expected_checksum == SHIPPED_MIGRATIONS[2].checksum
    assert refused.value.actual_checksum == SHIPPED_MIGRATIONS[3].checksum
    assert "rebuild" in refused.value.repair
    # Refused, not repaired: the ledger and the schema are untouched.
    assert (
        driver.query(
            "SELECT version, checksum FROM schema_migrations WHERE version = 3"
        )
        == ledger_before
    )
    assert driver.query("SELECT count(*) FROM schema_migrations") == [(3,)]


def test_a_second_run_is_a_no_op(driver: LocalSqliteDriver) -> None:
    migrate(driver)
    schema = driver.query("SELECT sql FROM sqlite_master ORDER BY name")

    assert migrate(driver) == 5
    assert driver.query("SELECT count(*) FROM schema_migrations") == [(5,)]
    assert driver.query("SELECT sql FROM sqlite_master ORDER BY name") == schema


def test_an_edited_revision_is_refused(driver: LocalSqliteDriver) -> None:
    migrate(driver)
    edited = Migration(1, REVISION_1.name, REVISION_1.sql + "\n-- edited\n")

    with pytest.raises(MigrationRefused) as refused:
        migrate(driver, [edited, *SHIPPED_MIGRATIONS[1:]])

    assert refused.value.version == 1
    assert refused.value.expected_checksum == edited.checksum
    assert refused.value.actual_checksum == REVISION_1.checksum
    assert "Repair:" in str(refused.value)


def test_a_ledger_ahead_of_the_shipped_set_is_refused(
    driver: LocalSqliteDriver,
) -> None:
    migrate(driver)
    driver.batch(
        [("INSERT INTO schema_migrations VALUES (6, 'future', 'x', 'now')", ())]
    )

    with pytest.raises(MigrationRefused, match="newer than this code"):
        migrate(driver)


def test_a_gap_in_the_ledger_is_refused(driver: LocalSqliteDriver) -> None:
    migrate(driver)
    driver.batch(
        [
            ("DELETE FROM schema_migrations", ()),
            ("INSERT INTO schema_migrations VALUES (2, 'second', 'x', 'now')", ()),
        ]
    )
    second = Migration(2, "second", "CREATE TABLE second (id INTEGER);")

    with pytest.raises(MigrationRefused, match="gap"):
        migrate(driver, [REVISION_1, second])


def test_runtime_tables_with_no_ledger_are_refused(driver: LocalSqliteDriver) -> None:
    driver.batch([("CREATE TABLE workflow_scopes (id TEXT)", ())])

    with pytest.raises(MigrationRefused, match="no schema_migrations ledger"):
        migrate(driver)


def test_a_legacy_documents_table_alone_is_migrated(driver: LocalSqliteDriver) -> None:
    driver.batch(
        [
            (
                "CREATE TABLE documents (key TEXT PRIMARY KEY, payload TEXT, revision INTEGER)",
                (),
            )
        ]
    )

    assert migrate(driver) == 5


def test_a_failing_revision_leaves_neither_schema_nor_ledger(
    driver: LocalSqliteDriver,
) -> None:
    broken = Migration(
        1, "broken", "CREATE TABLE ok (id INTEGER);\nCREATE TABLE ok (id INTEGER);\n"
    )

    with pytest.raises(Exception, match="already exists"):
        migrate(driver, [broken])

    assert _names(driver, "table") == set()


def test_every_table_and_index_of_the_data_model_exists(
    driver: LocalSqliteDriver,
) -> None:
    migrate(driver)

    assert _names(driver, "table") == TABLES
    assert _names(driver, "index") >= INDEXES


@pytest.mark.parametrize(
    ("table", "machine"),
    [
        ("workflow_scopes", SCOPE),
        ("runs", RUN),
        ("run_attempts", ATTEMPT),
        ("input_requests", INPUT_REQUEST),
    ],
)
def test_each_status_check_equals_its_machines_state_set(
    driver: LocalSqliteDriver, table: str, machine: Machine
) -> None:
    migrate(driver)
    [(sql,)] = driver.query("SELECT sql FROM sqlite_master WHERE name = ?", (table,))
    match = re.search(r"status\s+TEXT\s+NOT NULL CHECK \(status IN \(([^)]*)\)\)", sql)
    assert match, f"{table} has no status CHECK"

    declared = set(re.findall(r"'([^']+)'", match.group(1)))

    assert declared == set(machine.states)


def test_append_only_tables_refuse_an_update(driver: LocalSqliteDriver) -> None:
    migrate(driver)
    driver.batch(
        [
            ("INSERT INTO namespaces VALUES ('ns', 'project', 'now')", ()),
            (
                "INSERT INTO runs (namespace_id, id, job, status, started_at) VALUES ('ns', 'r1', 'j', 'running', 'now')",
                (),
            ),
            (
                "INSERT INTO run_events VALUES ('ns', 'r1', 1, 'started', NULL, 'now')",
                (),
            ),
        ]
    )

    with pytest.raises(Exception, match="append-only"):
        driver.batch([("UPDATE run_events SET type = 'edited'", ())])


def test_deleting_a_scope_cascades_its_artifact_reference_only(
    driver: LocalSqliteDriver,
) -> None:
    migrate(driver)
    driver.batch(
        [
            ("INSERT INTO namespaces VALUES ('ns', 'project', 'now')", ()),
            (
                "INSERT INTO workflow_scopes (namespace_id, id, workflow, status, created_at, updated_at) "
                "VALUES ('ns', 'scope', 'flow', 'completed', 'now', 'now')",
                (),
            ),
            (
                "INSERT INTO artifact_refs (id, namespace_id, scope_id, kind, uri, created_at) "
                "VALUES ('ref', 'ns', 'scope', 'output', 'file:///untouched', 'now')",
                (),
            ),
        ]
    )

    driver.batch([("DELETE FROM workflow_scopes WHERE id = 'scope'", ())])

    assert driver.query("SELECT id FROM artifact_refs") == []


def test_a_populated_version_4_database_migrates_to_5_and_gains_run_tags(
    tmp_path: Path,
) -> None:
    """AC15: the table and its index arrive; existing runs gain no rows; a run
    started afterwards writes one row per key."""
    path = tmp_path / "state.db"
    driver = LocalSqliteDriver(path)
    try:
        assert migrate(driver, SHIPPED_MIGRATIONS[:4]) == 4
        assert "run_tags" not in _names(driver, "table")
        driver.batch(
            [
                ("INSERT INTO namespaces VALUES ('default', 'p', 'now')", ()),
                (
                    "INSERT INTO runs (namespace_id, id, job, status, started_at) "
                    "VALUES ('default', 'r-old', 'j', 'success', 'now')",
                    (),
                ),
            ]
        )
        assert migrate(driver) == 5
        assert "run_tags" in _names(driver, "table")
        assert "run_tags_lookup" in _names(driver, "index")
        assert driver.query("SELECT id FROM runs") == [("r-old",)]
        assert driver.query("SELECT count(*) FROM run_tags") == [(0,)]
    finally:
        driver.close()

    store = (
        SqliteRuntimeStoreFactory()
        .prepare(
            RuntimeStoreConfig(
                url=f"sqlite://{path}", scheme="sqlite", project_root=tmp_path
            )
        )
        .store
    )
    try:
        with store.transaction() as tx:
            tx.runs.start_attempt(
                StartAttempt(
                    "tagged",
                    "cli",
                    datetime(2026, 10, 28, tzinfo=UTC),
                    run_tags={"model": "opus", "harness": "claude"},
                )
            )
        check = LocalSqliteDriver(path)
        try:
            assert check.query(
                "SELECT t.key, t.value FROM run_tags t JOIN runs r "
                "ON r.namespace_id = t.namespace_id AND r.id = t.run_id "
                "WHERE r.job = 'tagged' ORDER BY t.key"
            ) == [("harness", "claude"), ("model", "opus")]
        finally:
            check.close()
    finally:
        store.close()


def test_revision_5_is_additive_and_revision_4_stays_a_rollback_target(
    driver: LocalSqliteDriver,
) -> None:
    """Revision 5 creates objects only; a build stopped at 4 is still whole."""
    sql = SHIPPED_MIGRATIONS[4].sql.upper()
    assert "DROP " not in sql and "ALTER " not in sql
    assert migrate(driver, SHIPPED_MIGRATIONS[:4]) == 4
    assert _names(driver, "table") == TABLES - {"run_tags"}
    assert migrate(driver) == 5


def test_an_applied_revision_5_whose_table_is_gone_is_refused(
    driver: LocalSqliteDriver,
) -> None:
    migrate(driver)
    driver.batch([("DROP TABLE run_tags", ())])

    with pytest.raises(MigrationRefused, match="run_tags") as refused:
        migrate(driver)
    assert refused.value.version == 5


def test_run_tags_refuse_every_change_but_the_cascade(
    driver: LocalSqliteDriver,
) -> None:
    """AC33 at the schema: an update, a direct delete and a late insert are
    each refused; deleting the run removes its tags through the cascade."""
    migrate(driver)
    driver.batch(
        [
            ("INSERT INTO namespaces VALUES ('ns', 'project', 'now')", ()),
            (
                "INSERT INTO runs (namespace_id, id, job, status, started_at) "
                "VALUES ('ns', 'r1', 'j', 'running', 'now')",
                (),
            ),
            ("INSERT INTO run_tags VALUES ('ns', 'r1', 'k', 'v')", ()),
            (
                "INSERT INTO run_attempts (id, namespace_id, run_id, attempt_no, "
                "status, started_at) VALUES ('r1#1', 'ns', 'r1', 1, 'running', 'now')",
                (),
            ),
        ]
    )

    for statement in (
        "UPDATE run_tags SET value = 'changed'",
        "DELETE FROM run_tags",
        "INSERT INTO run_tags VALUES ('ns', 'r1', 'late', 'x')",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="fixed when the run opens"):
            driver.batch([(statement, ())])
    assert driver.query("SELECT key, value FROM run_tags") == [("k", "v")]

    driver.batch([("DELETE FROM runs WHERE id = 'r1'", ())])
    assert driver.query("SELECT count(*) FROM run_tags") == [(0,)]
