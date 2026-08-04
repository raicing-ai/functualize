"""Execution State Plugin — entry point integrating with functualize lifecycle hooks.

Hooks into APP_READY, BEFORE_JOB, AFTER_SUCCESS, AFTER_FAILURE, ON_TEARDOWN,
INVOKE_START, INVOKE_END, and ON_SCOPE_CREATED to persist execution history
and provide SQLite-backed state storage.

Implements PluginConfigProtocol (name, version, description, __call__) and
PluginWithShutdown (on_shutdown) for graceful resource cleanup.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from functualize_state_sqlite.sqlite_backend import SQLiteBackend
from functualize_state_sqlite.state_store import SQLiteStateStore
from functualize_state_sqlite.tracker import ExecutionTracker

__all__ = ["ExecutionStatePlugin"]

logger = logging.getLogger(__name__)


class ExecutionStateConfig(BaseModel):
    """Configuration for the execution state plugin."""

    db_path: str | None = Field(
        default=None,
        description="Path to the SQLite database file. Defaults to .functualize/execution.db",
    )
    session_ttl: float = Field(
        default=1800.0,
        description="Session TTL in seconds before a new session is created (default 30min)",
    )


class ExecutionStatePlugin:
    """SQLite-backed execution tracking and persistent state plugin.

    Registers lifecycle hooks to automatically track job executions,
    persist state across process restarts, and provide AI context summaries.

    Implements PluginConfigProtocol + PluginWithShutdown.
    """

    name: str = "execution-state"
    version: str = "0.1.0"
    description: str = "SQLite-backed execution tracking and persistent state"
    config_model = ExecutionStateConfig
    config_section: str = "plugin.execution-state"

    def __init__(self) -> None:
        self._backend: SQLiteBackend | None = None
        self._tracker: ExecutionTracker | None = None
        self._app: Any = None
        # Track parent_uid for nested invocations via INVOKE_START/INVOKE_END
        self._invoke_parent_stack: list[str] = []
        # Maps rc id -> execution_uid for retrieval in AFTER hooks
        self._rc_execution_map: dict[int, str] = {}

    @property
    def backend(self) -> SQLiteBackend | None:
        """The SQLiteBackend instance (available after APP_READY)."""
        return self._backend

    @property
    def tracker(self) -> ExecutionTracker | None:
        """The ExecutionTracker instance (available after APP_READY)."""
        return self._tracker

    def __call__(self, app: Any) -> None:
        """Register the plugin with the application instance.

        Hooks into: APP_READY, BEFORE_JOB, AFTER_SUCCESS, AFTER_FAILURE,
        ON_TEARDOWN, INVOKE_START, INVOKE_END, ON_SCOPE_CREATED.
        """
        self._app = app
        hook_registry = app.hook_registry

        from functualize._events.hooks import HookEvent

        # APP_READY: initialize DB
        hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)

        # BEFORE_JOB: record execution start
        hook_registry.register_global(HookEvent.BEFORE_JOB, self._on_before_job)

        # AFTER_SUCCESS: record successful completion
        hook_registry.register_global(HookEvent.AFTER_SUCCESS, self._on_after_success)

        # AFTER_FAILURE: record failed completion
        hook_registry.register_global(HookEvent.AFTER_FAILURE, self._on_after_failure)

        # ON_TEARDOWN: finalize execution (no-op currently, reserved for future)
        hook_registry.register_global(HookEvent.ON_TEARDOWN, self._on_teardown)

        # INVOKE_START / INVOKE_END: track nested invocations
        hook_registry.register_global(HookEvent.INVOKE_START, self._on_invoke_start)
        hook_registry.register_global(HookEvent.INVOKE_END, self._on_invoke_end)

        # ON_SCOPE_CREATED: replace state store with SQLiteStateStore
        hook_registry.register_global(
            HookEvent.ON_SCOPE_CREATED, self._on_scope_created
        )

    def on_shutdown(self, app: Any) -> None:
        """Close the SQLiteBackend on application shutdown."""
        if self._backend is not None:
            try:
                self._backend.close()
                logger.debug("ExecutionStatePlugin: SQLiteBackend closed.")
            except Exception as e:
                logger.error("ExecutionStatePlugin: Error closing backend: %s", e)
            finally:
                self._backend = None
                self._tracker = None

    # ─── Hook Handlers ────────────────────────────────────────────────

    def _on_app_ready(self, app: Any) -> None:
        """Initialize the SQLiteBackend and ExecutionTracker on app boot."""
        try:
            db_path = None
            # Try to resolve config if available
            try:
                config = app.resolve_model(self.config_section, self.config_model)
                if config.db_path:
                    db_path = config.db_path
                session_ttl = config.session_ttl
            except Exception:
                # Config resolution may fail if no config file exists
                session_ttl = 1800.0

            self._backend = SQLiteBackend(db_path=db_path)
            self._backend.initialize()

            self._tracker = ExecutionTracker(
                self._backend,
                session_ttl=session_ttl,
            )

            logger.debug(
                "ExecutionStatePlugin initialized (db=%s)",
                self._backend.db_path,
            )
        except Exception as e:
            logger.error("ExecutionStatePlugin: Failed to initialize backend: %s", e)

    def _on_before_job(self, rc: Any, **hook_kwargs: Any) -> None:
        """Record execution start and attach execution_uid to rc metadata."""
        if self._tracker is None:
            return

        try:
            job_name = rc.name

            # Determine parent_uid from the invoke parent stack.
            # When a parent invokes a child, INVOKE_START pushes the parent's
            # execution_uid onto the stack. Then the child's BEFORE_JOB fires,
            # and we read the top of that stack as the parent_uid.
            parent_uid: str | None = None
            depth = 0
            if self._invoke_parent_stack:
                parent_uid = self._invoke_parent_stack[-1]
                depth = len(self._invoke_parent_stack)

            # Serialize kwargs if provided
            kwargs_json: str | None = None
            raw_kwargs = hook_kwargs.get("kwargs")
            if raw_kwargs is not None:
                kwargs_json = _safe_serialize(raw_kwargs)

            # Record the start
            execution_uid = self._tracker.record_start(
                job_name,
                kwargs_json=kwargs_json,
                parent_uid=parent_uid,
                depth=depth,
            )

            # Attach execution_uid to RunContext result metadata
            rc.set_result_metadata("execution_uid", execution_uid)

            # Store execution_uid for retrieval in AFTER hooks
            self._rc_execution_map[id(rc)] = execution_uid

        except Exception as e:
            logger.error("ExecutionStatePlugin: Error in BEFORE_JOB handler: %s", e)

    def _on_after_success(self, rc: Any, **hook_kwargs: Any) -> None:
        """Record successful execution end."""
        if self._tracker is None:
            return

        try:
            execution_uid = self._get_execution_uid(rc)
            if execution_uid is None:
                return

            result = hook_kwargs.get("result")
            result_json = _safe_serialize(result)

            # Calculate duration from rc if available
            duration_ms = _get_duration_ms(rc)

            self._tracker.record_end(
                execution_uid,
                status="success",
                duration_ms=duration_ms,
                result_json=result_json,
            )
        except Exception as e:
            logger.error("ExecutionStatePlugin: Error in AFTER_SUCCESS handler: %s", e)

    def _on_after_failure(self, rc: Any, exception: Exception | None = None) -> None:
        """Record failed execution end."""
        if self._tracker is None:
            return

        try:
            execution_uid = self._get_execution_uid(rc)
            if execution_uid is None:
                return

            error_message: str | None = None
            error_type: str | None = None
            if exception is not None:
                error_message = str(exception)
                error_type = type(exception).__name__

            duration_ms = _get_duration_ms(rc)

            self._tracker.record_end(
                execution_uid,
                status="failure",
                duration_ms=duration_ms,
                error_message=error_message,
                error_type=error_type,
            )
        except Exception as e:
            logger.error("ExecutionStatePlugin: Error in AFTER_FAILURE handler: %s", e)

    def _on_teardown(self, rc: Any) -> None:
        """Finalize execution tracking for this run context.

        Cleans up the rc-to-execution mapping to prevent memory leaks.
        """
        try:
            rc_id = id(rc)
            self._rc_execution_map.pop(rc_id, None)
        except Exception as e:
            logger.error("ExecutionStatePlugin: Error in ON_TEARDOWN handler: %s", e)

    def _on_invoke_start(
        self, rc: Any, child_name: str, kwargs: dict[str, Any], depth: int
    ) -> None:
        """Track nested invocation start by pushing parent_uid onto the stack.

        When a parent job invokes a child, we push the parent's execution_uid
        so the child's BEFORE_JOB handler can link via parent_uid.
        """
        try:
            parent_execution_uid = self._get_execution_uid(rc)
            if parent_execution_uid is None:
                return

            self._invoke_parent_stack.append(parent_execution_uid)

        except Exception as e:
            logger.error("ExecutionStatePlugin: Error in INVOKE_START handler: %s", e)

    def _on_invoke_end(self, rc: Any, child_name: str, depth: int, result: Any) -> None:
        """Track nested invocation end by popping from the parent stack."""
        try:
            if self._invoke_parent_stack:
                self._invoke_parent_stack.pop()
        except Exception as e:
            logger.error("ExecutionStatePlugin: Error in INVOKE_END handler: %s", e)

    def _on_scope_created(self, scope: Any) -> None:
        """Replace the scope's state store with a SQLiteStateStore instance."""
        if self._backend is None:
            return

        try:
            scope_id = scope.scope_id if hasattr(scope, "scope_id") else str(id(scope))
            # Create a SQLiteStateStore scoped to this workflow scope
            # Use a generic namespace that can be refined per-job
            sqlite_store = SQLiteStateStore(
                backend=self._backend,
                scope_id=scope_id,
                job_namespace="__scope__",
            )
            scope.replace_state_store(sqlite_store)
            logger.debug(
                "ExecutionStatePlugin: Replaced state store for scope '%s'",
                scope_id,
            )
        except Exception as e:
            logger.error(
                "ExecutionStatePlugin: Error in ON_SCOPE_CREATED handler: %s", e
            )

    # ─── Internal Helpers ─────────────────────────────────────────────

    def _get_execution_uid(self, rc: Any) -> str | None:
        """Retrieve the execution_uid associated with a RunContext."""
        return self._rc_execution_map.get(id(rc))


# ─── Module-Level Helpers ─────────────────────────────────────────────


def _safe_serialize(value: Any) -> str | None:
    """Serialize a value to JSON, returning None for non-serializable values."""
    if value is None:
        return None
    try:
        return json.dumps(value)
    except (TypeError, ValueError, OverflowError):
        type_name = type(value).__name__
        return json.dumps(f"<non-serializable: {type_name}>")


def _get_duration_ms(rc: Any) -> float:
    """Extract duration_ms from a RunContext if available."""
    try:
        if hasattr(rc, "duration_ms"):
            val = rc.duration_ms
            if isinstance(val, int | float):
                return float(val)
        if hasattr(rc, "_start_time"):
            import time

            start = rc._start_time
            if isinstance(start, int | float):
                elapsed = time.perf_counter() - start
                return elapsed * 1000
    except Exception:
        pass
    return 0.0
