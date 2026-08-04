"""SQLite StateBackend implementation.

Implements the StateBackend protocol from functualize-state using SQLite
in WAL mode for concurrent access. Values are JSON-encoded for storage.
Uses only stdlib sqlite3 (zero external dependencies).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

__all__ = ["SQLiteStateBackend"]

logger = logging.getLogger(__name__)

_STATE_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS kv_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class SQLiteStateBackend:
    """StateBackend protocol implementation backed by SQLite.

    Provides persistent key-value state storage with JSON-encoded values.
    Uses WAL mode for concurrent read access without blocking writes.

    Args:
        db_path: Path to the SQLite database file. If None, defaults to
            `.functualize/state.db` relative to the current working directory.
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
        """Ensure the database is initialized and return the connection."""
        if self._conn is not None and self._initialized:
            return self._conn

        # Ensure the directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open connection
        self._conn = sqlite3.connect(
            str(self._db_path),
            timeout=10.0,
            check_same_thread=False,
        )

        # Enable WAL mode for concurrent access
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.commit()

        # Create schema
        self._conn.executescript(_STATE_SCHEMA_SQL)
        self._conn.commit()

        self._initialized = True
        logger.debug("SQLiteStateBackend initialized at %s", self._db_path)
        return self._conn

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value by key, returning default if not found.

        The stored JSON value is deserialized back to a Python object.
        """
        conn = self._ensure_initialized()
        cursor = conn.execute(
            "SELECT value FROM kv_state WHERE key = ?",
            (key,),
        )
        row = cursor.fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def set(self, key: str, value: Any) -> None:
        """Set a value for a key.

        The value is JSON-encoded before storage.
        """
        conn = self._ensure_initialized()
        value_json = json.dumps(value)
        now = time.time()
        conn.execute(
            "INSERT OR REPLACE INTO kv_state (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value_json, now),
        )
        conn.commit()

    def delete(self, key: str) -> None:
        """Delete a key from the state backend.

        No-op if the key does not exist.
        """
        conn = self._ensure_initialized()
        conn.execute("DELETE FROM kv_state WHERE key = ?", (key,))
        conn.commit()

    def keys(self, prefix: str = "") -> list[str]:
        """Return all keys, optionally filtered by prefix."""
        conn = self._ensure_initialized()
        if prefix:
            cursor = conn.execute(
                "SELECT key FROM kv_state WHERE key LIKE ? ESCAPE '\\'",
                (self._escape_like(prefix) + "%",),
            )
        else:
            cursor = conn.execute("SELECT key FROM kv_state")
        return [row[0] for row in cursor.fetchall()]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error as e:
                logger.warning("Error closing SQLiteStateBackend connection: %s", e)
            finally:
                self._conn = None
                self._initialized = False

    @staticmethod
    def _escape_like(value: str) -> str:
        """Escape special characters in a LIKE pattern."""
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def __enter__(self) -> SQLiteStateBackend:
        """Context manager entry — initialize if needed."""
        self._ensure_initialized()
        return self

    def __exit__(self, *exc: Any) -> None:
        """Context manager exit — close connection."""
        self.close()

    def __del__(self) -> None:
        """Ensure connection is closed on garbage collection."""
        self.close()
