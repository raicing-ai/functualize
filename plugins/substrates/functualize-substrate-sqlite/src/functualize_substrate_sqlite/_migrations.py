"""Versioned, checksummed, forward-only schema migrations.

The contract is `contributor/reference/runtime-persistence-data-model.md` §7:

- a revision is ``(version, name, sql)`` and its checksum is ``sha256(sql)``;
- each revision is applied in **one batch** together with its
  ``schema_migrations`` row, so a crash leaves both or neither — and because
  the unit is a `batch()`, the same runner works over a driver with no
  interactive transaction;
- the recorded version is ``max(version)``; there is no down migration;
- the runner **refuses**, never repairs: an edited revision (checksum
  mismatch), a gap in the ledger, a ledger ahead of the shipped set, or
  runtime tables with no ledger at all (a partial or foreign schema) each
  raise :class:`MigrationRefused` with repair steps, and boot aborts.

It runs inside the store factory's ``prepare`` at boot step 6.5, before the
engine exists, so no job can run against a schema that is not current.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize_substrate_sqlite._driver import SqlDriver, Statement

__all__ = ["SHIPPED_MIGRATIONS", "Migration", "MigrationRefused", "migrate"]

_LEDGER = "schema_migrations"


@dataclass(frozen=True)
class Migration:
    """One forward revision of the runtime schema."""

    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    def statements(self) -> list[str]:
        """The revision split into single statements, triggers kept whole."""
        out: list[str] = []
        pending = ""
        for line in self.sql.splitlines(keepends=True):
            if not pending and (not line.strip() or line.lstrip().startswith("--")):
                continue
            pending += line
            if sqlite3.complete_statement(pending):
                out.append(pending.strip())
                pending = ""
        if pending.strip():
            raise ValueError(f"revision {self.version} ends inside a statement")
        return out


class MigrationRefused(Exception):  # noqa: N818 — names a refusal, as contracts §5 does
    """The database's schema history does not match the code's; boot refuses.

    Carries what the operator needs to act: the revision, both checksums when
    they differ, and the repair steps. Never retried and never worked around:
    guessing a repair is how a schema silently diverges.
    """

    def __init__(
        self,
        reason: str,
        *,
        version: int | None = None,
        expected_checksum: str | None = None,
        actual_checksum: str | None = None,
        repair: str,
    ) -> None:
        self.version = version
        self.expected_checksum = expected_checksum
        self.actual_checksum = actual_checksum
        self.repair = repair
        super().__init__(f"{reason} Repair: {repair}")


def _load(version: int, name: str) -> Migration:
    sql = (
        resources.files("functualize_substrate_sqlite")
        .joinpath("_schema", f"{version:04d}_{name}.sql")
        .read_text(encoding="utf-8")
    )
    return Migration(version=version, name=name, sql=sql)


#: Every revision this package ships, in order. Append only.
SHIPPED_MIGRATIONS: tuple[Migration, ...] = (_load(1, "runtime_schema"),)


#: The objects a revision's SQL creates, by name — what "this revision
#: applied" has to mean on disk, so a table that vanished while its ledger
#: row stayed is caught as the partial application it is (§7).
_CREATED = re.compile(
    r"CREATE\s+(?:TEMP\s+)?(?:UNIQUE\s+)?(?:TABLE|INDEX|TRIGGER|VIEW)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?"
    "[\"'`\\[]?"
    r"([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def migrate(
    driver: SqlDriver, migrations: Sequence[Migration] = SHIPPED_MIGRATIONS
) -> int:
    """Bring the database to the newest shipped revision; return its version.

    A database already current is a no-op (one read). Refuses rather than
    repairs — see the module docstring.
    """
    shipped = _check_shipped(migrations)
    ledger = _read_ledger(driver)
    _check_ledger(ledger, shipped)
    _check_objects(driver, ledger, shipped)
    current = max(ledger, default=0)
    for migration in shipped.values():
        if migration.version <= current:
            continue
        _apply(driver, migration)
        current = migration.version
    return current


def _check_shipped(migrations: Sequence[Migration]) -> dict[int, Migration]:
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"shipped revisions must be 1..n in order, got {versions}")
    return {m.version: m for m in migrations}


def _read_ledger(driver: SqlDriver) -> dict[int, str]:
    tables = {
        row[0]
        for row in driver.query("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if _LEDGER not in tables:
        foreign = (
            tables - {"documents"} - {t for t in tables if t.startswith("sqlite_")}
        )
        if foreign:
            raise MigrationRefused(
                f"The database has tables ({', '.join(sorted(foreign))}) but no "
                f"{_LEDGER} ledger, so which revision they belong to is unknown.",
                repair=(
                    "restore the database from a backup taken before the failed "
                    "upgrade, or move it aside and let boot create a fresh one."
                ),
            )
        return {}
    return {
        int(v): str(c)
        for v, c in driver.query(f"SELECT version, checksum FROM {_LEDGER}")
    }


def _check_ledger(ledger: dict[int, str], shipped: dict[int, Migration]) -> None:
    newest = max(shipped, default=0)
    ahead = sorted(v for v in ledger if v > newest)
    if ahead:
        raise MigrationRefused(
            f"The database records revision {ahead[-1]}, newer than this code's "
            f"newest ({newest}).",
            version=ahead[-1],
            repair="upgrade functualize-substrate-sqlite; a schema is never downgraded.",
        )
    expected = list(range(1, len(ledger) + 1))
    if sorted(ledger) != expected:
        missing = sorted(set(range(1, max(ledger) + 1)) - set(ledger))
        raise MigrationRefused(
            f"The {_LEDGER} ledger has a gap: revision(s) {missing} were never recorded.",
            version=missing[0],
            repair="restore the database from a backup; a gap means a revision was "
            "applied out of order or its record was removed.",
        )
    for version, recorded in sorted(ledger.items()):
        migration = shipped[version]
        if recorded != migration.checksum:
            raise MigrationRefused(
                f"Revision {version} ({migration.name}) was applied with a different "
                f"text than this code ships.",
                version=version,
                expected_checksum=migration.checksum,
                actual_checksum=recorded,
                repair="a shipped revision must never be edited; reinstall the "
                "package version that created this database, or restore a backup.",
            )


def _check_objects(
    driver: SqlDriver, ledger: dict[int, str], shipped: dict[int, Migration]
) -> None:
    """Every applied revision's objects exist; a missing one is partial state."""
    present = {row[0] for row in driver.query("SELECT name FROM sqlite_master")}
    for version in sorted(ledger):
        missing = sorted(
            name
            for name in _CREATED.findall(shipped[version].sql)
            if name not in present
        )
        if missing:
            raise MigrationRefused(
                f"The {_LEDGER} ledger records revision {version}, but its "
                f"objects ({', '.join(missing)}) are missing from the database.",
                version=version,
                repair="restore the database from a backup; a revision whose "
                "objects are gone while its ledger row stays is not a state "
                "this runner repairs by guessing.",
            )


def _apply(driver: SqlDriver, migration: Migration) -> None:
    statements: list[Statement] = [(sql, ()) for sql in migration.statements()]
    statements.append(
        (
            f"INSERT INTO {_LEDGER} (version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
            (
                migration.version,
                migration.name,
                migration.checksum,
                datetime.now(UTC).isoformat(),
            ),
        )
    )
    try:
        driver.batch(statements)
    except sqlite3.DatabaseError:
        # Another process may have applied the same revision between our read
        # and our batch. Its record, with the same checksum, is success; any
        # other state is the original error.
        ledger = _read_ledger(driver)
        if ledger.get(migration.version) != migration.checksum:
            raise
