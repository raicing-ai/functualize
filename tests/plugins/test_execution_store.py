"""Tests for the SQLiteExecutionStore implementation."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from functualize_state._protocols import ExecutionStore
from functualize_state._types import ExecutionRecord, PhaseRecord
from functualize_state_sqlite._execution_store import SQLiteExecutionStore


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def store(tmp_db: Path) -> SQLiteExecutionStore:
    """Create a SQLiteExecutionStore with a temporary database."""
    s = SQLiteExecutionStore(db_path=tmp_db)
    yield s
    s.close()


class TestProtocolConformance:
    """Verify that SQLiteExecutionStore satisfies the ExecutionStore protocol."""

    def test_isinstance_check(self, store: SQLiteExecutionStore) -> None:
        """SQLiteExecutionStore is recognized as an ExecutionStore."""
        assert isinstance(store, ExecutionStore)


class TestInsertExecution:
    """Tests for insert_execution."""

    def test_insert_and_retrieve(self, store: SQLiteExecutionStore) -> None:
        """Inserted execution can be retrieved via get_session_executions."""
        record = ExecutionRecord(
            execution_id="exec-1",
            job_name="my-job",
            session_id="session-1",
            status="running",
            started_at=time.time(),
        )
        result_id = store.insert_execution(record)

        assert result_id == "exec-1"

        executions = store.get_session_executions("session-1")
        assert len(executions) == 1
        assert executions[0].execution_id == "exec-1"
        assert executions[0].job_name == "my-job"
        assert executions[0].status == "running"
        assert executions[0].session_id == "session-1"

    def test_insert_with_kwargs_and_result(self, store: SQLiteExecutionStore) -> None:
        """kwargs and result are JSON-serialized and deserialized correctly."""
        record = ExecutionRecord(
            execution_id="exec-2",
            job_name="compute",
            session_id="session-1",
            status="success",
            started_at=1000.0,
            ended_at=1005.0,
            duration_ms=5000.0,
            kwargs={"input": "hello", "count": 42},
            result={"output": "world", "values": [1, 2, 3]},
        )
        store.insert_execution(record)

        executions = store.get_session_executions("session-1")
        assert len(executions) == 1
        retrieved = executions[0]
        assert retrieved.kwargs == {"input": "hello", "count": 42}
        assert retrieved.result == {"output": "world", "values": [1, 2, 3]}
        assert retrieved.ended_at == 1005.0
        assert retrieved.duration_ms == 5000.0

    def test_insert_multiple_executions(self, store: SQLiteExecutionStore) -> None:
        """Multiple executions in same session are all retrievable."""
        for i in range(5):
            record = ExecutionRecord(
                execution_id=f"exec-{i}",
                job_name=f"job-{i}",
                session_id="session-multi",
                status="success",
                started_at=1000.0 + i,
            )
            store.insert_execution(record)

        executions = store.get_session_executions("session-multi")
        assert len(executions) == 5
        # Ordered by started_at DESC
        assert executions[0].execution_id == "exec-4"
        assert executions[4].execution_id == "exec-0"

    def test_session_auto_created(self, store: SQLiteExecutionStore) -> None:
        """Session is automatically created when inserting execution."""
        record = ExecutionRecord(
            execution_id="exec-auto",
            job_name="auto-job",
            session_id="new-session",
            status="running",
            started_at=time.time(),
        )
        # Should not raise even though session doesn't exist yet
        store.insert_execution(record)

        executions = store.get_session_executions("new-session")
        assert len(executions) == 1


class TestUpdateExecution:
    """Tests for update_execution."""

    def test_update_status(self, store: SQLiteExecutionStore) -> None:
        """Updating status field persists correctly."""
        record = ExecutionRecord(
            execution_id="exec-upd",
            job_name="updatable",
            session_id="session-upd",
            status="running",
            started_at=1000.0,
        )
        store.insert_execution(record)

        store.update_execution(
            "exec-upd", status="success", ended_at=1005.0, duration_ms=5000.0
        )

        executions = store.get_session_executions("session-upd")
        assert len(executions) == 1
        assert executions[0].status == "success"
        assert executions[0].ended_at == 1005.0
        assert executions[0].duration_ms == 5000.0

    def test_update_result(self, store: SQLiteExecutionStore) -> None:
        """Updating result field with a complex value."""
        record = ExecutionRecord(
            execution_id="exec-res",
            job_name="result-job",
            session_id="session-res",
            status="running",
            started_at=1000.0,
        )
        store.insert_execution(record)

        store.update_execution("exec-res", result={"answer": 42})

        executions = store.get_session_executions("session-res")
        assert executions[0].result == {"answer": 42}

    def test_update_kwargs(self, store: SQLiteExecutionStore) -> None:
        """Updating kwargs field."""
        record = ExecutionRecord(
            execution_id="exec-kw",
            job_name="kwargs-job",
            session_id="session-kw",
            status="running",
            started_at=1000.0,
        )
        store.insert_execution(record)

        store.update_execution("exec-kw", kwargs={"new_key": "new_value"})

        executions = store.get_session_executions("session-kw")
        assert executions[0].kwargs == {"new_key": "new_value"}

    def test_update_no_fields_is_noop(self, store: SQLiteExecutionStore) -> None:
        """Calling update with no fields does nothing."""
        record = ExecutionRecord(
            execution_id="exec-noop",
            job_name="noop-job",
            session_id="session-noop",
            status="running",
            started_at=1000.0,
        )
        store.insert_execution(record)

        # Should not raise
        store.update_execution("exec-noop")

        executions = store.get_session_executions("session-noop")
        assert executions[0].status == "running"


class TestGetSessionExecutions:
    """Tests for get_session_executions."""

    def test_empty_session(self, store: SQLiteExecutionStore) -> None:
        """Returns empty list for session with no executions."""
        executions = store.get_session_executions("nonexistent-session")
        assert executions == []

    def test_limit_parameter(self, store: SQLiteExecutionStore) -> None:
        """limit parameter restricts the number of results."""
        for i in range(10):
            record = ExecutionRecord(
                execution_id=f"exec-lim-{i}",
                job_name="limited",
                session_id="session-lim",
                status="success",
                started_at=1000.0 + i,
            )
            store.insert_execution(record)

        executions = store.get_session_executions("session-lim", limit=3)
        assert len(executions) == 3
        # Most recent first
        assert executions[0].execution_id == "exec-lim-9"

    def test_different_sessions_isolated(self, store: SQLiteExecutionStore) -> None:
        """Executions from different sessions don't mix."""
        for sid in ("session-a", "session-b"):
            for i in range(3):
                record = ExecutionRecord(
                    execution_id=f"{sid}-exec-{i}",
                    job_name="isolated",
                    session_id=sid,
                    status="success",
                    started_at=1000.0 + i,
                )
                store.insert_execution(record)

        a_execs = store.get_session_executions("session-a")
        b_execs = store.get_session_executions("session-b")
        assert len(a_execs) == 3
        assert len(b_execs) == 3
        assert all(e.session_id == "session-a" for e in a_execs)
        assert all(e.session_id == "session-b" for e in b_execs)


class TestPhases:
    """Tests for insert_phase and get_execution_phases."""

    def test_insert_and_retrieve_phases(self, store: SQLiteExecutionStore) -> None:
        """Phases can be inserted and retrieved for an execution."""
        record = ExecutionRecord(
            execution_id="exec-ph",
            job_name="phased-job",
            session_id="session-ph",
            status="running",
            started_at=1000.0,
        )
        store.insert_execution(record)

        phase1 = PhaseRecord(
            name="setup",
            status="success",
            started_at=1000.0,
            ended_at=1001.0,
            duration_ms=1000.0,
        )
        phase2 = PhaseRecord(
            name="execute",
            status="running",
            started_at=1001.0,
        )
        store.insert_phase("exec-ph", phase1)
        store.insert_phase("exec-ph", phase2)

        phases = store.get_execution_phases("exec-ph")
        assert len(phases) == 2
        assert phases[0].name == "setup"
        assert phases[0].status == "success"
        assert phases[0].ended_at == 1001.0
        assert phases[0].duration_ms == 1000.0
        assert phases[1].name == "execute"
        assert phases[1].status == "running"
        assert phases[1].ended_at is None

    def test_phases_ordered_by_start_time(self, store: SQLiteExecutionStore) -> None:
        """Phases are returned in started_at ascending order."""
        record = ExecutionRecord(
            execution_id="exec-order",
            job_name="ordered",
            session_id="session-order",
            status="running",
            started_at=1000.0,
        )
        store.insert_execution(record)

        # Insert out of order
        store.insert_phase(
            "exec-order", PhaseRecord(name="third", status="pending", started_at=1003.0)
        )
        store.insert_phase(
            "exec-order", PhaseRecord(name="first", status="success", started_at=1001.0)
        )
        store.insert_phase(
            "exec-order",
            PhaseRecord(name="second", status="running", started_at=1002.0),
        )

        phases = store.get_execution_phases("exec-order")
        assert [p.name for p in phases] == ["first", "second", "third"]

    def test_phases_empty_for_unknown_execution(
        self, store: SQLiteExecutionStore
    ) -> None:
        """Returns empty list for execution with no phases."""
        phases = store.get_execution_phases("nonexistent-exec")
        assert phases == []

    def test_phases_isolated_per_execution(self, store: SQLiteExecutionStore) -> None:
        """Phases from different executions don't mix."""
        for eid in ("exec-iso-1", "exec-iso-2"):
            record = ExecutionRecord(
                execution_id=eid,
                job_name="iso",
                session_id="session-iso",
                status="running",
                started_at=1000.0,
            )
            store.insert_execution(record)
            store.insert_phase(
                eid, PhaseRecord(name=f"phase-{eid}", status="done", started_at=1000.0)
            )

        phases1 = store.get_execution_phases("exec-iso-1")
        phases2 = store.get_execution_phases("exec-iso-2")
        assert len(phases1) == 1
        assert len(phases2) == 1
        assert phases1[0].name == "phase-exec-iso-1"
        assert phases2[0].name == "phase-exec-iso-2"


class TestContextManager:
    """Tests for context manager usage."""

    def test_context_manager(self, tmp_db: Path) -> None:
        """Store works as a context manager."""
        with SQLiteExecutionStore(db_path=tmp_db) as store:
            record = ExecutionRecord(
                execution_id="ctx-exec",
                job_name="ctx-job",
                session_id="ctx-session",
                status="running",
                started_at=time.time(),
            )
            store.insert_execution(record)
            executions = store.get_session_executions("ctx-session")
            assert len(executions) == 1


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_kwargs_stored_as_none(self, store: SQLiteExecutionStore) -> None:
        """Empty kwargs dict results in NULL in database (not '{}')."""
        record = ExecutionRecord(
            execution_id="exec-empty",
            job_name="empty-job",
            session_id="session-empty",
            status="running",
            started_at=1000.0,
            kwargs={},
        )
        store.insert_execution(record)

        executions = store.get_session_executions("session-empty")
        # Empty dict should round-trip to empty dict
        assert executions[0].kwargs == {}

    def test_none_result(self, store: SQLiteExecutionStore) -> None:
        """None result is handled correctly."""
        record = ExecutionRecord(
            execution_id="exec-none",
            job_name="none-job",
            session_id="session-none",
            status="success",
            started_at=1000.0,
            result=None,
        )
        store.insert_execution(record)

        executions = store.get_session_executions("session-none")
        assert executions[0].result is None

    def test_string_result(self, store: SQLiteExecutionStore) -> None:
        """String result is serialized and deserialized correctly."""
        record = ExecutionRecord(
            execution_id="exec-str",
            job_name="str-job",
            session_id="session-str",
            status="success",
            started_at=1000.0,
            result="hello world",
        )
        store.insert_execution(record)

        executions = store.get_session_executions("session-str")
        assert executions[0].result == "hello world"

    def test_numeric_result(self, store: SQLiteExecutionStore) -> None:
        """Numeric result round-trips correctly."""
        record = ExecutionRecord(
            execution_id="exec-num",
            job_name="num-job",
            session_id="session-num",
            status="success",
            started_at=1000.0,
            result=3.14159,
        )
        store.insert_execution(record)

        executions = store.get_session_executions("session-num")
        assert executions[0].result == 3.14159
