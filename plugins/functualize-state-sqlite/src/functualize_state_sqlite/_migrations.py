"""Schema migration system for the SQLite state plugin.

Provides version tracking and sequential migration upgrades using a
`schema_version` table. Each migration is a function that takes a
sqlite3.Connection and applies schema changes for that version.

Uses only stdlib sqlite3 (zero external dependencies).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable

__all__ = ["migrate", "get_current_version", "LATEST_VERSION"]

logger = logging.getLogger(__name__)

# Type alias for migration functions
MigrationFn = Callable[[sqlite3.Connection], None]


def _migration_v1(conn: sqlite3.Connection) -> None:
    """Initial migration: create state, executions, phases, and sessions tables."""
    conn.executescript("""\
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at REAL NOT NULL
        );

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
    """)


# Registry of all migrations, keyed by version number.
# Migrations are applied sequentially from current version + 1 to LATEST_VERSION.
_MIGRATIONS: dict[int, MigrationFn] = {
    1: _migration_v1,
}

# The latest schema version supported by this plugin.
LATEST_VERSION: int = max(_MIGRATIONS.keys())


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    """Create the schema_version table if it doesn't exist."""
    conn.execute("""\
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        )
    """)
    conn.commit()


def get_current_version(conn: sqlite3.Connection) -> int:
    """Get the current schema version from the database.

    Returns 0 if no migrations have been applied yet.

    Args:
        conn: An open sqlite3 connection.

    Returns:
        The highest version number that has been applied, or 0 if none.
    """
    _ensure_schema_version_table(conn)
    cursor = conn.execute("SELECT MAX(version) FROM schema_version")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply all pending migrations to bring the database up to LATEST_VERSION.

    Creates the schema_version table if it doesn't exist, checks the current
    version, and applies migrations sequentially from current + 1 to
    LATEST_VERSION.

    Each migration is executed within a transaction. If a migration fails,
    the transaction is rolled back and the error is raised.

    Args:
        conn: An open sqlite3 connection.

    Returns:
        The version the database is now at after migrations.

    Raises:
        sqlite3.Error: If a migration fails to apply.
    """
    _ensure_schema_version_table(conn)
    current = get_current_version(conn)

    if current >= LATEST_VERSION:
        logger.debug("Schema is up to date (version %d)", current)
        return current

    logger.info(
        "Migrating schema from version %d to %d",
        current,
        LATEST_VERSION,
    )

    for version in range(current + 1, LATEST_VERSION + 1):
        migration_fn = _MIGRATIONS.get(version)
        if migration_fn is None:
            raise RuntimeError(f"Missing migration function for version {version}")

        logger.debug("Applying migration version %d", version)
        try:
            migration_fn(conn)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, time.time()),
            )
            conn.commit()
            logger.info("Applied migration version %d", version)
        except sqlite3.Error:
            conn.rollback()
            logger.error("Failed to apply migration version %d", version)
            raise

    return LATEST_VERSION
