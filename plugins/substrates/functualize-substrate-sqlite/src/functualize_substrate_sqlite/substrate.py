"""A `StoreSubstrate` over SQLite. One table, six methods.

`store-substrate`/T5.

This plugin used to supply a **key-value store for one scope's job state**,
swapped in through `WorkflowScope.replace_state_store`. That was a seam one
level below the real one, and it is what made the split brain reachable: a
scope could keep its job state in SQLite while the *records* describing that
scope — which steps ran, where the walk stopped, what a human approved — stayed
on the filesystem. A resumed run then found its steps and not its variables.

So the plugin now supplies a **substrate**, and every store moves together or
none does.

## Why this is the interesting implementation

`JsonFileSubstrate` is the baseline; it exists to change nothing. This one is
the reason the port exists at all:

- **It is a local file, and says so.** `SQLITE_PROFILE` declares
  `multi_machine=False`: the database is a path on this host, reachable from
  every process on it and from nothing else. SQLite is not what would make a
  gate blocked on one runner resumable on another, and nothing here claims it.
- **`lock` is one lock.** A transaction covers every key it is given, so the
  lock-order inversion an external review found between the scope lock and the
  state lock is removed *by construction* rather than by asking callers to
  acquire in a careful order. `JsonFileSubstrate` can only sort; this cannot
  invert.
- **`write(expect=)` is a real compare-and-swap**, done in SQL, so it does not
  depend on the caller holding anything.

## The revision

A monotonically increasing integer per document, assigned by the write. Unlike
`JsonFileSubstrate`'s content hash it does not survive rewriting the same
content, and that is fine: a revision is an opaque token to compare, and the
port says so.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from functualize._types.errors import SubstrateUnreadableError
from functualize._types.protocols import Revision, Stored

__all__ = ["SQLiteSubstrate", "SqliteCheckpointBusyError"]

_LOG = logging.getLogger(__name__)

#: A checkpoint copies the write-ahead log, so it can collide with a reader and
#: wait for it. That wait belongs to *maintenance*, not to the write that is
#: already committed: it is bounded far below the write timeout, so a long read
#: elsewhere in the process cannot hold a caller inside a write it has returned.
#: `checkpoint()` is the retry.
_CHECKPOINT_TIMEOUT_MS = 100
_WRITE_TIMEOUT_MS = 10000


class SqliteCheckpointBusyError(Exception):
    """Another connection prevented a WAL checkpoint.

    A reader or writer can block the fold. This error says nothing about
    whether a document write happened; retry only the checkpoint after the
    other transaction ends.
    """

    #: Retrying the checkpoint is the remedy, and it is idempotent.
    retryable = True

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            f"SQLite WAL checkpoint for {path} was busy; retry checkpoint() "
            "after the other transaction ends"
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    key      TEXT PRIMARY KEY,
    payload  TEXT NOT NULL,
    revision INTEGER NOT NULL
);
"""


class SQLiteSubstrate:
    """Documents in one SQLite table, reachable from any process."""

    __slots__ = ("_local", "_path")

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        #: One connection per thread. SQLite connections are not safe to share
        #: across threads, and `invoke_parallel` runs workers on threads that
        #: all reach the same substrate.
        self._local = threading.local()
        self._conn().executescript(_SCHEMA)

    @property
    def path(self) -> Path:
        """The database file."""
        return self._path

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._path), isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA busy_timeout={_WRITE_TIMEOUT_MS}")
            self._local.conn = conn
            self._local.depth = 0
        return conn

    def _fold(self) -> None:
        """Checkpoint a completed write when readers permit it.

        A write-ahead log is folded into the main file by a checkpoint, and
        SQLite takes one when the **last** connection to the database closes.
        That moment belongs to whoever happens to close last, not to the
        write: a caller that has already returned can watch the file change
        later, when a connection nobody is using is finalized, and whether
        that lands inside its call is allocation timing — the same store
        appeared to change on one Python minor version and not another, which
        is what made a dry run look like it wrote.

        A reader holding a WAL snapshot can prevent the checkpoint. That does
        not undo the committed write: this reports the retryable maintenance
        failure separately and leaves the write's result intact. The next write
        attempts another checkpoint; ``checkpoint()`` permits an explicit retry.
        Inside a transaction the outermost commit makes this attempt.

        The attempt is **bounded** by ``_CHECKPOINT_TIMEOUT_MS`` rather than by
        the write timeout, because a reader can hold the log for as long as it
        likes and a maintenance stall has no business inside a write that has
        already committed.

        The at-rest guarantee is a property of *this* connection, so the
        corrective change belongs here rather than in core store/reader
        ownership — the deviation from shape I-8 (``substrate.py``'s behaviour
        is unchanged) that is labelled below and recorded in `.spec/STATUS.md`
        → *sqlite-runtime-provider*.
        """
        # The write-path fold is this substrate's settled at-rest design. A
        # store/reader reference cycle may still delay finalization, but that
        # lifetime does not carry the fold guarantee. The corrective deviation
        # from shape I-8 is recorded in .spec/STATUS.md.
        if getattr(self._local, "depth", 0):
            return
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.in_transaction:
            return
        try:
            self.checkpoint()
        except (SqliteCheckpointBusyError, sqlite3.Error) as exc:
            # A reader holding the log is the expected case, so this is a
            # reported maintenance condition, never an exception out of a
            # committed write. `sqlite3.Error` is deliberate: *any* way the
            # fold fails is maintenance, and none of it may turn a write that
            # already committed into a failure the caller sees.
            _LOG.warning(
                "SQLite write to %s committed; its WAL checkpoint did not run: %s",
                self._path,
                exc,
            )

    def checkpoint(self) -> None:
        """Fold `-wal` into the main file now; a busy peer is retryable.

        Separate from a write on purpose: a write reports whether *the write*
        happened, and a checkpoint that another connection blocked is not reported
        through that result. This raises :class:`SqliteCheckpointBusyError`
        (``retryable``) while another transaction blocks the fold, and
        returns quietly when the database is already at rest — a truncating
        checkpoint of an empty log changes nothing.
        """
        conn = self._conn()
        if getattr(self._local, "depth", 0) or conn.in_transaction:
            raise RuntimeError("checkpoint requires a completed transaction")
        conn.execute(f"PRAGMA busy_timeout={_CHECKPOINT_TIMEOUT_MS}")
        try:
            busy, _log, _checkpointed = conn.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
        finally:
            conn.execute(f"PRAGMA busy_timeout={_WRITE_TIMEOUT_MS}")
        if busy:
            raise SqliteCheckpointBusyError(self._path)

    def close(self) -> None:
        """Release this thread's connection; the next call opens a fresh one.

        The port has no ``close`` and a substrate normally lives as long as the
        process, so nothing here is required for correctness of a read or a
        write. It is required for **when the file changes**.

        A connection to a write-ahead-log database is closed in two steps: the
        close checkpoints, and the checkpoint folds `-wal` back into the main
        file and deletes it. That is the same checkpoint a reader can block, and
        a close cannot report the difference — so the fold that carries a
        guarantee is the one on the write path, with :meth:`checkpoint` as its
        retry. A `sqlite3.Connection` cannot be freed by
        reference counting alone — it holds its statement cache, and each
        cached statement holds the connection — so a *dropped* connection is
        closed whenever a cyclic collection happens to run. Until then the
        database keeps an un-checkpointed log and an open writer, and the
        collection lands wherever the allocator is: measured here, a deferred
        close inside an unrelated call rewrote a file the caller was promised
        would not move.

        Closing at the moment the substrate dies removes that timing from the
        picture. Safe to call twice, and the substrate stays usable afterwards.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return
        # Drop the reference first: a close that raises must not leave a dead
        # handle behind for the next call to reuse.
        self._local.conn = None
        self._local.depth = 0
        conn.close()

    def __del__(self) -> None:
        # A torn-down interpreter can have `sqlite3` gone already, and a
        # finalizer that raises is printed and ignored at best.
        with suppress(Exception):
            self.close()

    # ------------------------------------------------------------------
    # The port
    # ------------------------------------------------------------------

    def read(self, key: str) -> Stored | None:
        row = (
            self._conn()
            .execute("SELECT payload, revision FROM documents WHERE key = ?", (key,))
            .fetchone()
        )
        if row is None:
            return None
        try:
            data = json.loads(row[0])
        except ValueError as exc:
            raise SubstrateUnreadableError(key, str(exc)) from exc
        if not isinstance(data, dict):
            raise SubstrateUnreadableError(
                key, f"expected an object, found {type(data).__name__}"
            )
        return Stored(data=data, revision=Revision(str(row[1])))

    def write(
        self, key: str, payload: dict[str, Any], *, expect: Revision | None = None
    ) -> bool:
        """Replace the document, refusing when ``expect`` no longer matches.

        The compare and the write are **one statement**, so unlike the
        filesystem implementation this does not need the caller to hold a lock
        to be exact. That is the property a backend with no `flock` has to
        provide instead.
        """
        blob = json.dumps(payload, indent=2, sort_keys=True)
        conn = self._conn()
        if expect is None:
            conn.execute(
                "INSERT INTO documents (key, payload, revision) VALUES (?, ?, 1) "
                "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload, "
                "revision = documents.revision + 1",
                (key, blob),
            )
            self._fold()
            return True
        cursor = conn.execute(
            "UPDATE documents SET payload = ?, revision = revision + 1 "
            "WHERE key = ? AND revision = ?",
            (blob, key, expect),
        )
        if not cursor.rowcount:
            # A refused compare-and-swap wrote nothing: there is nothing to
            # fold, and no reason to make its caller wait on a reader's log.
            return False
        self._fold()
        return True

    @contextmanager
    def lock(self, *keys: str) -> Iterator[None]:
        """**One** lock, covering every key — the whole point of the port.

        A write transaction on the database excludes every other writer
        regardless of which keys they named, so a caller that takes state then
        scopes and a caller that takes scopes then state cannot deadlock
        against each other. `JsonFileSubstrate` sorts its per-file locks, which
        prevents a caller from inverting *within one call* and nothing more.

        Re-entrant per thread, because a store takes the lock around a
        read-modify-write that a wider batch may already hold.
        """
        conn = self._conn()
        depth = getattr(self._local, "depth", 0)
        self._local.depth = depth + 1
        try:
            if depth == 0:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    yield
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                else:
                    conn.execute("COMMIT")
                    self._local.depth = depth
                    self._fold()
            else:
                yield
        finally:
            self._local.depth = depth

    def clear(self, key: str) -> str | None:
        """Copy the document to a backup key and remove the original.

        Never decodes it — the escape hatch has to work on exactly the content
        :meth:`read` refuses.
        """
        conn = self._conn()
        row = conn.execute(
            "SELECT payload FROM documents WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        backup = f"{key}.bak"
        index = 1
        while conn.execute(
            "SELECT 1 FROM documents WHERE key = ?", (backup,)
        ).fetchone():
            backup = f"{key}.bak.{index}"
            index += 1
        conn.execute(
            "INSERT INTO documents (key, payload, revision) VALUES (?, ?, 1)",
            (backup, row[0]),
        )
        conn.execute("DELETE FROM documents WHERE key = ?", (key,))
        self._fold()
        return f"{self._path}#{backup}"

    def delete(self, key: str) -> bool:
        cursor = self._conn().execute("DELETE FROM documents WHERE key = ?", (key,))
        if not cursor.rowcount:
            return False
        self._fold()
        return True

    def describe(self, key: str) -> str:
        """The database, the key, and the payload size.

        A namespace key (``"scope-state/"``) is described in aggregate, as the
        port requires, because scope state is one document per run.
        """
        conn = self._conn()
        if key.endswith("/"):
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(LENGTH(payload)), 0) "
                "FROM documents WHERE key LIKE ?",
                (f"{key}%",),
            ).fetchone()
            count, total = int(row[0]), int(row[1])
            if not count:
                return "empty"
            plural = "" if count == 1 else "s"
            return f"{count} document{plural}, {total} B in {self._path}"
        row = conn.execute(
            "SELECT LENGTH(payload) FROM documents WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return f"{self._path}#{key} (absent)"
        return f"{self._path}#{key} ({int(row[0])} B)"
