"""Unit tests for SQLiteBackend connection management, schema, and WAL mode."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from functualize_state_sqlite.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path: Path) -> SQLiteBackend:
    """Create an initialized SQLiteBackend in a temp directory."""
    db = SQLiteBackend(base_dir=tmp_path)
    db.initialize()
    yield db
    db.close()


@pytest.fixture
def uninit_backend(tmp_path: Path) -> SQLiteBackend:
    """Create an uninitialized SQLiteBackend in a temp directory."""
    return SQLiteBackend(base_dir=tmp_path)


class TestConnectionManagement:
    """Tests for SQLiteBackend connection lifecycle."""

    def test_initialize_creates_directory_and_db(self, tmp_path: Path):
        """Initialize creates .functualize/ dir and execution.db file."""
        db = SQLiteBackend(base_dir=tmp_path)
        db.initialize()
        expected_path = tmp_path / ".functualize" / "execution.db"
        assert expected_path.exists()
        assert db.db_path == expected_path
        db.close()

    def test_initialize_idempotent(self, backend: SQLiteBackend):
        """Calling initialize() multiple times is safe."""
        backend.initialize()
        backend.initialize()
        assert backend.is_initialized

    def test_custom_db_path(self, tmp_path: Path):
        """Can specify a custom database path."""
        custom_path = tmp_path / "custom" / "my.db"
        db = SQLiteBackend(db_path=custom_path)
        db.initialize()
        assert custom_path.exists()
        assert db.db_path == custom_path
        db.close()

    def test_relative_db_path(self, tmp_path: Path):
        """Relative db_path is resolved against base_dir."""
        db = SQLiteBackend(db_path="data/test.db", base_dir=tmp_path)
        db.initialize()
        expected = tmp_path / "data" / "test.db"
        assert db.db_path == expected
        assert expected.exists()
        db.close()

    def test_close_sets_uninitialized(self, backend: SQLiteBackend):
        """Closing resets initialized state."""
        assert backend.is_initialized
        backend.close()
        assert not backend.is_initialized

    def test_connection_raises_before_init(self, uninit_backend: SQLiteBackend):
        """Accessing connection before initialize raises RuntimeError."""
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = uninit_backend.connection

    def test_context_manager_initializes(self, tmp_path: Path):
        """Using as context manager auto-initializes."""
        db = SQLiteBackend(base_dir=tmp_path)
        with db as backend:
            assert backend.is_initialized
        assert not db.is_initialized  # closed on exit


class TestWALMode:
    """Tests for WAL journal mode configuration."""

    def test_wal_mode_enabled(self, backend: SQLiteBackend):
        """WAL mode is active after initialization."""
        cursor = backend.connection.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal"

    def test_synchronous_normal(self, backend: SQLiteBackend):
        """Synchronous mode is set to NORMAL."""
        cursor = backend.connection.execute("PRAGMA synchronous")
        # NORMAL = 1
        sync_val = cursor.fetchone()[0]
        assert sync_val == 1

    def test_foreign_keys_enabled(self, backend: SQLiteBackend):
        """Foreign key constraints are enabled."""
        cursor = backend.connection.execute("PRAGMA foreign_keys")
        fk_val = cursor.fetchone()[0]
        assert fk_val == 1


class TestSchema:
    """Tests for schema initialization."""

    def test_sessions_table_exists(self, backend: SQLiteBackend):
        """The sessions table is created."""
        cursor = backend.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        )
        assert cursor.fetchone() is not None

    def test_executions_table_exists(self, backend: SQLiteBackend):
        """The executions table is created."""
        cursor = backend.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='executions'"
        )
        assert cursor.fetchone() is not None

    def test_execution_steps_table_exists(self, backend: SQLiteBackend):
        """The execution_steps table is created."""
        cursor = backend.connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='execution_steps'"
        )
        assert cursor.fetchone() is not None

    def test_state_table_exists(self, backend: SQLiteBackend):
        """The state table is created."""
        cursor = backend.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='state'"
        )
        assert cursor.fetchone() is not None

    def test_sessions_columns(self, backend: SQLiteBackend):
        """Sessions table has the expected columns."""
        cursor = backend.connection.execute("PRAGMA table_info(sessions)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "session_id",
            "scope_id",
            "created_at",
            "updated_at",
            "workflow_name",
            "status",
            "metadata_json",
        }
        assert expected == columns

    def test_executions_columns(self, backend: SQLiteBackend):
        """Executions table has the expected columns."""
        cursor = backend.connection.execute("PRAGMA table_info(executions)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "execution_uid",
            "session_id",
            "job_name",
            "started_at",
            "ended_at",
            "duration_ms",
            "status",
            "kwargs_json",
            "result_json",
            "error_message",
            "error_type",
            "parent_uid",
            "depth",
        }
        assert expected == columns

    def test_state_composite_primary_key(self, backend: SQLiteBackend):
        """State table has composite primary key (scope_id, job_namespace, key)."""
        # Insert a row, then try inserting the same key — should replace
        backend.upsert_state("scope1", "ns1", "k1", '"v1"')
        backend.upsert_state("scope1", "ns1", "k1", '"v2"')
        result = backend.get_state("scope1", "ns1", "k1")
        assert result == '"v2"'


class TestSessionOperations:
    """Tests for session CRUD helpers."""

    def test_insert_and_get_session(self, backend: SQLiteBackend):
        """Can insert and retrieve a session."""
        sid = str(uuid.uuid4())
        assert backend.insert_session(sid, "scope-1", workflow_name="test-wf")
        session = backend.get_latest_session()
        assert session is not None
        assert session["session_id"] == sid
        assert session["scope_id"] == "scope-1"
        assert session["workflow_name"] == "test-wf"
        assert session["status"] == "running"

    def test_update_session_status(self, backend: SQLiteBackend):
        """Can update session status."""
        sid = str(uuid.uuid4())
        backend.insert_session(sid, "scope-1")
        assert backend.update_session(sid, status="completed")
        session = backend.fetch_one(
            "SELECT * FROM sessions WHERE session_id = ?", (sid,)
        )
        assert session is not None
        assert session["status"] == "completed"

    def test_update_session_metadata(self, backend: SQLiteBackend):
        """Can update session metadata."""
        sid = str(uuid.uuid4())
        backend.insert_session(sid, "scope-1")
        assert backend.update_session(sid, metadata={"key": "value"})
        session = backend.fetch_one(
            "SELECT * FROM sessions WHERE session_id = ?", (sid,)
        )
        assert session is not None
        import json

        assert json.loads(session["metadata_json"]) == {"key": "value"}


class TestExecutionOperations:
    """Tests for execution CRUD helpers."""

    def test_insert_and_get_execution(self, backend: SQLiteBackend):
        """Can insert and retrieve an execution."""
        sid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        backend.insert_session(sid, "scope-1")
        assert backend.insert_execution(
            eid, sid, "my-job", kwargs_json='{"x": 1}', depth=0
        )
        execution = backend.get_execution(eid)
        assert execution is not None
        assert execution["job_name"] == "my-job"
        assert execution["kwargs_json"] == '{"x": 1}'
        assert execution["status"] == "running"
        assert execution["depth"] == 0

    def test_update_execution_success(self, backend: SQLiteBackend):
        """Can update execution with success details."""
        sid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        backend.insert_session(sid, "scope-1")
        backend.insert_execution(eid, sid, "my-job")
        assert backend.update_execution(
            eid, status="success", duration_ms=123.4, result_json='"ok"'
        )
        execution = backend.get_execution(eid)
        assert execution is not None
        assert execution["status"] == "success"
        assert execution["duration_ms"] == 123.4
        assert execution["result_json"] == '"ok"'
        assert execution["ended_at"] is not None

    def test_update_execution_failure(self, backend: SQLiteBackend):
        """Can update execution with error details."""
        sid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        backend.insert_session(sid, "scope-1")
        backend.insert_execution(eid, sid, "my-job")
        assert backend.update_execution(
            eid,
            status="failure",
            duration_ms=50.0,
            error_message="boom",
            error_type="ValueError",
        )
        execution = backend.get_execution(eid)
        assert execution is not None
        assert execution["error_message"] == "boom"
        assert execution["error_type"] == "ValueError"

    def test_nested_execution_parent_uid(self, backend: SQLiteBackend):
        """Can link child execution to parent via parent_uid."""
        sid = str(uuid.uuid4())
        parent_uid = str(uuid.uuid4())
        child_uid = str(uuid.uuid4())
        backend.insert_session(sid, "scope-1")
        backend.insert_execution(parent_uid, sid, "parent-job")
        backend.insert_execution(
            child_uid, sid, "child-job", parent_uid=parent_uid, depth=1
        )
        child = backend.get_execution(child_uid)
        assert child is not None
        assert child["parent_uid"] == parent_uid
        assert child["depth"] == 1

    def test_get_session_executions(self, backend: SQLiteBackend):
        """Get executions for a session returns correct results."""
        sid = str(uuid.uuid4())
        backend.insert_session(sid, "scope-1")
        for i in range(5):
            backend.insert_execution(str(uuid.uuid4()), sid, f"job-{i}")
        results = backend.get_session_executions(sid, limit=3)
        assert len(results) == 3

    def test_get_recent_executions(self, backend: SQLiteBackend):
        """Get recent executions across sessions."""
        sid = str(uuid.uuid4())
        backend.insert_session(sid, "scope-1")
        for i in range(3):
            backend.insert_execution(str(uuid.uuid4()), sid, f"job-{i}")
        results = backend.get_recent_executions(limit=10)
        assert len(results) == 3


class TestStepOperations:
    """Tests for execution step helpers."""

    def test_insert_and_get_steps(self, backend: SQLiteBackend):
        """Can insert and retrieve execution steps."""
        sid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        backend.insert_session(sid, "scope-1")
        backend.insert_execution(eid, sid, "my-job")

        step_id = backend.insert_step(eid, "step-1", message="Starting")
        assert step_id is not None

        steps = backend.get_execution_steps(eid)
        assert len(steps) == 1
        assert steps[0]["step_name"] == "step-1"
        assert steps[0]["message"] == "Starting"

    def test_update_step(self, backend: SQLiteBackend):
        """Can update step status and duration."""
        sid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        backend.insert_session(sid, "scope-1")
        backend.insert_execution(eid, sid, "my-job")

        step_id = backend.insert_step(eid, "step-1")
        assert step_id is not None
        assert backend.update_step(step_id, status="success", duration_ms=45.6)

        steps = backend.get_execution_steps(eid)
        assert steps[0]["status"] == "success"
        assert steps[0]["duration_ms"] == 45.6
        assert steps[0]["ended_at"] is not None


class TestStateOperations:
    """Tests for state CRUD helpers."""

    def test_upsert_and_get_state(self, backend: SQLiteBackend):
        """Can upsert and retrieve state."""
        assert backend.upsert_state("scope-1", "job-a", "key1", '"hello"')
        result = backend.get_state("scope-1", "job-a", "key1")
        assert result == '"hello"'

    def test_upsert_replaces_existing(self, backend: SQLiteBackend):
        """Upsert replaces existing value for same composite key."""
        backend.upsert_state("scope-1", "job-a", "key1", '"v1"')
        backend.upsert_state("scope-1", "job-a", "key1", '"v2"')
        result = backend.get_state("scope-1", "job-a", "key1")
        assert result == '"v2"'

    def test_get_state_returns_none_for_missing(self, backend: SQLiteBackend):
        """Getting non-existent state returns None."""
        result = backend.get_state("scope-x", "job-x", "missing")
        assert result is None

    def test_get_namespace_state(self, backend: SQLiteBackend):
        """Can get all state for a namespace."""
        backend.upsert_state("scope-1", "job-a", "k1", '"v1"')
        backend.upsert_state("scope-1", "job-a", "k2", '"v2"')
        backend.upsert_state("scope-1", "job-b", "k1", '"other"')

        ns_state = backend.get_namespace_state("scope-1", "job-a")
        assert ns_state == {"k1": '"v1"', "k2": '"v2"'}

    def test_get_all_state(self, backend: SQLiteBackend):
        """Can get all state organized by namespace."""
        backend.upsert_state("scope-1", "job-a", "k1", '"v1"')
        backend.upsert_state("scope-1", "job-b", "k2", '"v2"')

        all_state = backend.get_all_state("scope-1")
        assert "job-a" in all_state
        assert "job-b" in all_state
        assert all_state["job-a"]["k1"] == '"v1"'

    def test_delete_state(self, backend: SQLiteBackend):
        """Can delete a specific state key."""
        backend.upsert_state("scope-1", "job-a", "k1", '"v1"')
        assert backend.delete_state("scope-1", "job-a", "k1")
        result = backend.get_state("scope-1", "job-a", "k1")
        assert result is None

    def test_clear_namespace_state(self, backend: SQLiteBackend):
        """Can clear all state in a namespace."""
        backend.upsert_state("scope-1", "job-a", "k1", '"v1"')
        backend.upsert_state("scope-1", "job-a", "k2", '"v2"')
        assert backend.clear_namespace_state("scope-1", "job-a")
        ns_state = backend.get_namespace_state("scope-1", "job-a")
        assert ns_state == {}

    def test_list_namespaces(self, backend: SQLiteBackend):
        """Can list all namespaces for a scope."""
        backend.upsert_state("scope-1", "job-a", "k1", '"v1"')
        backend.upsert_state("scope-1", "job-b", "k2", '"v2"')
        namespaces = backend.list_namespaces("scope-1")
        assert sorted(namespaces) == ["job-a", "job-b"]

    def test_get_namespace_keys(self, backend: SQLiteBackend):
        """Can list all keys in a namespace."""
        backend.upsert_state("scope-1", "job-a", "k1", '"v1"')
        backend.upsert_state("scope-1", "job-a", "k2", '"v2"')
        keys = backend.get_namespace_keys("scope-1", "job-a")
        assert sorted(keys) == ["k1", "k2"]


class TestErrorResilience:
    """Tests for graceful error handling (Requirement 23.11)."""

    def test_execute_safe_returns_none_on_error(self, backend: SQLiteBackend):
        """execute_safe returns None on SQL errors instead of raising."""
        # Invalid SQL should not raise
        result = backend.execute_safe("INSERT INTO nonexistent VALUES (?)", ("x",))
        assert result is None

    def test_fetch_one_returns_none_on_error(self, backend: SQLiteBackend):
        """fetch_one returns None on SQL errors."""
        result = backend.fetch_one("SELECT * FROM nonexistent_table")
        assert result is None

    def test_fetch_all_returns_empty_on_error(self, backend: SQLiteBackend):
        """fetch_all returns empty list on SQL errors."""
        result = backend.fetch_all("SELECT * FROM nonexistent_table")
        assert result == []

    def test_insert_session_returns_false_on_duplicate(self, backend: SQLiteBackend):
        """Inserting duplicate session returns False."""
        sid = "same-id"
        backend.insert_session(sid, "scope-1")
        # Second insert with same primary key should fail gracefully
        result = backend.insert_session(sid, "scope-2")
        assert result is False
