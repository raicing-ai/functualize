"""SQLite implementation of the ExecutionStore protocol.

Provides persistent execution record and phase tracking backed by SQLite,
conforming to the ExecutionStore protocol defined in functualize-state SDK.

Shares the database file with the SQLiteStateBackend to keep all persistent
state in a single database. Uses only stdlib sqlite3 (zero external deps).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from functualize_state._types import ExecutionRecord, PhaseRecord

__all__ = ["SQLiteExecutionStore"]

logger = logging.getLogger(__name__)

# SQL to create the ExecutionStore-specific tables following the design schema.
_EXECUTION_STORE_SCHEMA = """\
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    job_name TEXT NOT NULL,
    session_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at REAL NOT NULL,
    ended_at REAL,
    duration_ms REAL,
    kwargs TEXT,
    result TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS phases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    duration_ms REAL,
    FOREIGN KEY (execution_id) REFERENCES executions(execution_id)
);

CREATE INDEX IF NOT EXISTS idx_executions_session_id
    ON executions(session_id);

CREATE INDEX IF NOT EXISTS idx_phases_execution_id
    ON phases(execution_id);
"""


class SQLiteExecutionStore:
    """SQLite-backed implementation of the ExecutionStore protocol.

    Stores execution records, phases, and sessions using the SQL schema
    defined in the design document. Uses JSON encoding for complex types
    (kwargs dict, result value).

    Shares the same database file as the SQLiteStateBackend to keep all
    persistent state collocated. Connection management is handled internally
    using the same WAL mode configuration.

    Args:
        db_path: Path to the SQLite database file. If None, defaults to
            `.functualize/state.db` relative to the current working directory.
            Should match the path used by SQLiteStateBackend.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            self._db_path = Path.cwd() / ".functualize" / "state.db"
        else:
            self._db_path = Path(db_path)

        self._conn: sqlite3.Connection | None = None
        self._initialized = False

    @property
    def db_path(self) -> Path:
        """The resolved path to the database file."""
        return self._db_path

    def _ensure_initialized(self) -> sqlite3.Connection:
        """Ensure the database is initialized and return the connection.

        Creates the database directory, opens a connection with WAL mode,
        and initializes the execution store schema tables.
        """
        if self._conn is not None and self._initialized:
            return self._conn

        # Ensure the directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open connection with same settings as SQLiteStateBackend
        self._conn = sqlite3.connect(
            str(self._db_path),
            timeout=10.0,
            check_same_thread=False,
        )

        # Enable WAL mode for concurrent access
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.commit()

        # Create execution store schema
        self._conn.executescript(_EXECUTION_STORE_SCHEMA)
        self._conn.commit()

        self._initialized = True
        logger.debug("SQLiteExecutionStore initialized at %s", self._db_path)
        return self._conn

    # ─── ExecutionStore Protocol Methods ──────────────────────────────

    def insert_execution(self, record: ExecutionRecord) -> str:
        """Insert an execution record, returning the execution ID.

        Ensures the session exists before inserting the execution. If the
        session doesn't exist yet, it is created automatically.

        Args:
            record: The ExecutionRecord to persist.

        Returns:
            The execution_id from the record.
        """
        conn = self._ensure_initialized()

        # Ensure the session exists (upsert — don't overwrite existing)
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?)",
            (record.session_id, record.started_at),
        )

        # Serialize complex fields
        kwargs_json = json.dumps(record.kwargs) if record.kwargs else None
        result_json = (
            _safe_json_encode(record.result) if record.result is not None else None
        )

        conn.execute(
            """INSERT INTO executions
               (execution_id, job_name, session_id, status, started_at,
                ended_at, duration_ms, kwargs, result)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.execution_id,
                record.job_name,
                record.session_id,
                record.status,
                record.started_at,
                record.ended_at,
                record.duration_ms,
                kwargs_json,
                result_json,
            ),
        )
        conn.commit()
        return record.execution_id

    def update_execution(self, execution_id: str, **updates: Any) -> None:
        """Update fields on an existing execution record.

        Supports updating: status, ended_at, duration_ms, kwargs, result.

        Args:
            execution_id: The execution to update.
            **updates: Field names and their new values.
        """
        if not updates:
            return

        conn = self._ensure_initialized()
        set_clauses: list[str] = []
        params: list[Any] = []

        for field_name, value in updates.items():
            if field_name == "kwargs":
                set_clauses.append("kwargs = ?")
                params.append(json.dumps(value) if value is not None else None)
            elif field_name == "result":
                set_clauses.append("result = ?")
                params.append(_safe_json_encode(value) if value is not None else None)
            elif field_name in ("status", "ended_at", "duration_ms"):
                set_clauses.append(f"{field_name} = ?")
                params.append(value)
            else:
                logger.warning(
                    "Ignoring unknown update field '%s' for execution %s",
                    field_name,
                    execution_id,
                )

        if not set_clauses:
            return

        params.append(execution_id)
        sql = f"UPDATE executions SET {', '.join(set_clauses)} WHERE execution_id = ?"

        conn.execute(sql, tuple(params))
        conn.commit()

    def get_session_executions(
        self, session_id: str, limit: int = 50
    ) -> list[ExecutionRecord]:
        """Get execution records for a session, ordered by start time descending.

        Args:
            session_id: The session to query.
            limit: Maximum number of results (default 50).

        Returns:
            List of ExecutionRecord instances.
        """
        conn = self._ensure_initialized()

        cursor = conn.execute(
            """SELECT execution_id, job_name, session_id, status,
                      started_at, ended_at, duration_ms, kwargs, result
               FROM executions
               WHERE session_id = ?
               ORDER BY started_at DESC
               LIMIT ?""",
            (session_id, limit),
        )
        rows = cursor.fetchall()
        return [_row_to_execution_record(row) for row in rows]

    def insert_phase(self, execution_id: str, phase: PhaseRecord) -> None:
        """Insert a phase record for an execution.

        Args:
            execution_id: The execution this phase belongs to.
            phase: The PhaseRecord to persist.
        """
        conn = self._ensure_initialized()

        conn.execute(
            """INSERT INTO phases
               (execution_id, name, status, started_at, ended_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                execution_id,
                phase.name,
                phase.status,
                phase.started_at,
                phase.ended_at,
                phase.duration_ms,
            ),
        )
        conn.commit()

    def get_execution_phases(self, execution_id: str) -> list[PhaseRecord]:
        """Get all phase records for an execution, ordered by start time.

        Args:
            execution_id: The execution to query phases for.

        Returns:
            List of PhaseRecord instances ordered by started_at ascending.
        """
        conn = self._ensure_initialized()

        cursor = conn.execute(
            """SELECT name, status, started_at, ended_at, duration_ms
               FROM phases
               WHERE execution_id = ?
               ORDER BY started_at ASC""",
            (execution_id,),
        )
        rows = cursor.fetchall()
        return [
            PhaseRecord(
                name=row[0],
                status=row[1],
                started_at=row[2],
                ended_at=row[3],
                duration_ms=row[4],
            )
            for row in rows
        ]

    # ─── Lifecycle ────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error as e:
                logger.warning("Error closing SQLiteExecutionStore connection: %s", e)
            finally:
                self._conn = None
                self._initialized = False

    def __enter__(self) -> SQLiteExecutionStore:
        """Context manager entry — initialize if needed."""
        self._ensure_initialized()
        return self

    def __exit__(self, *exc: Any) -> None:
        """Context manager exit — close connection."""
        self.close()

    def __del__(self) -> None:
        """Ensure connection is closed on garbage collection."""
        self.close()


# ─── Module-Level Helpers ─────────────────────────────────────────────


def _safe_json_encode(value: Any) -> str | None:
    """Encode a value to JSON, handling non-serializable values gracefully.

    Args:
        value: Any Python value to encode.

    Returns:
        JSON string, or None if value is None.
    """
    if value is None:
        return None
    try:
        return json.dumps(value)
    except (TypeError, ValueError, OverflowError):
        type_name = type(value).__name__
        return json.dumps(f"<non-serializable: {type_name}>")


def _row_to_execution_record(row: tuple[Any, ...]) -> ExecutionRecord:
    """Convert a database row tuple to an ExecutionRecord instance.

    Expected column order: execution_id, job_name, session_id, status,
    started_at, ended_at, duration_ms, kwargs, result.
    """
    kwargs_raw = row[7]
    result_raw = row[8]

    kwargs: dict[str, Any] = {}
    if kwargs_raw is not None:
        try:
            kwargs = json.loads(kwargs_raw)
        except (json.JSONDecodeError, TypeError):
            kwargs = {}

    result: Any = None
    if result_raw is not None:
        try:
            result = json.loads(result_raw)
        except (json.JSONDecodeError, TypeError):
            result = result_raw

    return ExecutionRecord(
        execution_id=row[0],
        job_name=row[1],
        session_id=row[2],
        status=row[3],
        started_at=row[4],
        ended_at=row[5],
        duration_ms=row[6],
        kwargs=kwargs,
        result=result,
    )
