"""Unit tests for MCPHistoryToolRegistry — MCP history query tools.

Tests get_job_history and get_execution_detail tools with conditional
exposure and error handling.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from functualize_mcp._history_tools import MCPHistoryToolRegistry

# ---------------------------------------------------------------------------
# Test helpers — minimal fakes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeExecutionRecord:
    """Fake ExecutionRecord for testing."""

    execution_id: str
    job_name: str
    session_id: str
    status: str
    started_at: float
    ended_at: float | None = None
    duration_ms: float | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass(frozen=True)
class FakePhaseRecord:
    """Fake PhaseRecord for testing."""

    name: str
    status: str
    started_at: float
    ended_at: float | None = None
    duration_ms: float | None = None


class FakeExecutionStore:
    """Fake ExecutionStore for testing history tools."""

    def __init__(self, executions: list[FakeExecutionRecord] | None = None) -> None:
        self._executions = executions or []
        self._phases: dict[str, list[FakePhaseRecord]] = {}

    def get_session_executions(
        self, session_id: str, limit: int = 50
    ) -> list[FakeExecutionRecord]:
        # Return all executions regardless of session for testing
        return self._executions[:limit]

    def get_execution_phases(self, execution_id: str) -> list[FakePhaseRecord]:
        return self._phases.get(execution_id, [])

    def get_execution(self, execution_id: str) -> FakeExecutionRecord | None:
        for e in self._executions:
            if e.execution_id == execution_id:
                return e
        return None

    def get_all_executions(self, limit: int = 50) -> list[FakeExecutionRecord]:
        return self._executions[:limit]

    def add_phases(self, execution_id: str, phases: list[FakePhaseRecord]) -> None:
        self._phases[execution_id] = phases


class FakeApp:
    """Minimal fake FunctualizeApp for testing MCPHistoryToolRegistry."""

    def __init__(self, execution_store: Any = None) -> None:
        self._execution_store = execution_store
        self.session_id = "test-session-001"

    def resolve(self, cls: type) -> Any:
        from functualize_state import ExecutionStore

        if cls is ExecutionStore and self._execution_store is not None:
            return self._execution_store
        raise KeyError(f"No provider for {cls}")


class FakeMCP:
    """Fake FastMCP that tracks registered tools."""

    def __init__(self) -> None:
        self.tools: list[Any] = []

    def add_tool(self, fn: Any) -> None:
        self.tools.append(fn)


# ---------------------------------------------------------------------------
# Tests for conditional registration
# ---------------------------------------------------------------------------


class TestHistoryToolRegistration:
    """Tests for conditional history tool registration."""

    def test_registers_tools_when_state_domain_available(self):
        """History tools are registered when functualize-state is importable."""
        store = FakeExecutionStore()
        app = FakeApp(execution_store=store)
        registry = MCPHistoryToolRegistry(app)
        mcp = FakeMCP()

        registry.register_tools(mcp)

        # functualize-state is installed in the workspace
        assert len(mcp.tools) == 2
        tool_names = [t.__name__ for t in mcp.tools]
        assert "get_job_history" in tool_names
        assert "get_execution_detail" in tool_names


# ---------------------------------------------------------------------------
# Tests for get_job_history
# ---------------------------------------------------------------------------


class TestGetJobHistory:
    """Tests for the get_job_history tool."""

    def test_returns_execution_history(self):
        """get_job_history returns execution records."""
        executions = [
            FakeExecutionRecord(
                execution_id="exec-001",
                job_name="deploy",
                session_id="session-1",
                status="success",
                started_at=1000.0,
                ended_at=1005.0,
                duration_ms=5000.0,
            ),
            FakeExecutionRecord(
                execution_id="exec-002",
                job_name="test",
                session_id="session-1",
                status="failure",
                started_at=2000.0,
                ended_at=2003.0,
                duration_ms=3000.0,
            ),
        ]
        store = FakeExecutionStore(executions=executions)
        app = FakeApp(execution_store=store)
        registry = MCPHistoryToolRegistry(app)

        result = asyncio.run(registry._get_job_history())

        assert "executions" in result
        assert result["count"] == 2
        assert result["executions"][0]["execution_id"] == "exec-001"
        assert result["executions"][1]["execution_id"] == "exec-002"

    def test_filters_by_job_name(self):
        """get_job_history filters by job name when provided."""
        executions = [
            FakeExecutionRecord(
                execution_id="exec-001",
                job_name="deploy",
                session_id="session-1",
                status="success",
                started_at=1000.0,
            ),
            FakeExecutionRecord(
                execution_id="exec-002",
                job_name="test",
                session_id="session-1",
                status="success",
                started_at=2000.0,
            ),
            FakeExecutionRecord(
                execution_id="exec-003",
                job_name="deploy",
                session_id="session-1",
                status="failure",
                started_at=3000.0,
            ),
        ]
        store = FakeExecutionStore(executions=executions)
        app = FakeApp(execution_store=store)
        registry = MCPHistoryToolRegistry(app)

        result = asyncio.run(registry._get_job_history(name="deploy"))

        assert result["count"] == 2
        for e in result["executions"]:
            assert e["job_name"] == "deploy"

    def test_respects_limit(self):
        """get_job_history respects the limit parameter."""
        executions = [
            FakeExecutionRecord(
                execution_id=f"exec-{i:03d}",
                job_name="job",
                session_id="session-1",
                status="success",
                started_at=float(i * 1000),
            )
            for i in range(10)
        ]
        store = FakeExecutionStore(executions=executions)
        app = FakeApp(execution_store=store)
        registry = MCPHistoryToolRegistry(app)

        result = asyncio.run(registry._get_job_history(limit=3))

        assert result["count"] == 3

    def test_returns_empty_when_no_history(self):
        """get_job_history returns empty list with no executions."""
        store = FakeExecutionStore(executions=[])
        app = FakeApp(execution_store=store)
        registry = MCPHistoryToolRegistry(app)

        result = asyncio.run(registry._get_job_history())

        assert result["count"] == 0
        assert result["executions"] == []

    def test_returns_error_when_store_not_available(self):
        """get_job_history returns error when no ExecutionStore."""
        app = FakeApp(execution_store=None)
        registry = MCPHistoryToolRegistry(app)

        result = asyncio.run(registry._get_job_history())

        assert "error" in result
        assert result["error"]["code"] == "state_not_available"


# ---------------------------------------------------------------------------
# Tests for get_execution_detail
# ---------------------------------------------------------------------------


class TestGetExecutionDetail:
    """Tests for the get_execution_detail tool."""

    def test_returns_execution_with_phases(self):
        """get_execution_detail returns execution record and its phases."""
        executions = [
            FakeExecutionRecord(
                execution_id="exec-001",
                job_name="deploy",
                session_id="session-1",
                status="success",
                started_at=1000.0,
                ended_at=1010.0,
                duration_ms=10000.0,
                kwargs={"env": "prod"},
                result={"deployed": True},
            ),
        ]
        phases = [
            FakePhaseRecord(
                name="validate",
                status="success",
                started_at=1000.0,
                ended_at=1003.0,
                duration_ms=3000.0,
            ),
            FakePhaseRecord(
                name="apply",
                status="success",
                started_at=1003.0,
                ended_at=1010.0,
                duration_ms=7000.0,
            ),
        ]
        store = FakeExecutionStore(executions=executions)
        store.add_phases("exec-001", phases)
        app = FakeApp(execution_store=store)
        registry = MCPHistoryToolRegistry(app)

        result = asyncio.run(registry._get_execution_detail("exec-001"))

        assert "execution" in result
        assert result["execution"]["execution_id"] == "exec-001"
        assert result["execution"]["job_name"] == "deploy"
        assert result["execution"]["status"] == "success"
        assert result["execution"]["kwargs"] == {"env": "prod"}
        assert result["execution"]["result"] == {"deployed": True}

        assert "phases" in result
        assert len(result["phases"]) == 2
        assert result["phases"][0]["name"] == "validate"
        assert result["phases"][1]["name"] == "apply"

    def test_returns_error_for_nonexistent_execution(self):
        """get_execution_detail returns error for unknown execution_id."""
        store = FakeExecutionStore(executions=[])
        app = FakeApp(execution_store=store)
        registry = MCPHistoryToolRegistry(app)

        result = asyncio.run(registry._get_execution_detail("nonexistent"))

        assert "error" in result
        assert result["error"]["code"] == "execution_not_found"

    def test_returns_error_when_store_not_available(self):
        """get_execution_detail returns error when no ExecutionStore."""
        app = FakeApp(execution_store=None)
        registry = MCPHistoryToolRegistry(app)

        result = asyncio.run(registry._get_execution_detail("exec-001"))

        assert "error" in result
        assert result["error"]["code"] == "state_not_available"

    def test_returns_execution_even_without_phases(self):
        """get_execution_detail returns execution even when no phases."""
        executions = [
            FakeExecutionRecord(
                execution_id="exec-001",
                job_name="simple_job",
                session_id="session-1",
                status="success",
                started_at=1000.0,
            ),
        ]
        store = FakeExecutionStore(executions=executions)
        app = FakeApp(execution_store=store)
        registry = MCPHistoryToolRegistry(app)

        result = asyncio.run(registry._get_execution_detail("exec-001"))

        assert "execution" in result
        assert result["execution"]["execution_id"] == "exec-001"
        assert result["phases"] == []
