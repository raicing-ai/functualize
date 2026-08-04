"""Core MCP tools — discover, inspect, and execute functualize jobs.

Provides the five primary tools that external AI agents use to interact
with functualize jobs via MCP:

- discover_jobs: List visible job summaries
- get_job_schema: Get full JSON Schema for a job's config model
- run_job: Execute a job synchronously
- run_job_async: Start a job asynchronously (returns execution_id)
- get_execution_status: Poll async execution state

These tools are registered with the FastMCP instance during server boot.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from functualize_mcp._translator import JobToolTranslator

if TYPE_CHECKING:
    from functualize_mcp._config import MCPConfig

__all__ = ["MCPToolRegistry"]

logger = logging.getLogger(__name__)


@dataclass
class AsyncExecution:
    """Tracks the state of an asynchronous job execution.

    Attributes:
        execution_id: Unique identifier for this execution.
        job_name: Name of the job being executed.
        status: Current status ("running", "success", "failure").
        started_at: Timestamp when execution began.
        ended_at: Timestamp when execution completed, or None if still running.
        duration_ms: Execution duration in milliseconds, or None if still running.
        return_value: Job return value on success, or None.
        error: Error message on failure, or None.
    """

    execution_id: str
    job_name: str
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    duration_ms: float | None = None
    return_value: Any = None
    error: str | None = None


class MCPToolRegistry:
    """Registers and manages core MCP tools for job interaction.

    Provides methods to register the five core tools with a FastMCP instance,
    handling visibility filtering, schema extraction, synchronous execution,
    asynchronous execution, and execution status polling.

    Args:
        app: The FunctualizeApp instance providing job registry and execution.
        config: MCPConfig controlling visibility and filtering.
    """

    def __init__(self, app: Any, *, config: MCPConfig, gate_policy: Any = None) -> None:
        self._app = app
        self._config = config
        self._gate_policy = gate_policy
        self._translator = JobToolTranslator()
        self._async_executions: dict[str, AsyncExecution] = {}
        self._lock = threading.Lock()

    def _gate_refusal(self, job_name: str) -> dict[str, Any] | None:
        """Refusal envelope when a waiting gate forbids running ``job_name``.

        Returns None when nothing is restricted, or when no policy was
        injected (direct callers with no workflow state to consult).

        The policy speaks the workflow tools' flat envelope; this module's
        responses nest under ``error.code``. Translating at the boundary keeps
        each surface internally consistent — a client parsing ``run_job``
        should not have to handle a second error shape for one refusal.
        """
        if self._gate_policy is None or self._gate_policy.permitted(job_name):
            return None
        refusal = self._gate_policy.refusal(job_name)
        response = _error_response("tool_not_permitted", refusal["message"])
        response["allowed_tools"] = refusal.get("allowed_tools", [])
        return response

    def register_tools(self, mcp: Any) -> None:
        """Register all core MCP tools with the FastMCP server instance.

        Args:
            mcp: The FastMCP instance to register tools with.
        """
        mcp.add_tool(self._discover_jobs)
        mcp.add_tool(self._get_job_schema)
        mcp.add_tool(self._run_job)
        mcp.add_tool(self._run_job_async)
        mcp.add_tool(self._get_execution_status)
        logger.info("MCPToolRegistry: Registered 5 core MCP tools")

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _discover_jobs(self) -> dict[str, Any]:
        """Discover available jobs and return their summaries.

        Returns a list of visible job summaries respecting visibility,
        include-tags, and exclude-jobs configuration. Each summary
        contains the job's name, description, and tags.

        Returns:
            Dict with "jobs" key containing list of job summary dicts.
        """
        descriptors = self._app.get_jobs()
        visible = self._translator._filter_descriptors(descriptors, self._config)

        jobs: list[dict[str, Any]] = []
        for descriptor in visible:
            # A job that declares `tty: TTY` needs a real terminal to own. MCP
            # has none, so it could only ever fail here — offering it silently
            # invites a caller to burn a turn discovering that. Mark it
            # not-runnable and say why.
            if _requires_terminal(descriptor):
                continue

            metadata = self._get_metadata(descriptor)
            tags = _get_attr_or_key(metadata, "tags") or []
            description = self._translator._first_paragraph(descriptor.docstring)

            jobs.append(
                {
                    "name": descriptor.name,
                    "description": description,
                    "tags": list(tags),
                }
            )

        return {"jobs": jobs}

    _discover_jobs.__name__ = "discover_jobs"
    _discover_jobs.__qualname__ = "discover_jobs"
    _discover_jobs.__doc__ = (
        "Discover available functualize jobs. Returns a list of visible job "
        "summaries with name, description, and tags. Respects visibility "
        "settings and tag/name filters."
    )

    async def _get_job_schema(self, name: str) -> dict[str, Any]:
        """Get the full JSON Schema for a job's configuration model.

        Args:
            name: The job name to retrieve the schema for.

        Returns:
            Dict with the job's JSON Schema, description, and examples,
            or an error response if the job is not found or not visible.
        """
        # Check if job exists
        descriptor = self._find_job(name)
        if descriptor is None:
            return _error_response(
                "job_not_found",
                f"Job '{name}' does not exist.",
            )

        # Check if job is visible
        if not self._is_visible(descriptor):
            return _error_response(
                "job_not_accessible",
                f"Job '{name}' is not accessible.",
            )

        # Capability floor: a `tty: TTY` job has no terminal to own here.
        if _requires_terminal(descriptor):
            return _not_runnable_response(name)

        # Build and return the schema
        tool_def = self._translator.translate(descriptor)
        metadata = self._get_metadata(descriptor)
        examples = _get_attr_or_key(metadata, "examples") or []

        return {
            "name": name,
            "description": tool_def.description,
            "input_schema": tool_def.input_schema,
            "examples": list(examples),
        }

    _get_job_schema.__name__ = "get_job_schema"
    _get_job_schema.__qualname__ = "get_job_schema"
    _get_job_schema.__doc__ = (
        "Get the full JSON Schema of a job's config model. Returns the "
        "schema with field types, descriptions, defaults, and examples. "
        "Args: name — the job name to inspect."
    )

    async def _run_job(
        self, name: str, config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a job synchronously and return the result.

        Executes the named job via app.execute() with the provided config.
        Missing config fields are resolved from the config chain
        (env vars, config files, defaults).

        Args:
            name: The job name to execute.
            config: Optional partial configuration dict. Missing fields
                are resolved from the config chain.

        Returns:
            Dict with status, return_value, and duration_ms on success,
            or an error response on failure.
        """
        # Check if job exists
        descriptor = self._find_job(name)
        if descriptor is None:
            return _error_response(
                "job_not_found",
                f"Job '{name}' does not exist.",
            )

        # Check if job is visible
        if not self._is_visible(descriptor):
            return _error_response(
                "job_not_accessible",
                f"Job '{name}' is not accessible.",
            )

        # Capability floor: a `tty: TTY` job has no terminal to own here.
        if _requires_terminal(descriptor):
            return _not_runnable_response(name)

        # `run_job` is a generic door to the same room the per-job tools open,
        # so it takes the same lock. Without this an agent refused `deploy` as
        # a tool just calls run_job("deploy") and the gate policy is theatre.
        refusal = self._gate_refusal(name)
        if refusal is not None:
            return refusal

        # Execute
        kwargs = config or {}
        try:
            result = self._app.execute(name, **kwargs)
            return {
                "status": result.status
                if isinstance(result.status, str)
                else result.status.value,
                "return_value": result.return_value,
                "duration_ms": result.duration_ms,
            }
        except Exception as e:
            logger.error("MCPToolRegistry: Error executing job '%s': %s", name, e)
            return _error_response(
                "execution_error",
                f"Job '{name}' execution failed: {e}",
            )

    _run_job.__name__ = "run_job"
    _run_job.__qualname__ = "run_job"
    _run_job.__doc__ = (
        "Execute a functualize job synchronously. Returns the result with "
        "status, return_value, and duration_ms. Missing config fields are "
        "resolved from the config chain. "
        "Args: name — job name; config — optional partial config dict."
    )

    async def _run_job_async(
        self, name: str, config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Start a job asynchronously and return an execution_id.

        Launches the job in a background thread, allowing the caller
        to poll progress via get_execution_status.

        Args:
            name: The job name to execute.
            config: Optional partial configuration dict.

        Returns:
            Dict with execution_id on success, or an error response.
        """
        # Check if job exists
        descriptor = self._find_job(name)
        if descriptor is None:
            return _error_response(
                "job_not_found",
                f"Job '{name}' does not exist.",
            )

        # Check if job is visible
        if not self._is_visible(descriptor):
            return _error_response(
                "job_not_accessible",
                f"Job '{name}' is not accessible.",
            )

        # Capability floor: a `tty: TTY` job has no terminal to own here.
        if _requires_terminal(descriptor):
            return _not_runnable_response(name)

        # Same lock as run_job — an async door is still a door.
        refusal = self._gate_refusal(name)
        if refusal is not None:
            return refusal

        # Create async execution record
        execution_id = uuid.uuid4().hex[:16]
        execution = AsyncExecution(
            execution_id=execution_id,
            job_name=name,
        )

        with self._lock:
            self._async_executions[execution_id] = execution

        # Launch in background thread
        kwargs = config or {}
        thread = threading.Thread(
            target=self._run_async_worker,
            args=(execution_id, name, kwargs),
            daemon=True,
            name=f"mcp-async-{execution_id}",
        )
        thread.start()

        return {"execution_id": execution_id}

    _run_job_async.__name__ = "run_job_async"
    _run_job_async.__qualname__ = "run_job_async"
    _run_job_async.__doc__ = (
        "Start a functualize job asynchronously. Returns an execution_id "
        "that can be used with get_execution_status to poll progress. "
        "Args: name — job name; config — optional partial config dict."
    )

    async def _get_execution_status(self, execution_id: str) -> dict[str, Any]:
        """Get the current status of an async execution.

        Args:
            execution_id: The execution ID returned by run_job_async.

        Returns:
            Dict with execution_id, status, and progress information,
            or an error response if the execution is not found.
        """
        with self._lock:
            execution = self._async_executions.get(execution_id)

        if execution is None:
            return _error_response(
                "execution_not_found",
                f"Execution '{execution_id}' does not exist.",
            )

        result: dict[str, Any] = {
            "execution_id": execution.execution_id,
            "job_name": execution.job_name,
            "status": execution.status,
            "started_at": execution.started_at,
        }

        if execution.ended_at is not None:
            result["ended_at"] = execution.ended_at
        if execution.duration_ms is not None:
            result["duration_ms"] = execution.duration_ms
        if execution.return_value is not None:
            result["return_value"] = execution.return_value
        if execution.error is not None:
            result["error"] = execution.error

        return result

    _get_execution_status.__name__ = "get_execution_status"
    _get_execution_status.__qualname__ = "get_execution_status"
    _get_execution_status.__doc__ = (
        "Get the status of an async job execution. Returns execution_id, "
        "status, duration, and result when complete. "
        "Args: execution_id — the ID returned by run_job_async."
    )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_async_worker(
        self, execution_id: str, job_name: str, kwargs: dict[str, Any]
    ) -> None:
        """Background worker that executes a job and updates execution state.

        Args:
            execution_id: ID of the async execution to update.
            job_name: Name of the job to execute.
            kwargs: Arguments to pass to the job.
        """
        start_time = time.time()
        try:
            result = self._app.execute(job_name, **kwargs)
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000

            with self._lock:
                execution = self._async_executions[execution_id]
                execution.status = (
                    result.status
                    if isinstance(result.status, str)
                    else result.status.value
                )
                execution.return_value = result.return_value
                execution.ended_at = end_time
                execution.duration_ms = duration_ms

        except Exception as e:
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000
            logger.error(
                "MCPToolRegistry: Async execution '%s' failed: %s",
                execution_id,
                e,
            )
            with self._lock:
                execution = self._async_executions[execution_id]
                execution.status = "failure"
                execution.error = str(e)
                execution.ended_at = end_time
                execution.duration_ms = duration_ms

    def _find_job(self, name: str) -> Any | None:
        """Find a job descriptor by name.

        Args:
            name: Job name to look up.

        Returns:
            The JobDescriptor if found, or None.
        """
        job = self._app.get_job(name) if hasattr(self._app, "get_job") else None
        if job is not None:
            return job

        # Fallback: linear scan
        for descriptor in self._app.get_jobs():
            if descriptor.name == name:
                return descriptor
        return None

    def _is_visible(self, descriptor: Any) -> bool:
        """Check if a job descriptor is visible given the current config.

        A job is not visible if:
        - It has visibility="internal"
        - It is in config.exclude_jobs
        - It has a tag in config.exclude_tags
        - config.include_tags is non-empty and it lacks a matching tag

        Args:
            descriptor: The job descriptor to check.

        Returns:
            True if the job is visible, False otherwise.
        """
        filtered = self._translator._filter_descriptors([descriptor], self._config)
        return len(filtered) > 0

    def _get_metadata(self, descriptor: Any) -> Any:
        """Get the @job declaration for tags/examples/visibility. Empty dict
        when the job is convention-discovered (no declaration)."""
        declaration = getattr(descriptor, "declaration", None)
        if declaration is None:
            return {}
        return declaration


def _get_attr_or_key(obj: Any, name: str) -> Any:
    """Get a value from an object by attribute or dict key.

    Handles both SimpleNamespace/dataclass-style objects and dicts.
    Returns None if the attribute/key doesn't exist.
    """
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _requires_terminal(descriptor: Any) -> bool:
    """Whether a job declares a hard ``tty: TTY`` requirement.

    Such a job takes over a real terminal; MCP has none to give, so it is not
    runnable over this transport and must not be offered as if it were.
    """
    return bool(getattr(descriptor, "requires_tty", False))


def _not_runnable_response(name: str) -> dict[str, Any]:
    """The refusal for a terminal-owning job, mirroring the CLI's floor."""
    return _error_response(
        "job_not_runnable",
        f"Job '{name}' requires an interactive terminal (it declares "
        f"`tty: TTY`) and cannot run over MCP. Run it directly with "
        f"`func {name}` in a terminal.",
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
