"""The migration runner and revision `0001` — data model §2 and §7."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from functualize_substrate_sqlite._driver import LocalSqliteDriver
from functualize_substrate_sqlite._migrations import (
    SHIPPED_MIGRATIONS,
    Migration,
    MigrationRefused,
    migrate,
)

from functualize._types.lifecycle import ATTEMPT, INPUT_REQUEST, RUN, SCOPE, Machine

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
    "outbox",
    "artifact_refs",
    "runtime_cutover",
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
}


@pytest.fixture
def driver(tmp_path: Path) -> LocalSqliteDriver:
    return LocalSqliteDriver(tmp_path / "state.db")


def _names(driver: LocalSqliteDriver, kind: str) -> set[str]:
    rows = driver.query("SELECT name FROM sqlite_master WHERE type = ?", (kind,))
    return {name for (name,) in rows if not name.startswith("sqlite_")}


def test_an_empty_database_becomes_version_1_with_one_ledger_row(
    driver: LocalSqliteDriver,
) -> None:
    assert migrate(driver) == 1

    rows = driver.query("SELECT version, name, checksum FROM schema_migrations")
    assert rows == [(1, "runtime_schema", REVISION_1.checksum)]


def test_a_second_run_is_a_no_op(driver: LocalSqliteDriver) -> None:
    migrate(driver)
    schema = driver.query("SELECT sql FROM sqlite_master ORDER BY name")

    assert migrate(driver) == 1
    assert driver.query("SELECT count(*) FROM schema_migrations") == [(1,)]
    assert driver.query("SELECT sql FROM sqlite_master ORDER BY name") == schema


def test_an_edited_revision_is_refused(driver: LocalSqliteDriver) -> None:
    migrate(driver)
    edited = Migration(1, REVISION_1.name, REVISION_1.sql + "\n-- edited\n")

    with pytest.raises(MigrationRefused) as refused:
        migrate(driver, [edited])

    assert refused.value.version == 1
    assert refused.value.expected_checksum == edited.checksum
    assert refused.value.actual_checksum == REVISION_1.checksum
    assert "Repair:" in str(refused.value)


def test_a_ledger_ahead_of_the_shipped_set_is_refused(
    driver: LocalSqliteDriver,
) -> None:
    migrate(driver)
    driver.batch(
        [("INSERT INTO schema_migrations VALUES (2, 'future', 'x', 'now')", ())]
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

    assert migrate(driver) == 1


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
