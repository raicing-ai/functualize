"""Unit tests for functualize-state-sqlite plugin.

Tests SQLite backend operations: get/set/delete, key listing,
serialization roundtrips, and execution store record insertion.
"""

from __future__ import annotations

from pathlib import Path

from functualize_state._types import ExecutionRecord
from functualize_state_sqlite._backend import SQLiteStateBackend
from functualize_state_sqlite._execution_store import SQLiteExecutionStore


class TestSQLiteStateBackend:
    """Tests for the SQLite state backend."""

    def test_get_returns_default_for_missing_key(self, tmp_db_path: Path):
        backend = SQLiteStateBackend(db_path=tmp_db_path)
        assert backend.get("nonexistent") is None
        assert backend.get("nonexistent", "fallback") == "fallback"

    def test_set_and_get_roundtrip(self, tmp_db_path: Path):
        backend = SQLiteStateBackend(db_path=tmp_db_path)
        backend.set("greeting", "hello")
        assert backend.get("greeting") == "hello"

    def test_set_overwrites_existing(self, tmp_db_path: Path):
        backend = SQLiteStateBackend(db_path=tmp_db_path)
        backend.set("key", "first")
        backend.set("key", "second")
        assert backend.get("key") == "second"

    def test_delete_removes_key(self, tmp_db_path: Path):
        backend = SQLiteStateBackend(db_path=tmp_db_path)
        backend.set("key", "value")
        backend.delete("key")
        assert backend.get("key") is None

    def test_delete_nonexistent_key_does_not_raise(self, tmp_db_path: Path):
        backend = SQLiteStateBackend(db_path=tmp_db_path)
        backend.delete("nope")  # Should not raise

    def test_keys_with_prefix(self, tmp_db_path: Path):
        backend = SQLiteStateBackend(db_path=tmp_db_path)
        backend.set("app.name", "functualize")
        backend.set("app.version", "1.0")
        backend.set("other.key", "value")
        keys = backend.keys("app.")
        assert "app.name" in keys
        assert "app.version" in keys
        assert "other.key" not in keys

    def test_stores_complex_types(self, tmp_db_path: Path):
        backend = SQLiteStateBackend(db_path=tmp_db_path)
        data = {"nested": {"list": [1, 2, 3], "bool": True}}
        backend.set("complex", data)
        assert backend.get("complex") == data

    def test_db_file_created(self, tmp_db_path: Path):
        backend = SQLiteStateBackend(db_path=tmp_db_path)
        backend.set("init", "trigger")
        assert tmp_db_path.exists()


class TestSQLiteExecutionStore:
    """Tests for the execution tracking store."""

    def test_insert_returns_execution_id(self, tmp_execution_db_path: Path):
        import time

        store = SQLiteExecutionStore(db_path=tmp_execution_db_path)
        record = ExecutionRecord(
            execution_id="exec-001",
            job_name="deploy",
            session_id="session-001",
            status="success",
            started_at=time.time(),
            ended_at=time.time(),
            duration_ms=42.0,
        )
        exec_id = store.insert_execution(record)
        assert exec_id is not None
        assert isinstance(exec_id, str)
        assert len(exec_id) > 0
