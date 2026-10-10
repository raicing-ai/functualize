"""SQLite's harness hooks — the instruments the suite cannot fake (contracts §4a).

Test code, not shipped code: it reaches the plugin the way `test_baseline.py`
does — through its public constructors, nothing private — because only the
backend's own code can build a store whose commit dies mid-statement, read
the outbox cold, or lay down last year's schema.

- `statement_faults` prepares the store exactly as boot does (the factory's
  ``prepare`` migrates and health-checks), then rebuilds it over a driver
  whose batch executes only the first ``fault_at`` statements of a unit
  before one that fails — inside the real ``BEGIN IMMEDIATE`` unit, which
  therefore rolls back (task 5's all-or-nothing). The fault is real SQL
  failing inside the store's own unit; nothing about the store is
  monkeypatched. The rebuilt store's own first batch (the namespace row its
  constructor ensures) rides through unarmed: it is not the unit under test,
  and every construction performs it.
- `outbox` reads the `outbox` table over a fresh `sqlite3` connection — never
  a store object, which is what a dispatcher restarting after a crash would
  do.
- `migrations` lays down the two historical schemas a local file can have
  (empty, and the legacy `documents`-only file holding derived keys), and the
  three kinds of damage the runner refuses: a doctored checksum, a ledger
  ahead of the shipped set, and a dropped table with its ledger row kept.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize.testing.conformance.hooks import RecordedIntent, StatementFault

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize.plugin import RuntimeStore

DB_NAME = "state.db"

#: The one statement that never works, so the fault is SQL failing inside the
#: store's own unit — not an exception raised around it.
_FAULT_STATEMENT = ("SELECT fault FROM sqlite_schema", ())


def _prepared_store(root: Path) -> Any:
    """The store exactly as boot selects it over ``root/state.db``."""
    import functualize_substrate_sqlite as sqlite

    from functualize.plugin import RuntimeStoreConfig

    return (
        sqlite.SqliteRuntimeStoreFactory()
        .prepare(
            RuntimeStoreConfig(
                url=f"sqlite://{root / DB_NAME}", scheme="sqlite", project_root=root
            )
        )
        .store
    )


class _FaultingDriver:
    """The driver seam with a fault armed: commits die before statement N."""

    def __init__(self, inner: Any, fault_at: int | None) -> None:
        self._inner = inner
        self._fault_at = fault_at
        self._batches = 0

    def batch(self, statements: Sequence[tuple[str, Any]]) -> tuple[int, ...]:
        self._batches += 1
        if (
            self._fault_at is None
            or self._batches == 1
            or len(statements) <= self._fault_at
        ):
            # The first batch is the store constructor's namespace ensure —
            # not the unit under test; and a unit with ≤ fault_at statements
            # commits normally, which is how the tier learns the unit length.
            return self._inner.batch(statements)
        try:
            return self._inner.batch([*statements[: self._fault_at], _FAULT_STATEMENT])
        except sqlite3.OperationalError:
            raise StatementFault(
                f"fault before statement {self._fault_at} of a "
                f"{len(statements)}-statement unit"
            ) from None

    def query(self, sql: str, parameters: Any = ()) -> list[tuple[Any, ...]]:
        return self._inner.query(sql, parameters)

    def close(self) -> None:
        self._inner.close()


class SqliteStatementFaults:
    """`StatementFaults` — a store whose next commit dies mid-unit."""

    def make_store(self, root: Path, fault_at: int | None) -> RuntimeStore:
        import functualize_substrate_sqlite as sqlite

        real = _prepared_store(root)
        store: RuntimeStore = sqlite.SqliteRuntimeStore(
            _FaultingDriver(real.driver, fault_at)
        )
        return store


class SqliteOutboxProbe:
    """`OutboxProbe` — the outbox read cold, over a fresh connection."""

    def pending(self, root: Path) -> list[RecordedIntent]:
        path = root / DB_NAME
        if not path.is_file():
            return []
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT namespace_id, topic, payload, idempotency_key "
                "FROM outbox WHERE status = 'pending' AND published_at IS NULL "
                "ORDER BY rowid"
            ).fetchall()
        finally:
            connection.close()
        return [
            RecordedIntent(
                namespace=str(row[0]),
                topic=str(row[1]),
                payload=json.loads(row[2]) if row[2] is not None else None,
                idempotency_key=str(row[3]) if row[3] is not None else None,
            )
            for row in rows
        ]


class SqliteMigrationHarness:
    """`MigrationHarness` — the schemas and damage a local file can have."""

    latest_version = 1
    historical = ("empty", "documents-only")
    refusals = ("checksum", "ahead", "partial")

    def lay_down(self, root: Path, schema: str) -> None:
        if schema == "empty":
            return
        if schema == "documents-only":
            # The legacy file: derived keys only, so opening it is not the
            # legacy-import refusal (runtime keys there would rightly be).
            connection = sqlite3.connect(root / DB_NAME)
            try:
                connection.executescript(
                    "CREATE TABLE documents "
                    "(key TEXT PRIMARY KEY, payload TEXT, revision INTEGER);"
                )
                connection.execute(
                    "INSERT INTO documents (key, payload, revision) "
                    "VALUES ('fresh', '{}', 1)"
                )
                connection.commit()
            finally:
                connection.close()
            return
        raise ValueError(f"unknown historical schema {schema!r}")

    def damage(self, root: Path, refusal: str) -> None:
        path = root / DB_NAME
        if refusal == "checksum":
            self._execute(path, "UPDATE schema_migrations SET checksum = 'doctored'")
        elif refusal == "ahead":
            self._execute(
                path,
                "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
                "VALUES (2, 'future', 'x', 'now')",
            )
        elif refusal == "partial":
            # One table of revision 0001 gone while its ledger row stays:
            # a schema that claims to be current and is not.
            self._execute(path, "DROP TABLE workflow_steps")
        else:
            raise ValueError(f"unknown damage {refusal!r}")

    def version(self, root: Path) -> int:
        path = root / DB_NAME
        if not path.is_file():
            return 0
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "schema_migrations" not in tables:
                return 0
            [(version,)] = connection.execute(
                "SELECT max(version) FROM schema_migrations"
            )
            return int(version or 0)
        finally:
            connection.close()

    @staticmethod
    def _execute(path: Path, sql: str) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(sql)
            connection.commit()
        finally:
            connection.close()
