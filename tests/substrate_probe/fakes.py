"""Three vendor-driver constraints, as instruments (FUN-25 tasks 2.1 and 2.2).

None of these is a backend and none is a port: `StoreSubstrate` is deliberately
not implemented (`plan.md` §4 — the fakes model *vendor drivers*, not our port).
Each class is a driver-shaped stand-in for the one constraint the research names
as decisive, so Tier A can exercise the harness with no network, no Docker and no
credentials (AC4):

- `BatchOnlySqliteDriver` — a D1, which has no `BEGIN`/`COMMIT`: read, decide in
  Python, then send **one** batch (`05-cloudflare.md` §A.3).
- `FakeObjectStore` — an S3: conditional writes per key, and no atomicity across
  keys (`06-s3.md` §4.1).
- `FakeItemStore` — a DynamoDB: `TransactWriteItems`, atomic across items.

**What an answer from these instruments means.** Every cell they produce is
stamped `measured (fake)`, and every cell describes *the instrument*, never the
vendor whose shape it borrows: that `BatchOnlySqliteDriver` refuses to hold a
transaction open says a D1-shaped driver cannot, not that D1 cannot. That is
AC2's "instruments, not columns", and AC3 is why no shipped field may rest on one
— the vendors' own numbers are tasks 4.1–4.3's measurement, not this module's.

**No network, no Docker, no credentials** (AC4): every instrument is a Python
object with an in-memory SQLite database or a dict behind it. Each `reading()`
performs its observations against itself with every socket refused, which is also
where `remote` and `offline_capable` come from (`harness.py` → `QUESTIONS`).
"""

from __future__ import annotations

import contextlib
import hashlib
import socket
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
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


class PreconditionFailedError(RuntimeError):
    """What S3 answers with 412: the conditional write's condition did not hold."""


class FakeObjectStore:
    """An S3-shaped object store: conditional writes per key, no atomicity across keys.

    `06-s3.md` §4.1 — AWS states it plainly: "There is no way to make atomic
    updates across keys." Every write names exactly one key, and a conditional
    write is refused when its condition does not hold, so the store's only atomic
    unit is one object.

    An object is its body plus an ETag, which is what `If-Match` compares against.
    """

    def __init__(self) -> None:
        self._objects: dict[str, tuple[str, str]] = {}

    def put(self, key: str, body: str) -> str:
        """Unconditional write — S3 has no multi-key form of one. Returns the ETag."""
        etag = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
        self._objects[key] = (body, etag)
        return etag

    def get(self, key: str) -> str | None:
        """The object's body, or `None`."""
        stored = self._objects.get(key)
        return None if stored is None else stored[0]

    def put_if_absent(self, key: str, body: str) -> str:
        """`If-None-Match: *` — create only, refusing when the key is already there."""
        if key in self._objects:
            raise PreconditionFailedError(
                f"{key} was already there and this write was conditioned on its absence"
            )
        return self.put(key, body)

    def put_if_match(self, key: str, body: str, etag: str) -> str:
        """`If-Match` — compare-and-swap on the ETag, refusing a stale one."""
        stored = self._objects.get(key)
        if stored is None or stored[1] != etag:
            raise PreconditionFailedError(
                f"{key} carries {None if stored is None else stored[1]!r} rather than "
                f"{etag!r}: the write lost its race and is refused, not queued"
            )
        return self.put(key, body)

    def reading(self) -> Reading:
        """The ten questions, each one answered by observing this instrument."""
        return reading(
            "fake — FakeObjectStore (an S3: no atomicity across keys)",
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
        """Advance the state, then have the outbox write that goes with it refused.

        Two keys are two calls and nothing binds them, so the write that landed is
        not undone by the one that did not — which is what a half-write looks like
        from outside.
        """
        self.put("outbox", "from an earlier run")
        self.put("state", "2")
        try:
            self.put_if_absent("outbox", "for this run")
        except PreconditionFailedError as refused:
            companion = f"the outbox write with it was refused ({refused})"
        else:
            companion = "the outbox write with it landed"
        observed = (self.get("state"), self.get("outbox"))
        detail = (
            f"the state write landed and {companion}, leaving {observed}: two calls and "
            f"no unit binding them, so the half-write is observable"
        )
        return (
            _fake("cross_aggregate_atomicity", False, detail),
            _fake("durable_outbox", False, detail),
        )

    def _interactive_transaction_answer(self) -> Answer:
        """Look for a transaction to hold open: an S3 has none to offer."""
        open_a_transaction = getattr(self, "transaction", None)
        if open_a_transaction is None:
            detail = (
                "there is no transaction surface at all: an S3's conditional write spans "
                "one object, so there is nothing to hold open across a decision"
            )
        else:
            detail = "a transaction was opened and held across a Python decision"
        return _fake("interactive_transaction", open_a_transaction is not None, detail)

    def _fencing_answer(self) -> Answer:
        """Let a stale writer and a second instrument try the same conditional write."""
        fresh = self.put("fenced", "held")
        try:
            self.put_if_match("fenced", "mine", "an-etag-that-moved")
        except PreconditionFailedError as refused:
            stale = f"a write carrying a stale ETag was refused ({refused})"
        else:
            stale = "a write carrying a stale ETag was accepted"
        other = FakeObjectStore()
        other.put("fenced", "theirs")
        return _fake(
            "fencing",
            "process-local",
            f"{stale}, and the ETag this instrument holds ({fresh!r}) is what every other "
            f"writer holding it would have to present; a second instrument — an object "
            f"cannot cross a process boundary, which makes it the closest in-process "
            f"stand-in for a second process — wrote the same key unfenced",
        )

    def _reach_answers(self) -> tuple[Answer, ...]:
        """Who else can reach this store, and does reaching it need a network?"""
        self.put("shared", "mine")
        other = FakeObjectStore()
        off_host = other.get("shared")
        reached = _offline_round_trip(lambda: self.put("round-trip", "1"))
        sharing = (
            f"a second instrument read {off_host!r} for a key this one had written: the "
            f"store is this Python object and its dict, with no path and no endpoint for "
            f"another process or host to address it by"
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
        self.put("large", "x" * size)
        accepted = len(self.get("large") or "")
        return _fake(
            "max_document_bytes",
            None,
            f"a {size} byte object was accepted and read back at {accepted} bytes; the "
            f"instrument has no size cap of its own, so its answer is unbounded — S3's "
            f"5 TB object limit is context, not a measurement, and task 4.3 measures it",
        )

    def _schema_answer(self) -> Answer:
        """Store an object that announces a schema version, and see what objects."""
        self.put("migrated", '{"schema_version": 2}')
        return _fake(
            "versioned_migrations",
            False,
            f"an object announcing schema_version 2 was stored and read back unchanged "
            f"({self.get('migrated')!r}); the instrument has no schema object at all, so "
            f"it rejects nothing",
        )


class TransactionCanceledError(RuntimeError):
    """What DynamoDB answers when a transaction's condition fails: nothing written."""


@dataclass(frozen=True, slots=True)
class Put:
    """One item in a `TransactWriteItems`, and the condition it has to meet."""

    key: str
    body: str
    only_if_absent: bool = False


class FakeItemStore:
    """A DynamoDB-shaped item store: `TransactWriteItems`, atomic across items.

    One request carries every item, each with its own condition, and a single
    violated condition cancels the whole transaction: no sibling item is written
    and no existing item is modified. That is the shape a D1 lacks (§A.3), and the
    one task 1.1 measured on floci.
    """

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def put(self, key: str, body: str) -> None:
        """Unconditional single-item write."""
        self._items[key] = body

    def get(self, key: str) -> str | None:
        """The item's body, or `None`."""
        return self._items.get(key)

    def transact_write(self, puts: Sequence[Put]) -> None:
        """Every item or none: every condition is checked before anything lands."""
        for put in puts:
            if put.only_if_absent and put.key in self._items:
                raise TransactionCanceledError(
                    f"{put.key}: its condition did not hold, so nothing in this "
                    f"transaction was written"
                )
        for put in puts:
            self._items[put.key] = put.body

    def reading(self) -> Reading:
        """The ten questions, each one answered by observing this instrument."""
        return reading(
            "fake — FakeItemStore (a DynamoDB: TransactWriteItems)",
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
        """One transaction, one violated condition, and what happened to the rest.

        The sibling item is written first in the request and the violation is the
        second item's, so an item that landed anyway would be visible here.
        """
        self.put("existing", "1")
        try:
            self.transact_write(
                (Put("sibling", "2"), Put("existing", "9", only_if_absent=True))
            )
        except TransactionCanceledError as cancelled:
            outcome = f"the transaction was cancelled ({cancelled})"
        else:
            outcome = "the transaction committed"
        sibling, existing = self.get("sibling"), self.get("existing")
        detail = (
            f"{outcome}: the item it would have written beside them is {sibling!r} and "
            f"the item whose condition it violated is {existing!r}, so the whole "
            f"transaction landed or none of it did"
        )
        atomic = (sibling, existing) == (None, "1")
        return (
            _fake("cross_aggregate_atomicity", atomic, detail),
            _fake("durable_outbox", atomic, detail),
        )

    def _interactive_transaction_answer(self) -> Answer:
        """Look for a transaction to hold open: `TransactWriteItems` is one request."""
        open_a_transaction = getattr(self, "transaction", None)
        if open_a_transaction is None:
            detail = (
                "there is no transaction surface to hold open: a transaction here is one "
                "request, so a Python decision cannot sit between its items"
            )
        else:
            detail = "a transaction was opened and held across a Python decision"
        return _fake("interactive_transaction", open_a_transaction is not None, detail)

    def _fencing_answer(self) -> Answer:
        """Let a stale writer and a second instrument try the same guarded write."""
        self.put("fenced", "held")
        try:
            self.transact_write((Put("fenced", "mine", only_if_absent=True),))
        except TransactionCanceledError as refused:
            stale = f"a conditional write against the held item was refused ({refused})"
        else:
            stale = "a conditional write against the held item was accepted"
        other = FakeItemStore()
        other.put("fenced", "theirs")
        return _fake(
            "fencing",
            "process-local",
            f"{stale}, so every writer holding this instrument is fenced; a second "
            f"instrument — an object cannot cross a process boundary, which makes it the "
            f"closest in-process stand-in for a second process — wrote the same item "
            f"unfenced",
        )

    def _reach_answers(self) -> tuple[Answer, ...]:
        """Who else can reach this store, and does reaching it need a network?"""
        self.put("shared", "mine")
        other = FakeItemStore()
        off_host = other.get("shared")
        reached = _offline_round_trip(lambda: self.put("round-trip", "1"))
        sharing = (
            f"a second instrument read {off_host!r} for an item this one had written: the "
            f"store is this Python object and its dict, with no path and no endpoint for "
            f"another process or host to address it by"
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
        self.put("large", "x" * size)
        accepted = len(self.get("large") or "")
        return _fake(
            "max_document_bytes",
            None,
            f"a {size} byte item was accepted and read back at {accepted} bytes; the "
            f"instrument enforces no item limit of its own, so its answer is unbounded — "
            f"DynamoDB's own item limit is task 4.2's measurement, not this one's",
        )

    def _schema_answer(self) -> Answer:
        """Store an item that announces a schema version, and see what objects."""
        self.put("migrated", '{"schema_version": 2}')
        return _fake(
            "versioned_migrations",
            False,
            f"an item announcing schema_version 2 was stored and read back unchanged "
            f"({self.get('migrated')!r}); the instrument is schemaless, so it has no "
            f"version to carry and nothing to reject",
        )
