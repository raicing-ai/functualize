"""MCP History tools — query execution history via MCP when the State domain is active.

Provides get_job_history and get_execution_detail MCP tools.
These tools are conditionally exposed only when the functualize-state
domain SDK is installed.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import asdict
from typing import Any

__all__ = ["MCPHistoryToolRegistry"]

logger = logging.getLogger(__name__)


def _execution_record_to_dict(record: Any) -> dict[str, Any]:
    """Convert an ExecutionRecord to a serializable dict.

    Args:
        record: An ExecutionRecord instance.

    Returns:
        A dict representation suitable for MCP responses.
    """
    data = asdict(record)
    return data


def _phase_record_to_dict(phase: Any) -> dict[str, Any]:
    """Convert a PhaseRecord to a serializable dict.

    Args:
        phase: A PhaseRecord instance.

    Returns:
        A dict representation suitable for MCP responses.
    """
    data = asdict(phase)
    return data


class MCPHistoryToolRegistry:
    """Registers MCP history tools when the State domain is available.

    Tools are only registered if the functualize-state package can be
    imported. This ensures the MCP server doesn't fail when the State
    domain is not installed.

    Args:
        app: The FunctualizeApp instance providing DI and job registry.
    """

    def __init__(self, app: Any) -> None:
        self._app = app
        self._execution_store: Any = None

    def _get_execution_store(self) -> Any:
        """Resolve the ExecutionStore from the app's DI registry.

        Returns:
            The ExecutionStore instance, or None if unavailable.
        """
        if self._execution_store is not None:
            return self._execution_store

        try:
            from functualize_state import ExecutionStore

            # Try to resolve from DI
            if hasattr(self._app, "resolve"):
                self._execution_store = self._app.resolve(ExecutionStore)
        except Exception:
            pass

        return self._execution_store

    def register_tools(self, mcp: Any) -> None:
        """Register history MCP tools with the FastMCP server instance.

        Only registers if functualize-state is importable.

        Args:
            mcp: The FastMCP instance to register tools with.
        """
        try:
            from functualize_state import ExecutionStore  # noqa: F401
        except ImportError:
            logger.debug(
                "MCPHistoryToolRegistry: functualize-state not installed, "
                "skipping history tool registration."
            )
            return

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
        """Get execution history, optionally filtered by job name.

        Args:
            name: Optional job name to filter history by.
            limit: Maximum number of records to return (default 50).

        Returns:
            Dict with "executions" key containing list of execution record dicts.
        """
        store = self._get_execution_store()
        if store is None:
            return _error_response(
                "state_not_available",
                "State domain is not available. Install functualize-state-sqlite "
                "for execution history.",
            )

        try:
            # The ExecutionStore protocol uses session-based querying.
            # We query with a broad session or use available methods.
            # Try to get executions — some implementations may support
            # a get_all or similar method.
            executions: list[Any] = []

            if hasattr(store, "get_all_executions"):
                # Extended method that some implementations may provide
                executions = store.get_all_executions(limit=limit)
            elif hasattr(store, "get_session_executions"):
                # Standard protocol method — try with a wildcard session
                # We need to find recent sessions and aggregate
                if hasattr(store, "get_recent_executions"):
                    executions = store.get_recent_executions(limit=limit)
                elif hasattr(store, "get_session_executions"):
                    # Use session_id="" or a known session to get executions
                    # Some backends support empty session for "all"
                    try:
                        executions = store.get_session_executions("", limit=limit)
                    except Exception:
                        # Fallback: try to get from app's current session
                        session_id = getattr(self._app, "session_id", None) or ""
                        if session_id:
                            executions = store.get_session_executions(
                                session_id, limit=limit
                            )

            # Filter by job name if specified
            if name and executions:
                executions = [
                    e for e in executions if getattr(e, "job_name", None) == name
                ]

            # Apply limit
            executions = executions[:limit]

            return {
                "executions": [_execution_record_to_dict(e) for e in executions],
                "count": len(executions),
            }
        except Exception as e:
            logger.error("MCPHistoryToolRegistry: Error getting job history: %s", e)
            return _error_response("history_error", f"Failed to get job history: {e}")

    _get_job_history.__name__ = "get_job_history"
    _get_job_history.__qualname__ = "get_job_history"
    _get_job_history.__doc__ = (
        "Get execution history for jobs. Returns a list of execution records "
        "with status, duration, and results. "
        "Args: name — optional job name filter; limit — max records (default 50)."
    )

    async def _get_execution_detail(
        self,
        execution_id: str,
    ) -> dict[str, Any]:
        """Get detailed information about a specific execution.

        Returns the execution record and its phase records.

        Args:
            execution_id: The execution ID to look up.

        Returns:
            Dict with execution details and phases, or an error response.
        """
        store = self._get_execution_store()
        if store is None:
            return _error_response(
                "state_not_available",
                "State domain is not available. Install functualize-state-sqlite "
                "for execution history.",
            )

        try:
            # Get the execution record
            execution = None

            if hasattr(store, "get_execution"):
                execution = store.get_execution(execution_id)
            elif hasattr(store, "get_session_executions") and hasattr(
                store, "get_recent_executions"
            ):
                # Fallback: search through sessions by scanning recent records
                all_execs = store.get_recent_executions(limit=1000)
                execution = next(
                    (e for e in all_execs if e.execution_id == execution_id),
                    None,
                )

            if execution is None:
                return _error_response(
                    "execution_not_found",
                    f"Execution '{execution_id}' does not exist.",
                )

            # Get phase records for this execution
            phases: list[Any] = []
            with contextlib.suppress(Exception):
                phases = store.get_execution_phases(execution_id)

            return {
                "execution": _execution_record_to_dict(execution),
                "phases": [_phase_record_to_dict(p) for p in phases],
            }
        except Exception as e:
            if "not found" in str(e).lower():
                return _error_response(
                    "execution_not_found",
                    f"Execution '{execution_id}' does not exist.",
                )
            logger.error(
                "MCPHistoryToolRegistry: Error getting execution detail: %s", e
            )
            return _error_response(
                "history_error", f"Failed to get execution detail: {e}"
            )

    _get_execution_detail.__name__ = "get_execution_detail"
    _get_execution_detail.__qualname__ = "get_execution_detail"
    _get_execution_detail.__doc__ = (
        "Get detailed information about a specific execution including phases. "
        "Returns execution record with status, duration, args, result, and "
        "a list of execution phases. "
        "Args: execution_id — the execution ID to look up."
    )


def _error_response(error_code: str, message: str) -> dict[str, Any]:
    """Build a structured error response dict.

    Args:
        error_code: Machine-readable error code.
        message: Human-readable error message.

    Returns:
        Dict with "error" key containing code and message.
    """
    return {
        "error": {
            "code": error_code,
            "message": message,
        }
    }
