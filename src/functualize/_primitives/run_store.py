"""Typed accessors over the run log.

``RunStore`` is the only thing that reads or writes run records. It sits on
:mod:`functualize._primitives.run_format`, which owns the file format, locking,
atomic write, and the discard-on-anything-unusable read.

**Why a third store beside `StateStore` and `ScopeStore`.** The same reason
there is a third file: their read rules are opposites, and a store's read
behaviour is the thing most easily got wrong by someone who assumes the
neighbouring rule applies. `ScopeStore` fails closed because a scope is the only
trace of work in flight. This one degrades, because a run record is an
*observation* — losing it costs history, not work.

**What it is not.** It is not the history ring. `func builtin history` shows the
handful of things a user launched, capped at 200, excluding nested and parallel
children on purpose so a deep workflow cannot evict them. The run log records
**every** run through `engine.run()`, children included, because its question is
"what happened in this project" rather than "what did I ask for". The two
coexist; `durable-run-layer`/T2's gate exists to prove the ring was not
disturbed.

**Write discipline.** Every mutation is a locked read-modify-write, so two
processes recording different runs merge rather than clobber. A caller making
several writes for one run takes the lock once with :meth:`RunStore.batch`.
"""

from __future__ import annotations

import os
import secrets
import socket
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.run_format import (
    EVENTS_PER_RUN_LIMIT,
    RUNS_FILENAME,
    clear_runs,
    load_runs,
    resolve_runs_path,
    runs_lock,
    save_runs,
    update_runs,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Crockford base32, ULID's alphabet: no I, L, O or U, so a run id read aloud
#: or copied out of a log cannot become a different one.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _now() -> str:
    """UTC timestamp, ISO-8601 — the spelling every other record here uses."""
    return datetime.now(UTC).isoformat()


#: Guards `_LAST`, so two threads of one process cannot mint the same id or
#: mint them out of order.
_ID_LOCK = threading.Lock()

#: The last `(milliseconds, tail)` this process minted, for the monotonic rule
#: below.
_LAST: tuple[int, int] | None = None

#: 16 Crockford characters of tail — 80 bits.
_TAIL_MAX = (1 << 80) - 1


def _encode(value: int, length: int) -> str:
    return "".join(
        _CROCKFORD[(value >> shift) & 0x1F] for shift in range((length - 1) * 5, -1, -5)
    )


def new_run_id() -> str:
    """A fresh run id: ``run-`` plus a **monotonic** ULID.

    **Sortable, so "recent" needs no index.** The first 10 characters encode the
    millisecond, so lexicographic order is chronological order and the ring in
    `run_format._trim` keeps the newest N with `sorted()` — no timestamp
    parsing, and no confusion between two machines whose clocks disagree about
    sub-second ordering.

    **Monotonic within a process**, which a plain ULID is not: several runs
    opened in one millisecond share a timestamp prefix, and a freshly drawn
    random tail then orders them arbitrarily. `rc.invoke_parallel` opens a batch
    of runs in a few microseconds, so that is the common case here rather than
    the exotic one — and "the most recent five runs" coming back shuffled is a
    bug a reader would blame on the store. Within a millisecond the tail is
    **incremented** rather than redrawn (the ULID spec's monotonic variant), so
    insertion order is preserved exactly.

    Across processes ordering is by time, which is the best any id can do
    without coordination.
    """
    global _LAST
    with _ID_LOCK:
        ms = int(time.time() * 1000)
        if _LAST is not None and _LAST[0] == ms and _LAST[1] < _TAIL_MAX:
            ms, tail = _LAST[0], _LAST[1] + 1
        elif _LAST is not None and _LAST[0] > ms:
            # A clock that went backwards — NTP, a VM resume. Keep minting under
            # the last millisecond seen rather than emitting an id that sorts
            # before runs already recorded.
            ms, tail = _LAST[0], _LAST[1] + 1
        else:
            tail = secrets.randbits(80) >> 1  # headroom to increment into
        _LAST = (ms, tail)
    return f"run-{_encode(ms, 10)}{_encode(tail, 16)}"


def runner_identity() -> str:
    """Who is running: ``<host>/pid-<n>``.

    Not a uuid: when a lease looks stuck, the question is *which machine and
    which process*, and an opaque token sends the reader to a log to find out.
    A hostname that cannot be read degrades to ``unknown`` rather than raising —
    identifying the runner is never worth failing a run over.
    """
    try:
        host = socket.gethostname() or "unknown"
    except OSError:  # pragma: no cover - documented on some platforms
        host = "unknown"
    return f"{host}/pid-{os.getpid()}"


class RunStore:
    """Read and write run records and their events."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._batch: dict[str, Any] | None = None

    @classmethod
    def for_project(cls, start: Path | str) -> RunStore:
        """Build a store at the project's resolved run-log path."""
        return cls(resolve_runs_path(Path(start)))

    @classmethod
    def beside_state(cls, state_path: Path | str) -> RunStore:
        """Build a store beside a given state file.

        The sibling rule applied to an explicit path, so
        ``StateStore(tmp / "state.json")`` in a test finds ``tmp / "runs.json"``
        with no extra wiring and the three files cannot land in different
        directories.
        """
        return cls(Path(state_path).with_name(RUNS_FILENAME))

    @property
    def path(self) -> Path:
        """The run log this store reads and writes."""
        return self._path

    # ------------------------------------------------------------------
    # Read / write plumbing
    # ------------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        """Current envelope — the open batch if one is active, else the file."""
        if self._batch is not None:
            return self._batch
        return load_runs(self._path)

    def _mutate(self, mutate: Any) -> None:
        """Apply ``mutate`` to the envelope, honouring an open batch."""
        if self._batch is not None:
            mutate(self._batch)
            return
        update_runs(self._path, mutate)

    @contextmanager
    def batch(self) -> Iterator[RunStore]:
        """Hold the lock for many mutations, writing once at the end.

        Writes on clean exit only: an exception inside the block discards the
        block's mutations rather than persisting some of them.
        """
        if self._batch is not None:  # already batching — reuse the outer one
            yield self
            return
        with runs_lock(self._path):
            self._batch = load_runs(self._path)
            try:
                yield self
                save_runs(self._path, self._batch)
            finally:
                self._batch = None

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def open_run(self, record: dict[str, Any]) -> str:
        """Record a run as started, returning its id.

        ``record`` is the shape in `schema.md` §2 minus the fields this method
        fills: ``run_id``, ``started_at`` and ``status``. An explicit ``run_id``
        is honoured so a caller that already told someone the id can use it.

        **No argument values, ever** — only ``args_hash``, the same rule the
        history ring follows. A run log is read by more people than a job's
        caller, and an argument may be a secret.
        """
        run_id = str(record.get("run_id") or new_run_id())
        entry = {k: v for k, v in record.items() if k != "run_id"}
        entry.setdefault("status", "running")
        entry.setdefault("started_at", _now())
        entry.setdefault("ended_at", None)
        entry.pop("kwargs", None)  # belt and braces: never store argument values
        entry.pop("arguments", None)

        def _apply(envelope: dict[str, Any]) -> None:
            envelope.setdefault("runs", {})[run_id] = entry

        self._mutate(_apply)
        return run_id

    def close_run(self, run_id: str, status: str, **extra: Any) -> None:
        """Mark a run finished. A run this store never opened is ignored.

        Ignored rather than raised: the log is an observation, and a writer that
        crashed between opening and closing has already told the reader what it
        needs to know — the record stays ``running`` and derives as abandoned.
        Raising here would turn a lost observation into a failed run.
        """

        def _apply(envelope: dict[str, Any]) -> None:
            runs = envelope.get("runs")
            if not isinstance(runs, dict):
                return
            entry = runs.get(run_id)
            if not isinstance(entry, dict):
                return
            entry["status"] = status
            entry["ended_at"] = _now()
            entry.update(extra)

        self._mutate(_apply)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """One run record, or None."""
        runs = self._read().get("runs")
        entry = runs.get(run_id) if isinstance(runs, dict) else None
        return dict(entry) if isinstance(entry, dict) else None

    def run_ids(self) -> list[str]:
        """Every run id, oldest first.

        Sorted rather than insertion-ordered: ids are ULIDs, so this is
        chronological, and it stays chronological after the ring trims.
        """
        runs = self._read().get("runs")
        return sorted(runs) if isinstance(runs, dict) else []

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """The newest ``limit`` runs, newest first, each with its id."""
        runs = self._read().get("runs")
        if not isinstance(runs, dict):
            return []
        out = []
        for run_id in sorted(runs, reverse=True)[: max(0, limit)]:
            entry = runs[run_id]
            if isinstance(entry, dict):
                out.append({"run_id": run_id, **entry})
        return out

    def children_of(self, run_id: str) -> list[dict[str, Any]]:
        """Runs whose ``parent_run_id`` is ``run_id``, oldest first.

        The relationship history deliberately drops: a nested `rc.invoke` child
        and a parallel batch item both belong to the run that launched them, and
        the run log is where that tree is answerable.
        """
        runs = self._read().get("runs")
        if not isinstance(runs, dict):
            return []
        out = [
            {"run_id": rid, **entry}
            for rid, entry in sorted(runs.items())
            if isinstance(entry, dict) and entry.get("parent_run_id") == run_id
        ]
        return out

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def append_event(self, run_id: str, event: dict[str, Any]) -> int:
        """Append one event to a run's log, returning its sequence number.

        ``seq`` is assigned here and is monotonic per run, so a reader can
        replay in order **without comparing timestamps** — which two processes
        on two clocks cannot do reliably.

        Appending to a run this store never opened is allowed: the subscriber
        that writes events and the code that opens records are deliberately not
        coordinated (spec AC-5, the bus does no file I/O), and dropping an event
        because its record has been trimmed away would make the log lie about
        what it saw.
        """
        seq_box: list[int] = [0]

        def _apply(envelope: dict[str, Any]) -> None:
            events = envelope.setdefault("events", {})
            entries = events.setdefault(run_id, [])
            if not isinstance(entries, list):
                entries = []
                events[run_id] = entries
            seq = len(entries) + 1
            seq_box[0] = seq
            entries.append({"seq": seq, "at": _now(), **event})
            if len(entries) > EVENTS_PER_RUN_LIMIT:
                del entries[: len(entries) - EVENTS_PER_RUN_LIMIT]

        self._mutate(_apply)
        return seq_box[0]

    def events_for(self, run_id: str) -> list[dict[str, Any]]:
        """A run's events, in sequence order."""
        events = self._read().get("events")
        entries = events.get(run_id) if isinstance(events, dict) else None
        if not isinstance(entries, list):
            return []
        return sorted(
            (e for e in entries if isinstance(e, dict)),
            key=lambda e: e.get("seq", 0),
        )

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear(self) -> Path | None:
        """Move the run log aside, returning where it went, or None if absent."""
        return clear_runs(self._path)
