"""SQLite backend for execution state persistence.

Manages the SQLite database connection with WAL mode for concurrent read
performance, initializes the schema, and provides query helpers for the
execution tracking plugin.

The database is stored at `.functualize/execution.db` relative to the
configured base path (defaults to CWD). The directory is created if it
does not exist.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

__all__ = ["SQLiteBackend"]

logger = logging.getLogger(__name__)

# Schema version for future migration support
_SCHEMA_VERSION = 1

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    created_at REAL,
    updated_at REAL,
    workflow_name TEXT,
    status TEXT DEFAULT 'running',
    metadata_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS executions (
    execution_uid TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(session_id),
    job_name TEXT NOT NULL,
    started_at REAL,
    ended_at REAL,
    duration_ms REAL,
    status TEXT DEFAULT 'running',
    kwargs_json TEXT,
    result_json TEXT,
    error_message TEXT,
    error_type TEXT,
    parent_uid TEXT,
    depth INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS execution_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_uid TEXT REFERENCES executions(execution_uid),
    step_name TEXT,
    status TEXT,
    message TEXT,
    started_at REAL,
    ended_at REAL,
    duration_ms REAL
);

CREATE TABLE IF NOT EXISTS state (
    scope_id TEXT,
    job_namespace TEXT,
    key TEXT,
    value_json TEXT,
    updated_at REAL,
    PRIMARY KEY (scope_id, job_namespace, key)
);

CREATE INDEX IF NOT EXISTS idx_executions_session
    ON executions(session_id);

CREATE INDEX IF NOT EXISTS idx_executions_job_name
    ON executions(job_name);

CREATE INDEX IF NOT EXISTS idx_execution_steps_uid
    ON execution_steps(execution_uid);

CREATE INDEX IF NOT EXISTS idx_state_scope
    ON state(scope_id, job_namespace);
"""


class SQLiteBackend:
    """SQLite connection manager with WAL mode and schema initialization.

    Provides a single-connection approach suitable for the plugin's
    synchronous execution model. WAL mode enables concurrent reads
    without blocking writes.

    Args:
        db_path: Path to the SQLite database file. If None, defaults to
            `.functualize/execution.db` relative to cwd.
        base_dir: Base directory for relative db_path resolution. Defaults
            to the current working directory.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        base_dir = Path.cwd() if base_dir is None else Path(base_dir)

        if db_path is None:
            self._db_path = base_dir / ".functualize" / "execution.db"
        else:
            db_path = Path(db_path)
            if not db_path.is_absolute():
                self._db_path = base_dir / db_path
            else:
                self._db_path = db_path

        self._conn: sqlite3.Connection | None = None
        self._initialized = False

    @property
    def db_path(self) -> Path:
        """The resolved path to the database file."""
        return self._db_path

    @property
    def is_initialized(self) -> bool:
        """Whether the backend has been initialized (schema created)."""
        return self._initialized

    def initialize(self) -> None:
        """Create the database directory, open connection, enable WAL, and run schema.

        This method is idempotent — calling it multiple times is safe.
        """
        if self._initialized:
            return

        # Ensure the directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open connection and configure
        self._conn = self._create_connection()
        self._enable_wal()
        self._create_schema()
        self._initialized = True
        logger.debug("SQLiteBackend initialized at %s", self._db_path)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error as e:
                logger.warning("Error closing SQLite connection: %s", e)
            finally:
                self._conn = None
                self._initialized = False

    @property
    def connection(self) -> sqlite3.Connection:
        """Get the active database connection.

        Raises:
            RuntimeError: If the backend has not been initialized.
        """
        if self._conn is None:
            raise RuntimeError(
                "SQLiteBackend not initialized. Call initialize() first."
            )
        return self._conn

    # ─── Query Helpers ────────────────────────────────────────────────

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> sqlite3.Cursor:
        """Execute a SQL statement with error handling.

        Args:
            sql: SQL statement to execute.
            params: Parameters for the SQL statement.

        Returns:
            The cursor after execution.

        Raises:
            RuntimeError: If the backend is not initialized.
            sqlite3.Error: If the operation fails (callers should handle).
        """
        return self.connection.execute(sql, params)

    def execute_safe(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> sqlite3.Cursor | None:
        """Execute a SQL statement, logging errors instead of raising.

        Per Requirement 23.11: database write failures should not crash
        job execution.

        Args:
            sql: SQL statement to execute.
            params: Parameters for the SQL statement.

        Returns:
            The cursor after execution, or None if the operation failed.
        """
        try:
            cursor = self.connection.execute(sql, params)
            self._conn.commit()  # type: ignore[union-attr]
            return cursor
        except sqlite3.Error as e:
            logger.error("SQLite operation failed: %s | SQL: %s", e, sql[:200])
            return None

    def executemany_safe(
        self,
        sql: str,
        params_seq: list[tuple[Any, ...]],
    ) -> sqlite3.Cursor | None:
        """Execute a SQL statement against multiple parameter sets safely.

        Args:
            sql: SQL statement to execute.
            params_seq: Sequence of parameter tuples.

        Returns:
            The cursor after execution, or None if the operation failed.
        """
        try:
            cursor = self.connection.executemany(sql, params_seq)
            self._conn.commit()  # type: ignore[union-attr]
            return cursor
        except sqlite3.Error as e:
            logger.error("SQLite batch operation failed: %s | SQL: %s", e, sql[:200])
            return None

    def fetch_one(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> dict[str, Any] | None:
        """Execute a query and return the first row as a dict.

        Args:
            sql: SELECT statement.
            params: Query parameters.

        Returns:
            A dict mapping column names to values, or None if no rows.
        """
        try:
            cursor = self.connection.execute(sql, params)
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row, strict=False))
        except sqlite3.Error as e:
            logger.error("SQLite fetch_one failed: %s | SQL: %s", e, sql[:200])
            return None

    def fetch_all(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> list[dict[str, Any]]:
        """Execute a query and return all rows as a list of dicts.

        Args:
            sql: SELECT statement.
            params: Query parameters.

        Returns:
            A list of dicts, each mapping column names to values.
            Returns empty list on error.
        """
        try:
            cursor = self.connection.execute(sql, params)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("SQLite fetch_all failed: %s | SQL: %s", e, sql[:200])
            return []

    # ─── Session Operations ───────────────────────────────────────────

    def insert_session(
        self,
        session_id: str,
        scope_id: str,
        *,
        workflow_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Insert a new session record.

        Returns:
            True if successful, False on failure.
        """
        now = time.time()
        metadata_json = json.dumps(metadata or {})
        result = self.execute_safe(
            """INSERT INTO sessions
               (session_id, scope_id, created_at, updated_at, workflow_name, status, metadata_json)
               VALUES (?, ?, ?, ?, ?, 'running', ?)""",
            (session_id, scope_id, now, now, workflow_name, metadata_json),
        )
        return result is not None

    def update_session(
        self,
        session_id: str,
        *,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Update an existing session record.

        Only updates the fields that are provided (not None).

        Returns:
            True if successful, False on failure.
        """
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [time.time()]

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(json.dumps(metadata))

        params.append(session_id)
        sql = f"UPDATE sessions SET {', '.join(updates)} WHERE session_id = ?"
        result = self.execute_safe(sql, tuple(params))
        return result is not None

    def get_latest_session(self) -> dict[str, Any] | None:
        """Get the most recently updated session.

        Returns:
            Session record as a dict, or None if no sessions exist.
        """
        return self.fetch_one("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 1")

    # ─── Execution Operations ─────────────────────────────────────────

    def insert_execution(
        self,
        execution_uid: str,
        session_id: str,
        job_name: str,
        *,
        kwargs_json: str | None = None,
        parent_uid: str | None = None,
        depth: int = 0,
    ) -> bool:
        """Insert a new execution record.

        Returns:
            True if successful, False on failure.
        """
        now = time.time()
        result = self.execute_safe(
            """INSERT INTO executions
               (execution_uid, session_id, job_name, started_at, status,
                kwargs_json, parent_uid, depth)
               VALUES (?, ?, ?, ?, 'running', ?, ?, ?)""",
            (execution_uid, session_id, job_name, now, kwargs_json, parent_uid, depth),
        )
        return result is not None

    def update_execution(
        self,
        execution_uid: str,
        *,
        status: str | None = None,
        duration_ms: float | None = None,
        result_json: str | None = None,
        error_message: str | None = None,
        error_type: str | None = None,
    ) -> bool:
        """Update an existing execution record.

        Only updates the fields that are provided (not None).

        Returns:
            True if successful, False on failure.
        """
        updates: list[str] = ["ended_at = ?"]
        params: list[Any] = [time.time()]

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if duration_ms is not None:
            updates.append("duration_ms = ?")
            params.append(duration_ms)

        if result_json is not None:
            updates.append("result_json = ?")
            params.append(result_json)

        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        if error_type is not None:
            updates.append("error_type = ?")
            params.append(error_type)

        params.append(execution_uid)
        sql = f"UPDATE executions SET {', '.join(updates)} WHERE execution_uid = ?"
        result = self.execute_safe(sql, tuple(params))
        return result is not None

    def get_execution(self, execution_uid: str) -> dict[str, Any] | None:
        """Get a single execution record by UID."""
        return self.fetch_one(
            "SELECT * FROM executions WHERE execution_uid = ?",
            (execution_uid,),
        )

    def get_session_executions(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get executions for a session, ordered by start time descending.

        Args:
            session_id: The session to query.
            limit: Maximum number of results (default 20).

        Returns:
            List of execution records as dicts.
        """
        return self.fetch_all(
            """SELECT * FROM executions
               WHERE session_id = ?
               ORDER BY started_at DESC
               LIMIT ?""",
            (session_id, limit),
        )

    def get_recent_executions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Get the most recent executions across all sessions.

        Args:
            limit: Maximum number of results (default 20).

        Returns:
            List of execution records as dicts.
        """
        return self.fetch_all(
            "SELECT * FROM executions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )

    # ─── Execution Steps Operations ──────────────────────────────────

    def insert_step(
        self,
        execution_uid: str,
        step_name: str,
        *,
        status: str = "running",
        message: str | None = None,
    ) -> int | None:
        """Insert a new execution step record.

        Returns:
            The auto-generated step ID, or None on failure.
        """
        now = time.time()
        result = self.execute_safe(
            """INSERT INTO execution_steps
               (execution_uid, step_name, status, message, started_at)
               VALUES (?, ?, ?, ?, ?)""",
            (execution_uid, step_name, status, message, now),
        )
        if result is not None:
            return result.lastrowid
        return None

    def update_step(
        self,
        step_id: int,
        *,
        status: str | None = None,
        message: str | None = None,
        duration_ms: float | None = None,
    ) -> bool:
        """Update an execution step record.

        Returns:
            True if successful, False on failure.
        """
        updates: list[str] = ["ended_at = ?"]
        params: list[Any] = [time.time()]

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if message is not None:
            updates.append("message = ?")
            params.append(message)

        if duration_ms is not None:
            updates.append("duration_ms = ?")
            params.append(duration_ms)

        params.append(step_id)
        sql = f"UPDATE execution_steps SET {', '.join(updates)} WHERE id = ?"
        result = self.execute_safe(sql, tuple(params))
        return result is not None

    def get_execution_steps(self, execution_uid: str) -> list[dict[str, Any]]:
        """Get all steps for an execution, ordered by start time.

        Returns:
            List of step records as dicts.
        """
        return self.fetch_all(
            """SELECT * FROM execution_steps
               WHERE execution_uid = ?
               ORDER BY started_at ASC""",
            (execution_uid,),
        )

    # ─── State Operations ─────────────────────────────────────────────

    def upsert_state(
        self,
        scope_id: str,
        job_namespace: str,
        key: str,
        value_json: str,
    ) -> bool:
        """Insert or update a state key-value pair.

        Uses SQLite's INSERT OR REPLACE (upsert) on the composite primary key.

        Returns:
            True if successful, False on failure.
        """
        now = time.time()
        result = self.execute_safe(
            """INSERT OR REPLACE INTO state
               (scope_id, job_namespace, key, value_json, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (scope_id, job_namespace, key, value_json, now),
        )
        return result is not None

    def get_state(
        self,
        scope_id: str,
        job_namespace: str,
        key: str,
    ) -> str | None:
        """Get a state value by composite key.

        Returns:
            The value_json string, or None if not found.
        """
        row = self.fetch_one(
            """SELECT value_json FROM state
               WHERE scope_id = ? AND job_namespace = ? AND key = ?""",
            (scope_id, job_namespace, key),
        )
        if row is not None:
            return row["value_json"]
        return None

    def get_namespace_state(
        self,
        scope_id: str,
        job_namespace: str,
    ) -> dict[str, str]:
        """Get all state key-value pairs for a namespace.

        Returns:
            Dict mapping keys to their value_json strings.
        """
        rows = self.fetch_all(
            "SELECT key, value_json FROM state WHERE scope_id = ? AND job_namespace = ?",
            (scope_id, job_namespace),
        )
        return {row["key"]: row["value_json"] for row in rows}

    def get_all_state(self, scope_id: str) -> dict[str, dict[str, str]]:
        """Get all state for a scope, organized by namespace.

        Returns:
            Dict mapping job_namespace to {key: value_json}.
        """
        rows = self.fetch_all(
            "SELECT job_namespace, key, value_json FROM state WHERE scope_id = ?",
            (scope_id,),
        )
        result: dict[str, dict[str, str]] = {}
        for row in rows:
            ns = row["job_namespace"]
            if ns not in result:
                result[ns] = {}
            result[ns][row["key"]] = row["value_json"]
        return result

    def delete_state(
        self,
        scope_id: str,
        job_namespace: str,
        key: str,
    ) -> bool:
        """Delete a state key-value pair.

        Returns:
            True if successful, False on failure.
        """
        result = self.execute_safe(
            "DELETE FROM state WHERE scope_id = ? AND job_namespace = ? AND key = ?",
            (scope_id, job_namespace, key),
        )
        return result is not None

    def clear_namespace_state(
        self,
        scope_id: str,
        job_namespace: str,
    ) -> bool:
        """Delete all state for a namespace within a scope.

        Returns:
            True if successful, False on failure.
        """
        result = self.execute_safe(
            "DELETE FROM state WHERE scope_id = ? AND job_namespace = ?",
            (scope_id, job_namespace),
        )
        return result is not None

    def list_namespaces(self, scope_id: str) -> list[str]:
        """List all job namespaces that have state for a scope.

        Returns:
            List of namespace strings.
        """
        rows = self.fetch_all(
            "SELECT DISTINCT job_namespace FROM state WHERE scope_id = ?",
            (scope_id,),
        )
        return [row["job_namespace"] for row in rows]

    def get_namespace_keys(
        self,
        scope_id: str,
        job_namespace: str,
    ) -> list[str]:
        """List all keys within a namespace for a scope.

        Returns:
            List of key strings.
        """
        rows = self.fetch_all(
            "SELECT key FROM state WHERE scope_id = ? AND job_namespace = ?",
            (scope_id, job_namespace),
        )
        return [row["key"] for row in rows]

    # ─── Internal Methods ─────────────────────────────────────────────

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with appropriate settings."""
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=10.0,
            check_same_thread=False,
        )
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _enable_wal(self) -> None:
        """Enable WAL mode for better concurrent read performance."""
        assert self._conn is not None
        self._conn.execute("PRAGMA journal_mode = WAL")
        # Set synchronous to NORMAL for a good balance of safety and speed
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.commit()

    def _create_schema(self) -> None:
        """Create the database schema if it doesn't exist."""
        assert self._conn is not None
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def __enter__(self) -> SQLiteBackend:
        """Context manager entry — initialize if needed."""
        if not self._initialized:
            self.initialize()
        return self

    def __exit__(self, *exc: Any) -> None:
        """Context manager exit — close connection."""
        self.close()

    def __del__(self) -> None:
        """Ensure connection is closed on garbage collection."""
        self.close()
