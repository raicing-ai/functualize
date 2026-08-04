"""Execution tracker for session management, execution recording, and AI context.

Provides high-level operations for tracking job executions within sessions,
including automatic session resume based on TTL, nested execution linkage,
and a plain-text AI context summary.

The tracker delegates all database operations to the SQLiteBackend and
follows the error resilience pattern (Requirement 23.11): database failures
are logged but never propagate to callers.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize_state_sqlite.sqlite_backend import SQLiteBackend

__all__ = ["ExecutionTracker"]

logger = logging.getLogger(__name__)

# Default session TTL: 30 minutes (in seconds)
_DEFAULT_SESSION_TTL_SECONDS = 30 * 60


class ExecutionTracker:
    """Tracks job executions within sessions, providing history and AI context.

    The tracker manages session lifecycle (auto-resume or create new) and
    records execution start/end events. It supports nested executions via
    parent_uid linkage and provides a plain-text summary for AI assistants.

    Args:
        backend: An initialized SQLiteBackend instance.
        session_ttl: Time in seconds before a session is considered expired.
            Defaults to 1800 (30 minutes).
        scope_id: The workflow scope identifier. Defaults to "default".
    """

    def __init__(
        self,
        backend: SQLiteBackend,
        *,
        session_ttl: float = _DEFAULT_SESSION_TTL_SECONDS,
        scope_id: str = "default",
    ) -> None:
        self._backend = backend
        self._session_ttl = session_ttl
        self._scope_id = scope_id
        self._session_id: str | None = None
        self._execution_count: int = 0

    @property
    def session_id(self) -> str | None:
        """The current active session ID, or None if no session is active."""
        return self._session_id

    @property
    def session_ttl(self) -> float:
        """The session TTL in seconds."""
        return self._session_ttl

    # ─── Session Management ───────────────────────────────────────────

    def ensure_session(self) -> str:
        """Ensure an active session exists, resuming or creating as needed.

        If the latest session's updated_at is within the TTL, resume it.
        Otherwise, create a new session.

        Returns:
            The active session ID.
        """
        if self._session_id is not None:
            return self._session_id

        # Try to resume the latest session
        latest = self._backend.get_latest_session()
        if latest is not None:
            updated_at = latest.get("updated_at", 0.0)
            elapsed = time.time() - updated_at
            if elapsed < self._session_ttl:
                self._session_id = latest["session_id"]
                # Touch the session to keep it alive
                self._backend.update_session(self._session_id)
                logger.debug(
                    "Resumed session %s (idle %.1fs)",
                    self._session_id,
                    elapsed,
                )
                return self._session_id

        # Create a new session
        self._session_id = str(uuid.uuid4())
        success = self._backend.insert_session(
            self._session_id,
            self._scope_id,
        )
        if success:
            logger.debug("Created new session %s", self._session_id)
        else:
            logger.error("Failed to create session %s", self._session_id)

        return self._session_id

    # ─── Execution Recording ──────────────────────────────────────────

    def record_start(
        self,
        job_name: str,
        *,
        kwargs_json: str | None = None,
        parent_uid: str | None = None,
        depth: int = 0,
    ) -> str:
        """Record the start of a job execution.

        Ensures a session is active, generates a unique execution UID,
        and inserts the execution record.

        Args:
            job_name: The name of the job being executed.
            kwargs_json: JSON-serialized kwargs passed to the job.
            parent_uid: The execution UID of the parent (for nested calls).
            depth: The nesting depth (0 for top-level).

        Returns:
            The generated execution UID.
        """
        session_id = self.ensure_session()
        execution_uid = str(uuid.uuid4())

        success = self._backend.insert_execution(
            execution_uid,
            session_id,
            job_name,
            kwargs_json=kwargs_json,
            parent_uid=parent_uid,
            depth=depth,
        )

        if success:
            self._execution_count += 1
            # Keep session alive
            self._backend.update_session(session_id)
            logger.debug(
                "Recorded execution start: %s (job=%s, parent=%s)",
                execution_uid,
                job_name,
                parent_uid,
            )
        else:
            logger.error(
                "Failed to record execution start for job %s",
                job_name,
            )

        return execution_uid

    def record_end(
        self,
        execution_uid: str,
        *,
        status: str,
        duration_ms: float,
        result_json: str | None = None,
        error_message: str | None = None,
        error_type: str | None = None,
    ) -> None:
        """Record the end of a job execution.

        Updates the execution record with completion details.

        Args:
            execution_uid: The execution UID returned by record_start().
            status: The final status ("success" or "failure").
            duration_ms: The execution duration in milliseconds.
            result_json: JSON-serialized return value (if serializable).
            error_message: Error message (for failed executions).
            error_type: Error type name (for failed executions).
        """
        success = self._backend.update_execution(
            execution_uid,
            status=status,
            duration_ms=duration_ms,
            result_json=result_json,
            error_message=error_message,
            error_type=error_type,
        )

        if success:
            # Keep session alive
            if self._session_id:
                self._backend.update_session(self._session_id)
            logger.debug(
                "Recorded execution end: %s (status=%s, duration=%.1fms)",
                execution_uid,
                status,
                duration_ms,
            )
        else:
            logger.error(
                "Failed to record execution end for %s",
                execution_uid,
            )

    # ─── Query Methods ────────────────────────────────────────────────

    def get_execution_history(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get recent executions for the current session.

        Args:
            limit: Maximum number of executions to return.

        Returns:
            List of execution records as dicts, ordered by start time descending.
        """
        if self._session_id is None:
            return []
        return self._backend.get_session_executions(
            self._session_id,
            limit=limit,
        )

    def get_session_execution_count(self) -> int:
        """Get the total number of executions in the current session.

        Returns:
            The count of executions, or 0 if no session is active.
        """
        if self._session_id is None:
            return 0

        row = self._backend.fetch_one(
            "SELECT COUNT(*) as count FROM executions WHERE session_id = ?",
            (self._session_id,),
        )
        if row is not None:
            return int(row["count"])
        return 0

    # ─── AI Context ───────────────────────────────────────────────────

    def to_ai_context(self) -> str:
        """Generate a plain-text summary for AI assistant consumption.

        Returns a formatted summary containing:
        - Session ID
        - Total execution count in the session
        - List of recent 20 executions with job name, status, duration, timestamp

        Returns:
            A plain-text string suitable for including in AI context.
        """
        if self._session_id is None:
            return "No active execution session."

        total_count = self.get_session_execution_count()
        recent = self._backend.get_session_executions(
            self._session_id,
            limit=20,
        )

        lines: list[str] = [
            "## Execution Context",
            f"Session: {self._session_id}",
            f"Total executions: {total_count}",
            "",
        ]

        if not recent:
            lines.append("No executions recorded yet.")
        else:
            lines.append("Recent executions (most recent first):")
            lines.append("")
            for exec_record in recent:
                job_name = exec_record.get("job_name", "unknown")
                status = exec_record.get("status", "unknown")
                duration = exec_record.get("duration_ms")
                started_at = exec_record.get("started_at")
                parent_uid = exec_record.get("parent_uid")

                # Format timestamp
                ts_str = ""
                if started_at is not None:
                    dt = datetime.fromtimestamp(started_at, tz=UTC)
                    ts_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")

                # Format duration
                dur_str = ""
                if duration is not None:
                    if duration < 1000:
                        dur_str = f"{duration:.0f}ms"
                    else:
                        dur_str = f"{duration / 1000:.1f}s"

                # Build the line
                parts = [f"  - {job_name}"]
                parts.append(f"[{status}]")
                if dur_str:
                    parts.append(f"({dur_str})")
                if ts_str:
                    parts.append(f"at {ts_str}")
                if parent_uid:
                    parts.append("(nested)")

                lines.append(" ".join(parts))

        return "\n".join(lines)
