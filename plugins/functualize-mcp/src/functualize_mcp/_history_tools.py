"""MCP tools over the run log: what ran, and what happened inside one run.

`store-substrate`/T6.

These tools used to read an `ExecutionStore` from the retired
`functualize-state` domain, and the way they read it is the clearest argument
for retiring it. `get_job_history` could not simply ask for recent executions —
the protocol had no such method — so it probed for four
(`get_all_executions`, `get_recent_executions`, `get_session_executions` with an
empty session, then with the app's session), taking whichever the installed
backend happened to have. That is what "the intersection of every backend" costs
in practice: a caller guessing at five shapes because the contract cannot
express the one question being asked.

The framework's own run log answers it directly. `job_history` and
`describe_run` are the same projections `func builtin history` and
`func builtin run show` render, so the MCP surface and the CLI now report one
set of facts instead of two.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["MCPHistoryToolRegistry"]

logger = logging.getLogger(__name__)


def _error_response(code: str, message: str) -> dict[str, Any]:
    """The shape every failing tool returns, unchanged from the old tools."""
    return {"error": {"code": code, "message": message}}


class MCPHistoryToolRegistry:
    """Registers the two history tools against a FastMCP server."""

    def __init__(self, app: Any, *, run_store: Any = None) -> None:
        self._app = app
        self._run_store = run_store

    @property
    def run_store(self) -> Any:
        """The run log, on the app's substrate. Resolved on first use.

        Through the engine rather than from the cwd, so the tools read the same
        documents the run wrote — including when a plugin has installed a
        database (`store-substrate`/T5).
        """
        if self._run_store is None:
            from functualize._primitives.run_store import RunStore

            self._run_store = RunStore(self._app.execution_engine.substrate)
        return self._run_store

    def register_tools(self, mcp: Any) -> None:
        """Register both history tools.

        **Unconditional now.** It used to register only if `functualize-state`
        was importable, so the tools were absent on an ordinary install and the
        absence looked like a missing feature. The run log is part of the
        framework; there is nothing to be installed.
        """
        mcp.add_tool(self._get_job_history)
        mcp.add_tool(self._get_execution_detail)
        logger.info("MCPHistoryToolRegistry: Registered 2 history MCP tools")

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _get_job_history(
        self,
        name: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Launches, newest first, optionally filtered by job name."""
        from functualize.app.utils import job_history

        try:
            records = job_history(self.run_store)
        except Exception as exc:
            logger.error("MCPHistoryToolRegistry: could not read history: %s", exc)
            return _error_response("history_error", f"Failed to get job history: {exc}")

        if name:
            records = [r for r in records if r.get("job") == name]
        records = records[:limit]
        return {"executions": records, "count": len(records)}

    _get_job_history.__name__ = "get_job_history"
    _get_job_history.__qualname__ = "get_job_history"
    _get_job_history.__doc__ = (
        "Get run history for jobs. Returns a list of run records with status, "
        "timing, and the surface that started each one. "
        "Args: name — optional job name filter; limit — max records (default 50)."
    )

    async def _get_execution_detail(
        self,
        execution_id: str,
    ) -> dict[str, Any]:
        """One run and the events it emitted, in sequence order."""
        from functualize.app.utils import describe_run, run_events

        try:
            record = describe_run(self.run_store, execution_id)
        except Exception as exc:
            logger.error("MCPHistoryToolRegistry: could not read run: %s", exc)
            return _error_response("history_error", f"Failed to get run: {exc}")

        if record is None:
            return _error_response(
                "execution_not_found", f"No run with id '{execution_id}'."
            )
        return {
            "execution": record,
            # Named `phases` because that is what this tool returned before the
            # port, and an MCP client's tool schema is a published surface.
            # They are the run's events, ordered by the store's sequence rather
            # than by a timestamp, so a replay is correct across two clocks.
            "phases": run_events(self.run_store, execution_id) or [],
        }

    _get_execution_detail.__name__ = "get_execution_detail"
    _get_execution_detail.__qualname__ = "get_execution_detail"
    _get_execution_detail.__doc__ = (
        "Get one run's record and the events it emitted. "
        "Args: execution_id — the run id from get_job_history."
    )
