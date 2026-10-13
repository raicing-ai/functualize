"""The SQL driver the runtime store speaks through: a batch, a query, a close.

`SqlDriver` is deliberately the shape a D1-like backend can offer: the only
atomic unit is one `batch()` call, so the store never needs `BEGIN` across
round trips — it buffers a transition's statements and sends them together
(`_transaction.py`). That is what lets `BatchOnlySqliteDriver` run the same
store (AC-5) and why the profile can declare `interactive_transaction=False`
and mean it.

`LocalSqliteDriver` is that shape over one local SQLite file:

- one connection per thread, every one of them closed by `close()`;
- `PRAGMA foreign_keys=ON` on each connection, since SQLite defaults it off
  per connection and a schema whose cascades silently do nothing is worse
  than no foreign keys at all;
- WAL for a file only — `:memory:` has no journal to switch, and one
  connection is shared by every thread there, because a second `:memory:`
  connection is a second, empty database;
- a bounded busy timeout, surfaced as `SqliteBusyError(retryable=True)` so a
  caller can tell "another process holds the write lock" from a broken
  statement (I-5);
- `batch()` is `BEGIN IMMEDIATE … COMMIT`: all of it or none of it.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "DEFAULT_BUSY_TIMEOUT_S",
    "LocalSqliteDriver",
    "SqlDriver",
    "SqliteBusyError",
    "Statement",
]

#: Long enough to ride out another process's short transition; short enough
#: that a stuck writer surfaces as an error a person sees.
DEFAULT_BUSY_TIMEOUT_S = 5.0

#: One statement and its parameters — the unit a batch is a list of.
Statement = tuple[str, Sequence[object]]

_MEMORY = ":memory:"


class SqliteBusyError(Exception):
    """Another connection held the write lock past the busy timeout.

    Retryable: nothing was applied, and the same batch may succeed once the
    other writer commits. Distinct from ``sqlite3.OperationalError`` so a
    caller never has to parse a message to know that.
    """

    retryable = True

    def __init__(self, path: str, timeout_s: float) -> None:
        self.path = path
        self.timeout_s = timeout_s
        super().__init__(
            f"SQLite database {path} stayed locked by another writer for "
            f"{timeout_s:g}s; nothing was applied and the batch can be retried."
        )


@runtime_checkable
class SqlDriver(Protocol):
    """What the runtime store needs from a SQL backend, and nothing more."""

    def batch(self, statements: Sequence[Statement]) -> tuple[int, ...]:
        """Apply every statement as one atomic unit; rows affected, per statement."""
        ...

    def query(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> list[tuple[Any, ...]]:
        """One read, outside any unit."""
        ...

    def close(self) -> None:
        """Release every connection this driver opened."""
        ...


class LocalSqliteDriver:
    """`SqlDriver` over one local SQLite file (or `:memory:`, for tests)."""

    def __init__(
        self, path: Path | str, *, busy_timeout_s: float = DEFAULT_BUSY_TIMEOUT_S
    ) -> None:
        self._path = str(path)
        self._timeout = busy_timeout_s
        self._memory = self._path == _MEMORY
        if not self._memory:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.RLock()
        self._connections: list[sqlite3.Connection] = []
        self._closed = False
        # Open one now, so an unusable path fails at construction — inside
        # `prepare`, which aborts boot — rather than on the first write.
        self._connection()

    def batch(self, statements: Sequence[Statement]) -> tuple[int, ...]:
        with self._serialised():
            conn = self._connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise self._translate(exc) from exc
            try:
                counts = tuple(
                    conn.execute(sql, params).rowcount for sql, params in statements
                )
                conn.execute("COMMIT")
            except BaseException as exc:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                if isinstance(exc, sqlite3.OperationalError):
                    raise self._translate(exc) from exc
                raise
            return counts

    def query(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> list[tuple[Any, ...]]:
        with self._serialised():
            try:
                return list(self._connection().execute(sql, parameters).fetchall())
            except sqlite3.OperationalError as exc:
                raise self._translate(exc) from exc

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for conn in self._connections:
                conn.close()
            self._connections.clear()
            self._local = threading.local()

    def open_connections(self) -> int:
        """How many connections are open now — what `close()` must bring to 0."""
        with self._lock:
            return len(self._connections)

    def _serialised(self) -> contextlib.AbstractContextManager[object]:
        # The shared `:memory:` connection is one per driver, so its users
        # take turns; a file's per-thread connections let SQLite arbitrate.
        return self._lock if self._memory else contextlib.nullcontext()

    def _connection(self) -> sqlite3.Connection:
        if self._closed:
            raise sqlite3.ProgrammingError(f"driver for {self._path} is closed")
        if self._memory:
            with self._lock:
                if not self._connections:
                    self._connections.append(self._open())
                return self._connections[0]
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open()
            self._local.conn = conn
            with self._lock:
                self._connections.append(conn)
        return conn

    def _open(self) -> sqlite3.Connection:
        # `check_same_thread=False` only so `close()` may close a connection
        # another thread opened; each thread still uses its own.
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(
                self._path,
                timeout=self._timeout,
                isolation_level=None,
                check_same_thread=False,
            )
            conn.execute("PRAGMA foreign_keys=ON")
            if not self._memory:
                conn.execute("PRAGMA journal_mode=WAL")
            return conn
        except sqlite3.OperationalError as exc:
            if conn is not None:
                conn.close()
            raise self._translate(exc) from exc
        except BaseException:
            if conn is not None:
                conn.close()
            raise

    def _translate(self, exc: sqlite3.OperationalError) -> Exception:
        if getattr(exc, "sqlite_errorcode", None) in (
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        ):
            return SqliteBusyError(self._path, self._timeout)
        return exc
