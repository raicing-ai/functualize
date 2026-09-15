"""Persisting what the bus emits, against the run that emitted it.

`durable-run-layer`/T4. Spec AC-4, AC-5, AC-6.

The `EventBus` emits and forgets. Nothing in `src/` or `plugins/` wrote an event
anywhere, so a run's own account of itself — which config file it read, which
gate it stopped at, which step it retried — existed for the length of the
process and then did not. This is the subscriber that keeps it.

## Three constraints, and what each rules out

**AC-5 — the bus gains no file I/O.** Persistence is a subscriber, not a
publisher. `bus.py` is untouched by this feature and a gate asserts it stays
that way.

**No synchronous write on the emit path** (spec §3.2). `RunStore.append_event`
is a locked read-modify-write of the whole log; doing one per `emit` would put a
file lock in the middle of every event a job raises. So events are **buffered in
memory and flushed once**, when the run that owns them ends.

**AC-6 — a run with no subscriber costs no additional write.** That is the bus's
existing zero-cost bypass: with nothing subscribed, `emit` returns before it
builds an event object. Registering this subscriber is therefore what turns the
log on, and a bare engine in a test is unaffected.

## Which run an event belongs to

The hard part, and the reason this module owns a stack rather than the engine.

An event carries `trace_id` and `span_id`, not a run id. The run id is known by
`engine.run()`, and a job body emits from inside it — so the answer is *the
innermost run active on the emitting thread*.

**A thread-local stack, not a `ContextVar`.** That looks backwards, because a
`ContextVar` is the usual tool. It is the wrong one here for the reason
`RunContext._run_id` already records: `invoke_parallel` runs batch items on
worker threads, and a `ContextVar` set in the parent is **not** inherited by a
thread it did not create — the child would read an empty context and its events
would be filed under nothing.

A thread-local stack is correct for exactly the same reason it is usually not:
the push happens *on the thread that runs the job*, because `engine.run()` is
what pushes and `invoke_parallel` calls it on the worker. Nesting on one thread
(a workflow step, a dependency, an `rc.invoke` child) is a push and a pop, so
the innermost run wins — which is the run whose log the event belongs in.

Events emitted outside any run — boot, discovery, CLI parsing — see an empty
stack and are dropped. That is not a loss: they belong to the *process*, not to
a run, and inventing a run for them would make the log claim something false.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from functualize._primitives.run_format import EVENTS_PER_RUN_LIMIT

if TYPE_CHECKING:
    from functualize._events.bus import EventBus, StructuredEvent

__all__ = [
    "RunLogSubscriber",
    "current_run_id",
    "install_run_log",
    "pop_run",
    "push_run",
]

logger = logging.getLogger(__name__)

#: The innermost run on *this* thread. See the module docstring for why this is
#: thread-local rather than a `ContextVar`.
_local = threading.local()


def _stack() -> list[str]:
    stack = getattr(_local, "runs", None)
    if stack is None:
        stack = []
        _local.runs = stack
    return stack


def push_run(run_id: str | None) -> None:
    """Mark ``run_id`` as the run this thread is now executing.

    A `None` id — an unrecordable run, where `_open_run_record` could not write
    — pushes nothing, so its events fall to the enclosing run rather than being
    attributed to a record that does not exist.
    """
    if run_id is not None:
        _stack().append(run_id)


def pop_run(run_id: str | None) -> None:
    """Undo the matching :func:`push_run`.

    Pops by **identity of the value**, not blindly: a `finally` that popped
    unconditionally would corrupt the stack for the enclosing run the first time
    a push was skipped.
    """
    if run_id is None:
        return
    stack = _stack()
    if stack and stack[-1] == run_id:
        stack.pop()
    elif run_id in stack:  # pragma: no cover - defensive
        # Out-of-order close. Remove the right entry rather than the top, so one
        # mis-nesting does not misfile every event that follows.
        stack.remove(run_id)


def current_run_id() -> str | None:
    """The innermost run on this thread, or None outside any run."""
    stack = _stack()
    return stack[-1] if stack else None


class RunLogSubscriber:
    """Buffers a run's events in memory, writes them once when it ends.

    One instance per application, registered on the bus at boot. It holds a
    buffer per open run, so a parent and the child it invoked accumulate
    separately and neither waits on the other's write.
    """

    __slots__ = ("_buffers", "_limit", "_lock", "_store_for")

    def __init__(self, store_for: Any, *, limit: int = EVENTS_PER_RUN_LIMIT) -> None:
        """
        Args:
            store_for: Called with no arguments to get the `RunStore` to write
                to. A callable rather than a store, because the store resolves
                from the working directory and this object outlives any one run.
            limit: Per-run ring cap (risk R-c). A long walk emits without bound,
                and a log that grows with it would be the same unbounded-file
                defect `scopes.json` already had. Capped **in memory**, so an
                over-long run costs nothing extra on disk either.
        """
        self._store_for = store_for
        self._limit = limit
        self._buffers: dict[str, list[dict[str, Any]]] = {}
        # Guards `_buffers` only. Parallel batch items run on worker threads and
        # each appends to its own run's list, but the dict itself is shared.
        self._lock = threading.Lock()

    def __call__(self, event: StructuredEvent) -> None:
        """Bus callback. Buffers; never writes.

        Exceptions are swallowed by the bus, but an observation must not be
        able to disturb a run even so — a subscriber that raises on every event
        would fill the log with errors from a feature the user did not ask for.
        """
        run_id = current_run_id()
        if run_id is None:
            return
        try:
            record = {
                "event": event.event_name,
                "resource": event.resource,
                "payload": dict(event.payload),
            }
            if event.trace_id:
                record["trace_id"] = event.trace_id
            if event.span_id:
                record["span_id"] = event.span_id
            with self._lock:
                buffer = self._buffers.setdefault(run_id, [])
                buffer.append(record)
                if len(buffer) > self._limit:
                    del buffer[: len(buffer) - self._limit]
        except Exception:  # noqa: BLE001 - an observation never disturbs a run
            logger.debug("could not buffer a run-log event", exc_info=True)

    def close_run(self, run_id: str | None) -> None:
        """Flush ``run_id``'s buffer to the store. One write, at the end.

        Best-effort and silent, like the run record's own close: a store that
        cannot be written must not turn a job that ran fine into a failure.
        """
        if run_id is None:
            return
        with self._lock:
            events = self._buffers.pop(run_id, None)
        if not events:
            return
        try:
            store = self._store_for()
            with store.batch():
                for record in events:
                    store.append_event(run_id, record)
        except Exception:  # noqa: BLE001 - an observation never disturbs a run
            logger.debug("could not persist the run log", exc_info=True)

    def discard(self, run_id: str | None) -> None:
        """Drop a run's buffer without writing it.

        For a run whose record could not be opened: its events have nowhere to
        go, and keeping them would leak memory for the life of the process.
        """
        if run_id is None:
            return
        with self._lock:
            self._buffers.pop(run_id, None)


def install_run_log(bus: EventBus, store_for: Any) -> RunLogSubscriber:
    """Subscribe a `RunLogSubscriber` to every event on ``bus``.

    ``*`` rather than a prefix list: the log's value is that it holds whatever
    the run actually emitted, and a subscriber that enumerated event names would
    be a second copy of the catalogue, stale the first time one is added.
    """
    subscriber = RunLogSubscriber(store_for)
    bus.subscribe("*", subscriber)
    return subscriber
