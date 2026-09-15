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

- **It has no shared disk.** Two processes on different machines can reach the
  same database, which is what makes a gate blocked on one runner resumable on
  another (spec AC-3).
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
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from functualize._types.errors import SubstrateUnreadableError
from functualize._types.protocols import Stored

__all__ = ["SQLiteSubstrate"]

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
            conn.execute("PRAGMA busy_timeout=10000")
            self._local.conn = conn
            self._local.depth = 0
        return conn

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
        return Stored(data=data, revision=int(row[1]))

    def write(
        self, key: str, payload: dict[str, Any], *, expect: int | None = None
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
            return True
        cursor = conn.execute(
            "UPDATE documents SET payload = ?, revision = revision + 1 "
            "WHERE key = ? AND revision = ?",
            (blob, key, expect),
        )
        return cursor.rowcount == 1

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
        return f"{self._path}#{backup}"

    def delete(self, key: str) -> bool:
        cursor = self._conn().execute("DELETE FROM documents WHERE key = ?", (key,))
        return cursor.rowcount > 0

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
