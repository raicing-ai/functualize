"""Offline import of the legacy runtime documents into the relational schema.

The shape's seven steps (S-5, from the design package's 08), each a point the
process may die at without leaving two authorities:

1. **lock** — an exclusive ``flock`` on ``<db>.import.lock``; a second import
   gets exit 5. The kernel releases it if this process dies.
2. **snapshot and backup** — a consistent copy of the file (SQLite's backup
   API, so a WAL file is included) is kept beside it; everything is read from
   a copy, never from the source.
3. **import** — every runtime row *and* the ``runtime_cutover`` marker in
   **one** batch: all of it lands, or none of it.
4. **verify** — counts, identities, terminal/live status, state keys, sequence
   order and payload digests, read back from the tables and compared with the
   snapshot's manifest.
5. **cutover** — the marker is read back and must name the snapshot's digest.
6. **reopen and verify semantically** — a fresh `SqliteRuntimeStore` answers,
   through its read ports, what the documents said.
7. **keep the backup** — its path is reported; nothing removes it.

A failure at 4–6 deletes what step 3 wrote, marker included, in one batch:
the documents stay authoritative. A process killed after 3 leaves the marker
and the rows together; the next run finds the marker and finishes 4–7 instead
of importing again. So at every instant exactly one of {the documents, the
marker} is authoritative, and a second run of a finished import changes
nothing.

Refused records (`_legacy_source`) refuse the whole import before step 3,
with the source untouched (exit 3).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any

from functualize_substrate_sqlite._driver import LocalSqliteDriver
from functualize_substrate_sqlite._factory import (
    _LEGACY_RUNTIME_KEYS,
    _validated_marker,
)
from functualize_substrate_sqlite._legacy_source import (
    LegacySnapshot,
    Refusal,
    collisions,
    read_snapshot,
)
from functualize_substrate_sqlite._legacy_verify import (
    SOURCE,
    VerifyError,
    undo,
    verify_ports,
    verify_rows,
)
from functualize_substrate_sqlite._migrations import migrate
from functualize_substrate_sqlite._runtime_store import (
    DEFAULT_NAMESPACE,
    SqliteRuntimeStore,
)

__all__ = ["STEPS", "ImportReport", "Mode", "Outcome", "import_legacy"]

STEPS = (
    "lock",
    "snapshot and backup",
    "import",
    "verify",
    "cutover",
    "reopen and verify semantically",
    "keep the backup",
)

CAP_NOTE = (
    "The legacy stores kept a bounded history (500 records each by default): "
    "terminal runs and scopes evicted before this import were already gone and "
    "could not be imported."
)


class Outcome(IntEnum):
    """Exit codes, `contracts.md` §6."""

    IMPORTED = 0
    USAGE = 2
    REFUSED = 3
    VERIFY_FAILED = 4
    LOCKED = 5


class Mode(IntEnum):
    IMPORT = 0
    RESUME = 1
    ROLLBACK = 2


@dataclass
class ImportReport:
    outcome: Outcome
    lines: list[str] = field(default_factory=list)
    backup: Path | None = None

    def say(self, line: str) -> None:
        self.lines.append(line)

    def text(self) -> str:
        return "\n".join(self.lines)


def import_legacy(
    db: Path,
    *,
    dry_run: bool = False,
    mode: Mode = Mode.IMPORT,
    on_step: Callable[[int], None] | None = None,
    now: datetime | None = None,
) -> ImportReport:
    """Run the seven steps on ``db``; ``on_step(n)`` is told when step ``n`` is done."""
    report = ImportReport(Outcome.IMPORTED)
    step = on_step or (lambda _n: None)
    if not db.is_file():
        report.outcome = Outcome.USAGE
        report.say(f"no database at {db}")
        return report
    with _locked(db) as held:
        if not held:
            report.outcome = Outcome.LOCKED
            report.say(f"another import holds {db}.import.lock")
            return report
        step(1)
        marker, born_relational = _cutover(db)
        if born_relational:
            report.say("born relational; nothing to import")
            return report
        if mode is Mode.ROLLBACK:
            return _rollback_only(db, marker, report)
        if marker is not None:
            return _resume(db, marker, report, step, now)
        if mode is Mode.RESUME:
            report.outcome = Outcome.USAGE
            report.say("no import to resume: no cutover marker is recorded")
            return report
        return _fresh(db, report, step, dry_run=dry_run, now=now)


def _fresh(
    db: Path,
    report: ImportReport,
    step: Callable[[int], None],
    *,
    dry_run: bool,
    now: datetime | None,
) -> ImportReport:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    backup = db.with_name(f"{db.name}.pre-import-{stamp}.bak")
    with tempfile.TemporaryDirectory(prefix="sqlite-import-") as scratch:
        snapshot = Path(scratch) / "snapshot.db"
        _copy(db, snapshot)
        digest = _source_digest(snapshot)
        legacy = read_snapshot(_working_copy(snapshot, scratch), DEFAULT_NAMESPACE, now)
        legacy.refusals += _existing(db, legacy)
        report.say(_summary(legacy))
        report.say(CAP_NOTE)
        if legacy.refusals:
            report.outcome = Outcome.REFUSED
            report.say(
                f"refused — {len(legacy.refusals)} record(s); nothing imported, source untouched:"
            )
            report.lines += [f"  {refusal}" for refusal in legacy.refusals]
            return report
        if dry_run:
            report.say("dry run — nothing written")
            return report
        shutil.copyfile(snapshot, backup)
    report.backup = backup
    step(2)

    driver = LocalSqliteDriver(db)
    try:
        migrate(driver)
        driver.batch(
            [
                *legacy.rows,
                (
                    "INSERT INTO runtime_cutover (source, imported_at, source_digest, backup_path) "
                    "VALUES (?, ?, ?, ?)",
                    (SOURCE, legacy.imported_at, digest, str(backup)),
                ),
            ]
        )
        step(3)
        return _finish(driver, legacy, digest, report, step)
    finally:
        driver.close()


def _resume(
    db: Path,
    marker: tuple[str, str],
    report: ImportReport,
    step: Callable[[int], None],
    now: datetime | None,
) -> ImportReport:
    """A marker exists: the import landed. Finish steps 4–7 against its backup."""
    digest, backup_path = marker
    backup = Path(backup_path)
    report.backup = backup
    if not backup.is_file():
        report.outcome = Outcome.VERIFY_FAILED
        report.say(
            f"the recorded backup {backup} is missing; the import cannot be re-verified"
        )
        return report
    report.say(f"an import is already recorded (backup {backup}); verifying it")
    with tempfile.TemporaryDirectory(prefix="sqlite-import-") as scratch:
        legacy = read_snapshot(_working_copy(backup, scratch), DEFAULT_NAMESPACE, now)
    driver = LocalSqliteDriver(db)
    try:
        return _finish(driver, legacy, digest, report, step)
    finally:
        driver.close()


def _finish(
    driver: LocalSqliteDriver,
    legacy: LegacySnapshot,
    digest: str,
    report: ImportReport,
    step: Callable[[int], None],
) -> ImportReport:
    try:
        verify_rows(driver, legacy)
        step(4)
        recorded = driver.query(
            "SELECT source_digest FROM runtime_cutover WHERE source = ?", (SOURCE,)
        )
        if recorded != [(digest,)]:
            raise VerifyError(
                f"cutover marker reads {recorded!r}, expected digest {digest}"
            )
        step(5)
        verify_ports(SqliteRuntimeStore(driver), legacy)
        step(6)
    except VerifyError as failure:
        undo(driver, legacy)
        report.outcome = Outcome.VERIFY_FAILED
        report.say(
            f"verification failed — rolled back, the documents stay authoritative: {failure}"
        )
        return report
    report.say(
        f"imported and verified: {len(legacy.scope_ids)} scope(s), {len(legacy.run_ids)} run(s), "
        f"{len(legacy.request_ids)} input request(s)"
    )
    if legacy.synthesized_candidates:
        report.say(
            f"{legacy.synthesized_candidates} legacy deposit(s) carried as one accepted "
            f"candidate each (source 'legacy-import')"
        )
    report.say(f"backup kept at {report.backup}")
    step(7)
    return report


def _rollback_only(
    db: Path, marker: tuple[str, str] | None, report: ImportReport
) -> ImportReport:
    if marker is None:
        report.say("no import is recorded; nothing to roll back")
        return report
    backup = Path(marker[1])
    if not backup.is_file():
        report.outcome = Outcome.VERIFY_FAILED
        report.say(
            f"the recorded backup {backup} is missing; cannot tell which rows were imported"
        )
        return report
    with tempfile.TemporaryDirectory(prefix="sqlite-import-") as scratch:
        legacy = read_snapshot(_working_copy(backup, scratch), DEFAULT_NAMESPACE)
    driver = LocalSqliteDriver(db)
    try:
        undo(driver, legacy)
    finally:
        driver.close()
    report.backup = backup
    report.say(
        "rolled back: the imported rows and the cutover marker are gone; the documents are "
        "authoritative. Rows written by the app since the import are removed with them."
    )
    return report


# -- the parts ----------------------------------------------------------------


@contextlib.contextmanager
def _locked(db: Path) -> Iterator[bool]:
    path = db.with_name(f"{db.name}.import.lock")
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _copy(source: Path, target: Path) -> None:
    """A consistent copy, WAL included, read without opening the source for writing."""
    reader, writer = _readonly(source), sqlite3.connect(target)
    try:
        reader.backup(writer)
    finally:
        reader.close()
        writer.close()


def _working_copy(snapshot: Path, scratch: str) -> Path:
    """The document stores may tidy what they read; they read a throwaway copy."""
    copy = Path(scratch) / f"read-{snapshot.name}"
    shutil.copyfile(snapshot, copy)
    return copy


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _source_digest(snapshot: Path) -> str:
    conn = _readonly(snapshot)
    try:
        if "documents" not in _tables(conn):
            return hashlib.sha256(b"").hexdigest()
        rows = conn.execute(
            f"SELECT key, payload, revision FROM documents WHERE {_LEGACY_RUNTIME_KEYS} ORDER BY key"
        ).fetchall()
    finally:
        conn.close()
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _cutover(db: Path) -> tuple[tuple[str, str] | None, bool]:
    conn = _readonly(db)
    try:
        if "runtime_cutover" not in _tables(conn):
            return None, False
        rows = conn.execute(
            "SELECT source, imported_at, source_digest, backup_path "
            "FROM runtime_cutover ORDER BY source"
        ).fetchall()
    finally:
        conn.close()
    if any(row[0] == "born-relational" for row in rows):
        return None, _validated_marker(db, rows) == "born-relational"
    row = next((row for row in rows if row[0] == SOURCE), None)
    return (None if row is None else (str(row[2]), str(row[3] or ""))), False


def _existing(db: Path, legacy: LegacySnapshot) -> list[Refusal]:
    """Identity collisions with rows already in the tables, read without writing."""
    conn = _readonly(db)
    try:
        if not {"workflow_scopes", "runs"} <= _tables(conn):
            return []
        return collisions(_ReadOnly(conn), legacy)
    finally:
        conn.close()


class _ReadOnly:
    """The one `SqlDriver` member a collision check needs, over a read-only connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def query(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> list[tuple[Any, ...]]:
        return list(self._conn.execute(sql, parameters).fetchall())


def _summary(legacy: LegacySnapshot) -> str:
    return (
        f"found {len(legacy.scope_ids)} scope(s), {len(legacy.run_ids)} run(s), "
        f"{len(legacy.request_ids)} input request(s); source digest manifest {legacy.digest[:12]}"
    )
