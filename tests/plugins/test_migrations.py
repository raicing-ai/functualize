"""Tests for the schema migration system in functualize-state-sqlite."""

from __future__ import annotations

import sqlite3

import pytest
from functualize_state_sqlite._migrations import (
    LATEST_VERSION,
    get_current_version,
    migrate,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Create an in-memory SQLite connection for testing."""
    connection = sqlite3.connect(":memory:")
    yield connection
    connection.close()


class TestGetCurrentVersion:
    """Tests for get_current_version."""

    def test_returns_zero_on_fresh_database(self, conn: sqlite3.Connection) -> None:
        """Fresh database with no migrations should report version 0."""
        assert get_current_version(conn) == 0

    def test_returns_version_after_migration(self, conn: sqlite3.Connection) -> None:
        """After running migrations, reports the latest applied version."""
        migrate(conn)
        assert get_current_version(conn) == LATEST_VERSION

    def test_creates_schema_version_table(self, conn: sqlite3.Connection) -> None:
        """Calling get_current_version creates the schema_version table."""
        get_current_version(conn)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        assert cursor.fetchone() is not None


class TestMigrate:
    """Tests for the migrate function."""

    def test_applies_initial_migration(self, conn: sqlite3.Connection) -> None:
        """Migration should create all required tables."""
        version = migrate(conn)
        assert version == LATEST_VERSION

        # Verify all tables exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "state" in tables
        assert "executions" in tables
        assert "phases" in tables
        assert "sessions" in tables
        assert "schema_version" in tables

    def test_records_version_in_schema_version_table(
        self, conn: sqlite3.Connection
    ) -> None:
        """Each applied migration is recorded in schema_version."""
        migrate(conn)
        cursor = conn.execute("SELECT version, applied_at FROM schema_version")
        rows = cursor.fetchall()
        assert len(rows) == LATEST_VERSION
        # Version 1 should be recorded
        versions = {row[0] for row in rows}
        assert 1 in versions
        # applied_at should be a positive float (timestamp)
        for row in rows:
            assert row[1] > 0

    def test_idempotent_on_second_call(self, conn: sqlite3.Connection) -> None:
        """Running migrate twice should be a no-op the second time."""
        migrate(conn)
        version = migrate(conn)
        assert version == LATEST_VERSION
        # Should still have exactly one version row
        cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
        count = cursor.fetchone()[0]
        assert count == LATEST_VERSION

    def test_state_table_schema(self, conn: sqlite3.Connection) -> None:
        """Verify the state table has the expected columns."""
        migrate(conn)
        # Insert and retrieve to verify schema
        conn.execute(
            "INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?)",
            ("test_key", '{"data": 1}', 1234567890.0),
        )
        conn.commit()
        cursor = conn.execute(
            "SELECT key, value, updated_at FROM state WHERE key = ?", ("test_key",)
        )
        row = cursor.fetchone()
        assert row == ("test_key", '{"data": 1}', 1234567890.0)

    def test_sessions_table_schema(self, conn: sqlite3.Connection) -> None:
        """Verify the sessions table has the expected columns."""
        migrate(conn)
        conn.execute(
            "INSERT INTO sessions (session_id, started_at, metadata) VALUES (?, ?, ?)",
            ("sess-1", 1000.0, '{"env": "test"}'),
        )
        conn.commit()
        cursor = conn.execute("SELECT session_id, started_at, metadata FROM sessions")
        row = cursor.fetchone()
        assert row == ("sess-1", 1000.0, '{"env": "test"}')

    def test_executions_table_schema(self, conn: sqlite3.Connection) -> None:
        """Verify the executions table has the expected columns."""
        migrate(conn)
        # Need a session first due to foreign key
        conn.execute(
            "INSERT INTO sessions (session_id, started_at) VALUES (?, ?)",
            ("sess-1", 1000.0),
        )
        conn.execute(
            """INSERT INTO executions
               (execution_id, job_name, session_id, status, started_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("exec-1", "my-job", "sess-1", "running", 1001.0),
        )
        conn.commit()
        cursor = conn.execute(
            "SELECT execution_id, job_name, session_id, status, started_at FROM executions"
        )
        row = cursor.fetchone()
        assert row == ("exec-1", "my-job", "sess-1", "running", 1001.0)

    def test_phases_table_schema(self, conn: sqlite3.Connection) -> None:
        """Verify the phases table has the expected columns."""
        migrate(conn)
        conn.execute(
            "INSERT INTO sessions (session_id, started_at) VALUES (?, ?)",
            ("sess-1", 1000.0),
        )
        conn.execute(
            """INSERT INTO executions
               (execution_id, job_name, session_id, status, started_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("exec-1", "my-job", "sess-1", "running", 1001.0),
        )
        conn.execute(
            """INSERT INTO phases
               (execution_id, name, status, started_at)
               VALUES (?, ?, ?, ?)""",
            ("exec-1", "setup", "running", 1002.0),
        )
        conn.commit()
        cursor = conn.execute(
            "SELECT execution_id, name, status, started_at FROM phases"
        )
        row = cursor.fetchone()
        assert row == ("exec-1", "setup", "running", 1002.0)

    def test_latest_version_is_positive(self) -> None:
        """LATEST_VERSION should be at least 1."""
        assert LATEST_VERSION >= 1
