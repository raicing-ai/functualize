"""The MCP history tools, reading the run log.

`store-substrate`/T6.

These tools used to read an `ExecutionStore` from the retired
`functualize-state` domain, and were tested against a fake that implemented
four different query methods — because the tool probed for four, the protocol
having none of them by name. The fake was therefore more capable than any real
backend, and the tests could not tell which of the four paths a given install
would take.

Now they read the framework's own run log, so these tests use a **real**
`RunStore` on a temporary substrate. That is the point of the port: there is one
answer to "what ran", and both the CLI and MCP render it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from functualize_mcp._history_tools import MCPHistoryToolRegistry

from functualize._primitives.run_store import RunStore
from functualize._primitives.substrate import JsonFileSubstrate


class _RecordingMCP:
    """Collects what `register_tools` adds."""

    def __init__(self) -> None:
        self.tools: list[Any] = []

    def add_tool(self, tool: Any) -> None:
        self.tools.append(tool)


@pytest.fixture
def runs(tmp_path: Path) -> RunStore:
    return RunStore(JsonFileSubstrate(tmp_path))


@pytest.fixture
def registry(runs: RunStore) -> MCPHistoryToolRegistry:
    """Built with the store injected, so no app is needed.

    The injection point exists for the server, which builds one per session;
    here it is what lets a unit test use a real store instead of a fake app.
    """
    return MCPHistoryToolRegistry(app=None, run_store=runs)


def _launch(runs: RunStore, job: str, status: str = "success") -> str:
    """A run as a user's own launch — what `job_history` reports.

    `surface` matters: history is the launches, not every nested and parallel
    run the log also holds, and the projection decides that from the record.
    """
    run_id = runs.open_run({"job": job, "surface": "func.job"})
    runs.close_run(run_id, status)
    return run_id


class TestRegistration:
    def test_both_tools_are_registered(self, registry: MCPHistoryToolRegistry) -> None:
        mcp = _RecordingMCP()
        registry.register_tools(mcp)
        assert [t.__name__ for t in mcp.tools] == [
            "get_job_history",
            "get_execution_detail",
        ]

    def test_registration_is_unconditional(
        self, registry: MCPHistoryToolRegistry
    ) -> None:
        """It used to depend on `functualize-state` being importable.

        So on an ordinary install the tools were simply absent, and the absence
        looked like a missing feature rather than a missing package. The run log
        is part of the framework; there is nothing to install.
        """
        mcp = _RecordingMCP()
        registry.register_tools(mcp)
        assert len(mcp.tools) == 2


class TestGetJobHistory:
    def test_it_returns_what_was_launched(
        self, registry: MCPHistoryToolRegistry, runs: RunStore
    ) -> None:
        _launch(runs, "build")
        _launch(runs, "deploy")

        result = asyncio.run(registry._get_job_history())  # noqa: SLF001

        assert result["count"] == 2
        assert {r["job"] for r in result["executions"]} == {"build", "deploy"}

    def test_it_is_empty_when_nothing_has_run(
        self, registry: MCPHistoryToolRegistry
    ) -> None:
        result = asyncio.run(registry._get_job_history())  # noqa: SLF001
        assert result == {"executions": [], "count": 0}

    def test_it_filters_by_job_name(
        self, registry: MCPHistoryToolRegistry, runs: RunStore
    ) -> None:
        _launch(runs, "build")
        _launch(runs, "deploy")

        result = asyncio.run(registry._get_job_history(name="build"))  # noqa: SLF001

        assert result["count"] == 1
        assert result["executions"][0]["job"] == "build"

    def test_it_respects_the_limit(
        self, registry: MCPHistoryToolRegistry, runs: RunStore
    ) -> None:
        for i in range(5):
            _launch(runs, f"job-{i}")

        result = asyncio.run(registry._get_job_history(limit=2))  # noqa: SLF001

        assert result["count"] == 2

    def test_it_carries_the_status(
        self, registry: MCPHistoryToolRegistry, runs: RunStore
    ) -> None:
        _launch(runs, "build", status="failure")
        result = asyncio.run(registry._get_job_history())  # noqa: SLF001
        assert result["executions"][0]["status"] == "failure"


class TestGetExecutionDetail:
    def test_it_returns_the_run(
        self, registry: MCPHistoryToolRegistry, runs: RunStore
    ) -> None:
        run_id = _launch(runs, "build")

        result = asyncio.run(registry._get_execution_detail(run_id))  # noqa: SLF001

        assert result["execution"]["job"] == "build"
        assert result["execution"]["status"] == "success"

    def test_a_run_with_no_events_still_answers(
        self, registry: MCPHistoryToolRegistry, runs: RunStore
    ) -> None:
        """`[]` and "no such run" are different answers, and a client needs both."""
        run_id = _launch(runs, "build")

        result = asyncio.run(registry._get_execution_detail(run_id))  # noqa: SLF001

        assert result["phases"] == []
        assert "error" not in result

    def test_it_returns_the_events_in_sequence_order(
        self, registry: MCPHistoryToolRegistry, runs: RunStore
    ) -> None:
        """Ordered by the store's sequence, never by timestamp.

        The sequence is monotonic per run, so a replay is correct across two
        processes on two clocks — which timestamps cannot promise.
        """
        run_id = _launch(runs, "build")
        for name in ("job.execute.start", "job.execute.end"):
            runs.append_event(run_id, {"event_name": name})

        result = asyncio.run(registry._get_execution_detail(run_id))  # noqa: SLF001

        assert [e["event_name"] for e in result["phases"]] == [
            "job.execute.start",
            "job.execute.end",
        ]

    def test_an_unknown_run_is_an_error_not_an_empty_answer(
        self, registry: MCPHistoryToolRegistry
    ) -> None:
        result = asyncio.run(registry._get_execution_detail("nope"))  # noqa: SLF001
        assert result["error"]["code"] == "execution_not_found"


class TestItReadsTheAppsSubstrate:
    def test_the_store_is_resolved_through_the_engine(self, tmp_path: Path) -> None:
        """Not from the cwd — so a database plugin's documents are what it reads.

        Resolving independently is how the MCP surface and the run that wrote
        the records could end up reading different backends, which is the
        failure `store-substrate` exists to remove.
        """
        substrate = JsonFileSubstrate(tmp_path)

        class _Engine:
            pass

        engine = _Engine()
        engine.substrate = substrate  # type: ignore[attr-defined]

        class _App:
            execution_engine = engine

        registry = MCPHistoryToolRegistry(app=_App())
        assert registry.run_store.substrate is substrate
