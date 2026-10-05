"""`SqliteRuntimeStoreFactory`: what boot step 6.5 calls when ``sqlite`` is selected.

``prepare`` opens the driver, migrates, refuses an un-imported legacy
database, and hands boot the store plus a `SQLiteSubstrate` on the **same
file**, so freshness and shell history live beside runtime truth rather than
falling back to the filesystem. Every failure is raised, uncaught: a selected
store that cannot start aborts boot, and nothing comes up on documents
instead (S-2).

URL forms (`contracts.md` §1): ``sqlite:`` is the project's default
``state.db``; ``sqlite:///abs/path.db`` is absolute; ``sqlite:rel/path.db`` is
relative to the project root.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from functualize.plugin import PreparedStore, RuntimeStoreSelectionError, StoreProfile
from functualize_substrate_sqlite._driver import LocalSqliteDriver
from functualize_substrate_sqlite._migrations import migrate
from functualize_substrate_sqlite._runtime_store import (
    SQLITE_PROFILE,
    SqliteRuntimeStore,
)
from functualize_substrate_sqlite.substrate import SQLiteSubstrate

if TYPE_CHECKING:
    from functualize.plugin import RuntimeStoreConfig
    from functualize_substrate_sqlite._driver import SqlDriver

__all__ = [
    "DEFAULT_DB_NAME",
    "IMPORT_COMMAND",
    "LegacyImportRequired",
    "SqliteRuntimeStoreFactory",
    "database_path",
    "default_database_path",
]

#: Beside the project's other runtime state, so `func builtin data clear` and a
#: `.gitignore` that already covers `.functualize/` keep working.
DEFAULT_DB_NAME = "state.db"

#: The offline command that moves legacy runtime documents into the schema.
IMPORT_COMMAND = "functualize-sqlite-import"

#: The legacy ``documents`` rows that are runtime truth. ``fresh`` and
#: ``shell-history`` are derived data and stay in ``documents`` for good.
_LEGACY_RUNTIME_KEYS = "key IN ('runs', 'scopes') OR key LIKE 'scope-state/%'"


class LegacyImportRequired(RuntimeStoreSelectionError):  # noqa: N818 — names the remedy, as contracts §5 does
    """``sqlite`` is selected, but its file still holds un-imported runtime documents.

    Starting anyway would leave every run and scope recorded before the
    upgrade unread behind a store that looks empty. The remedy is one offline
    command, named in the message.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.command = f"{IMPORT_COMMAND} --db {path}"
        super().__init__(
            f"{path} holds runtime documents written before the relational "
            f"schema, and no import has been recorded. Run `{self.command}` "
            f"(offline; it backs the file up first), then start again."
        )


def default_database_path(project_root: Path) -> Path:
    """Where ``sqlite:`` puts the database: the same directory as the file store."""
    # Public API, and the one question a storage plugin must not answer for
    # itself: the filesystem substrate resolves its location by the same call.
    from functualize.app.utils import resolve_fresh_location

    return resolve_fresh_location(Path(project_root))[0].parent / DEFAULT_DB_NAME


def database_path(url: str, project_root: Path) -> Path:
    """The file a ``sqlite:`` URL names. Refuses a form it does not know."""
    _scheme, _, rest = url.partition(":")
    if not rest:
        return default_database_path(project_root)
    if rest.startswith("///"):
        return Path(rest[2:])
    if rest.startswith("//"):
        raise RuntimeStoreSelectionError(
            f"runtime_store.url = {url!r} names a host; SQLite is a local file. "
            f"Use 'sqlite:', 'sqlite:///absolute/path.db' or 'sqlite:relative/path.db'."
        )
    return Path(project_root) / rest


class SqliteRuntimeStoreFactory:
    """Registered by the plugin under the scheme ``sqlite``."""

    scheme = "sqlite"
    profile: StoreProfile = SQLITE_PROFILE

    def prepare(self, config: RuntimeStoreConfig) -> PreparedStore:
        path = database_path(config.url, config.project_root)
        driver = LocalSqliteDriver(path)
        try:
            migrate(driver)
            if _holds_unimported_legacy(driver):
                raise LegacyImportRequired(path)
        except BaseException:
            driver.close()
            raise
        return PreparedStore(
            store=SqliteRuntimeStore(driver), substrate=SQLiteSubstrate(path)
        )

    def unselected_data(self, project_root: Path) -> str | None:
        """Runtime data in the default ``state.db`` that the document store would not see."""
        path = default_database_path(project_root)
        if not path.is_file():
            return None
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            tables = _tables(conn)
            legacy = "documents" in tables and _has_row(
                conn, f"SELECT 1 FROM documents WHERE {_LEGACY_RUNTIME_KEYS} LIMIT 1"
            )
            relational = any(
                _has_row(conn, f"SELECT 1 FROM {table} LIMIT 1")
                for table in ("runs", "workflow_scopes")
                if table in tables
            )
        finally:
            conn.close()
        if not (legacy or relational):
            return None
        remedy = (
            f"; after selecting it, run `{IMPORT_COMMAND} --db {path}`"
            if legacy and not relational
            else ""
        )
        return f"{path} holds runtime data for this project{remedy}."


def _holds_unimported_legacy(driver: SqlDriver) -> bool:
    tables = {
        row[0]
        for row in driver.query("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "documents" not in tables:
        return False
    if driver.query("SELECT 1 FROM runtime_cutover LIMIT 1"):
        return False
    return bool(
        driver.query(f"SELECT 1 FROM documents WHERE {_LEGACY_RUNTIME_KEYS} LIMIT 1")
    )


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _has_row(conn: sqlite3.Connection, sql: str) -> bool:
    return conn.execute(sql).fetchone() is not None
