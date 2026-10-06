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

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from functualize.plugin import PreparedStore, RuntimeStoreSelectionError, StoreProfile
from functualize_substrate_sqlite._driver import LocalSqliteDriver, SqliteBusyError
from functualize_substrate_sqlite._migrations import migrate
from functualize_substrate_sqlite._retention import apply_retention
from functualize_substrate_sqlite._runtime_store import (
    DEFAULT_NAMESPACE,
    SQLITE_PROFILE,
    SqliteRuntimeStore,
)
from functualize_substrate_sqlite.substrate import SQLiteSubstrate

if TYPE_CHECKING:
    from functualize.plugin import RuntimeStoreConfig
    from functualize_substrate_sqlite._driver import SqlDriver

__all__ = [
    "BORN_RELATIONAL_DIGEST",
    "CutoverMarkerInvalid",
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
BORN_RELATIONAL_DIGEST = (
    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
)


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


class CutoverMarkerInvalid(RuntimeStoreSelectionError):  # noqa: N818 — names a refusal
    """The marker cannot establish which store owns this file's runtime data."""

    def __init__(self, path: Path, row: object) -> None:
        self.path = path
        self.row = row
        super().__init__(
            f"{path} has an invalid runtime_cutover marker {row!r}. "
            f"Restore the database backup, or delete the invalid row and run "
            f"`{IMPORT_COMMAND} --db {path}` so the importer decides."
        )


def _validated_marker(path: Path, rows: list[tuple[object, ...]]) -> str | None:
    """Return one valid provenance, or refuse an ambiguous or malformed marker."""
    if len(rows) > 1:
        raise CutoverMarkerInvalid(path, rows)
    if not rows:
        return None
    row = rows[0]
    source, imported_at, digest, backup_path = row
    try:
        stamp = datetime.fromisoformat(str(imported_at))
    except (TypeError, ValueError) as error:
        raise CutoverMarkerInvalid(path, row) from error
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise CutoverMarkerInvalid(path, row)
    if source == "documents":
        valid = (
            backup_path is not None
            and isinstance(digest, str)
            and bool(re.fullmatch(r"[0-9a-fA-F]{64}", digest))
        )
    elif source == "born-relational":
        valid = backup_path is None and digest == BORN_RELATIONAL_DIGEST
    else:
        valid = False
    if not valid:
        raise CutoverMarkerInvalid(path, row)
    return str(source)


def _marker_rows(driver: SqlDriver) -> list[tuple[object, ...]]:
    return driver.query(
        "SELECT source, imported_at, source_digest, backup_path "
        "FROM runtime_cutover ORDER BY source"
    )


def _legacy_runtime_rows(driver: SqlDriver) -> bool:
    tables = {
        row[0]
        for row in driver.query("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return "documents" in tables and bool(
        driver.query(f"SELECT 1 FROM documents WHERE {_LEGACY_RUNTIME_KEYS} LIMIT 1")
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
        # Migration and the document-table DDL may race on the first open.
        # The driver identifies that lock as retryable, and each step is
        # idempotent, so a bounded retry can finish after the winner.
        for attempt in range(3):
            try:
                return self._prepare_once(path)
            except SqliteBusyError:
                if attempt == 2:
                    raise
        raise AssertionError("unreachable prepare retry")

    def _prepare_once(self, path: Path) -> PreparedStore:
        driver = LocalSqliteDriver(path)
        try:
            migrate(driver)
            substrate = SQLiteSubstrate(path)
            driver.batch(
                [
                    (
                        "INSERT INTO runtime_cutover "
                        "(source, imported_at, source_digest, backup_path) "
                        "SELECT 'born-relational', ?, ?, NULL "
                        "WHERE NOT EXISTS (SELECT 1 FROM runtime_cutover) "
                        f"AND NOT EXISTS (SELECT 1 FROM documents WHERE {_LEGACY_RUNTIME_KEYS})",
                        (datetime.now(UTC).isoformat(), BORN_RELATIONAL_DIGEST),
                    )
                ]
            )
            marker = _validated_marker(path, _marker_rows(driver))
            if marker is None and _legacy_runtime_rows(driver):
                raise LegacyImportRequired(path)
            if marker is None:
                raise CutoverMarkerInvalid(path, None)
            store = SqliteRuntimeStore(driver)
            apply_retention(driver, DEFAULT_NAMESPACE)
        except BaseException:
            driver.close()
            raise
        return PreparedStore(store=store, substrate=substrate)

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
            marker = (
                _validated_marker(
                    path,
                    list(
                        conn.execute(
                            "SELECT source, imported_at, source_digest, backup_path "
                            "FROM runtime_cutover ORDER BY source"
                        )
                    ),
                )
                if "runtime_cutover" in tables
                else None
            )
            relational = marker is not None or any(
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


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _has_row(conn: sqlite3.Connection, sql: str) -> bool:
    return conn.execute(sql).fetchone() is not None
