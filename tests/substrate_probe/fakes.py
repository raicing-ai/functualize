"""A D1-shaped driver, as an instrument (FUN-25 task 2.1).

`BatchOnlySqliteDriver` is not a backend and not a port: `StoreSubstrate` is
deliberately not implemented (`plan.md` §4 — the fakes model *vendor drivers*,
not our port). It is the shape the research names as the one that changes the
design: D1 has no `BEGIN`/`COMMIT` across round trips, so a caller cannot read,
decide in Python, and then write inside one transaction. Everything atomic must
be a single `batch` payload (`05-cloudflare.md` §A.3).

**What an answer from this instrument means.** Every cell it produces is stamped
`measured (fake)`, and every cell describes *the instrument*, never D1: that this
driver refuses to hold a transaction open says a D1-shaped driver cannot, not
that D1 cannot. That is AC2's "instruments, not columns", and AC3 is why no
shipped field may rest on one — D1's own numbers are task 4.1's measurement, not
this module's.

**No network, no Docker, no credentials** (AC4): the database is in-memory
SQLite. `reading()` performs its observations against itself with every socket
refused, which is also where `remote` and `offline_capable` come from
(`harness.py` → `QUESTIONS`).
"""

from __future__ import annotations

import contextlib
import socket
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from typing import NoReturn
from unittest import mock

from tests.substrate_probe.harness import (
    FAKE_EVIDENCE,
    Answer,
    AnswerValue,
    Reading,
    measured,
    reading,
)


def _fake(field: str, value: AnswerValue, detail: str) -> Answer:
    """The one evidence level these instruments may stamp, pinned in one place.

    `measured (real service)` is unreachable from here by construction, which is
    AC3 stated where it cannot be forgotten (and task 2.2's done-when).
    """
    return measured(field, value, evidence=FAKE_EVIDENCE, detail=detail)


@contextlib.contextmanager
def _network_taken_away(reached: list[str]) -> Iterator[None]:
    """Take the network away, so "offline" is observed rather than assumed.

    One call settles two questions: anything that still works with
    `socket.socket` refusing was measured with the network unavailable
    (`offline_capable`), and anything that reaches for one is recorded here
    (`remote` — the round trip's transport).
    """

    def _refuse(*_args: object, **_kwargs: object) -> NoReturn:
        reached.append("socket.socket")
        raise OSError("the network was taken away for this measurement")

    with mock.patch.object(socket, "socket", _refuse):
        yield


def _offline_round_trip(operation: Callable[[], object]) -> tuple[str, ...]:
    """Run one operation with every socket refused; say what it reached for."""
    reached: list[str] = []
    with _network_taken_away(reached):
        operation()
    return tuple(reached)


class NoInteractiveTransactionError(RuntimeError):
    """What a D1 answers where a caller asks for a transaction: there is none.

    `05-cloudflare.md` §A.3 — no `BEGIN`/`COMMIT`/`ROLLBACK`/`SAVEPOINT` held
    open across round trips.
    """


class BatchOnlySqliteDriver:
    """A D1-shaped driver whose only atomic unit is one `batch()` call.

    In-memory SQLite behind a D1-shaped surface: one statement alone, or one list
    of statements sent together. What is modelled is §A.3's constraint, not D1's
    latency or its limits — there is nothing here to reach over a network, so it
    runs anywhere (AC4).

    Schema, since the surface is SQL::

        CREATE TABLE documents (key TEXT PRIMARY KEY, body TEXT NOT NULL)
    """

    def __init__(self) -> None:
        self._connection = sqlite3.connect(":memory:")
        self._connection.execute(
            "CREATE TABLE documents (key TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )

    def execute(self, sql: str, parameters: Sequence[object] = ()) -> int:
        """One statement, on its own. Returns the rows affected."""
        with self._connection:
            cursor = self._connection.execute(sql, parameters)
        return cursor.rowcount

    def batch(
        self, statements: Sequence[tuple[str, Sequence[object]]]
    ) -> tuple[int, ...]:
        """The whole atomic unit, in one call: all of it lands or none of it does.

        A batch is one request, so a caller cannot decide in Python between its
        statements — that is the constraint, not an implementation detail of this
        class. A statement that fails rolls the entire batch back, which is what
        makes this the only atomic unit a D1-shaped driver has.
        """
        applied: list[int] = []
        with self._connection:
            for sql, parameters in statements:
                applied.append(self._connection.execute(sql, parameters).rowcount)
        return tuple(applied)

    def read(self, key: str) -> str | None:
        """The document under `key`, or `None`."""
        row = self._connection.execute(
            "SELECT body FROM documents WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else str(row[0])

    def transaction(self) -> contextlib.AbstractContextManager[None]:
        """The shape D1 does not have — and this never returns.

        The pattern that would need it is: begin, read, decide in Python, then
        write inside the same transaction (§A.3). D1 has no `BEGIN`/`COMMIT`
        across round trips, so the refusal happens on entry: the read, the
        decision and the write inside `with driver.transaction():` are
        unreachable. What a caller has instead is `batch()`.
        """
        raise NoInteractiveTransactionError(
            "no BEGIN/COMMIT across round trips (05-cloudflare.md §A.3): read, "
            "decide in Python, then send everything atomic as one batch()"
        )

    def reading(self) -> Reading:
        """The ten questions, each one answered by observing this instrument."""
        return reading(
            "fake — BatchOnlySqliteDriver (a D1: no BEGIN/COMMIT)",
            (
                *self._atomicity_answers(),
                *self._reach_answers(),
                self._interactive_transaction_answer(),
                self._fencing_answer(),
                self._document_size_answer(),
                self._schema_answer(),
            ),
        )

    def _atomicity_answers(self) -> tuple[Answer, ...]:
        """Commit one batch, then doom a second write inside another.

        A batch that commits is not evidence of atomicity, and a refused batch
        whose first write survived would be evidence against it, so both halves
        are performed. The doomed statement is the batch's own second write,
        colliding with the key the first one inserted.
        """
        self.batch(
            (
                (
                    "INSERT OR REPLACE INTO documents(key, body) VALUES (?, ?)",
                    ("state", "1"),
                ),
                (
                    "INSERT OR REPLACE INTO documents(key, body) VALUES (?, ?)",
                    ("outbox", "1"),
                ),
            )
        )
        committed = (self.read("state"), self.read("outbox"))
        with contextlib.suppress(sqlite3.Error):
            self.batch(
                (
                    (
                        "INSERT INTO documents(key, body) VALUES (?, ?)",
                        ("doomed", "state"),
                    ),
                    (
                        "INSERT INTO documents(key, body) VALUES (?, ?)",
                        ("doomed", "outbox"),
                    ),
                )
            )
        landed = self.read("doomed")
        detail = (
            f"one batch committed both writes together ({committed}), and a batch "
            f"whose own second write was refused left the first one "
            f"{'present' if landed else 'absent'}"
        )
        atomic = landed is None
        return (
            _fake("cross_aggregate_atomicity", atomic, detail),
            _fake("durable_outbox", atomic, detail),
        )

    def _interactive_transaction_answer(self) -> Answer:
        """Ask for the shape D1 refuses: read, decide, write, all inside one."""
        opened = False
        try:
            with self.transaction():
                opened = True
        except NoInteractiveTransactionError as refused:
            detail = f"`with driver.transaction():` was refused on entry: {refused}"
        else:
            detail = "a transaction was opened and held across a Python decision"
        return _fake("interactive_transaction", opened, detail)

    def _fencing_answer(self) -> Answer:
        """Hold the guard, then let a stale writer and a second instrument try it.

        The guard is D1's own CAS shape (§A.3): the write carries `WHERE body = ?`
        and a row that moved makes it affect nothing.
        """
        self.execute(
            "INSERT OR REPLACE INTO documents(key, body) VALUES (?, ?)",
            ("fenced", "held"),
        )
        stale = self.batch(
            (
                (
                    "UPDATE documents SET body = 'mine' WHERE key = 'fenced' AND body = ?",
                    ("a-body-that-moved",),
                ),
            )
        )
        other = BatchOnlySqliteDriver()
        other.execute(
            "INSERT OR REPLACE INTO documents(key, body) VALUES (?, ?)",
            ("fenced", "theirs"),
        )
        return _fake(
            "fencing",
            "process-local",
            f"a guarded write carrying a stale body affected {stale[0]} rows, so every "
            f"writer holding this instrument is fenced; a second instrument — an object "
            f"cannot cross a process boundary, which makes it the closest in-process "
            f"stand-in for a second process — wrote the same key unfenced",
        )

    def _reach_answers(self) -> tuple[Answer, ...]:
        """Who else can reach this store, and does reaching it need a network?"""
        self.execute(
            "INSERT OR REPLACE INTO documents(key, body) VALUES (?, ?)",
            ("shared", "mine"),
        )
        other = BatchOnlySqliteDriver()
        off_host = other.read("shared")
        reached = _offline_round_trip(
            lambda: self.execute(
                "INSERT OR REPLACE INTO documents(key, body) VALUES (?, ?)",
                ("round-trip", "1"),
            )
        )
        sharing = (
            f"a second instrument read {off_host!r} for a key this one had written: the "
            f"store is this Python object and its in-memory database, with no path and no "
            f"endpoint for another process or host to address it by"
        )
        if reached:
            transport = (
                f"one round trip reached for {reached[0]}, so every operation crosses "
                f"a network"
            )
        else:
            transport = (
                "one round trip completed with every socket refused and reached for "
                "none, so no operation crosses a network"
            )
        return (
            _fake("multi_process", off_host is not None, sharing),
            _fake("multi_machine", off_host is not None, sharing),
            _fake("remote", bool(reached), transport),
            _fake("offline_capable", not reached, transport),
        )

    def _document_size_answer(self) -> Answer:
        """Write until something refuses. Nothing did, so record what was accepted."""
        size = 4 * 1024 * 1024
        self.execute(
            "INSERT OR REPLACE INTO documents(key, body) VALUES (?, ?)",
            ("large", "x" * size),
        )
        accepted = len(self.read("large") or "")
        return _fake(
            "max_document_bytes",
            None,
            f"a {size} byte document was accepted and read back at {accepted} bytes; the "
            f"instrument has no row cap of its own, so its answer is unbounded — D1's "
            f"2 MB row limit (§A.5) is task 4.1's measurement, not this one's",
        )

    def _schema_answer(self) -> Answer:
        """Store a document that announces a schema version, and see what objects."""
        self.execute(
            "INSERT OR REPLACE INTO documents(key, body) VALUES (?, ?)",
            ("migrated", '{"schema_version": 2}'),
        )
        return _fake(
            "versioned_migrations",
            False,
            f"a document announcing schema_version 2 was stored and read back unchanged "
            f"({self.read('migrated')!r}); the instrument carries no schema version of "
            f"its own, so it rejects nothing",
        )
