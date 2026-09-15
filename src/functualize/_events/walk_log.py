"""A walk's events, on the scope they advance, written as they happen.

`workflow-graph-semantics`/T5. Spec AC-10, AC-11.

The subscriber that makes `func builtin workflow watch` possible, and it exists
as a **separate** subscriber from `run_log` for one reason that decides
everything else about it.

## Why not the run log

`RunLogSubscriber` buffers a run's events in memory and writes them once, when
the run ends — for a good reason, stated there: a job body can emit thousands of
events, and `RunStore.append_event` is a locked read-modify-write of the whole
log, so one write per emit would put a file lock in the middle of every event a
job raises.

That design is exactly wrong for watching. A log flushed when the run ends
arrives too late for anybody following a walk that is still going; a watcher
would see nothing and then everything. **Live and buffered are incompatible, so
this is a second subscriber and not a flag on the first.**

The cost argument does not carry over either. A walk emits a handful of events
per node — start, end, and one for the walk itself — and it is *already* taking
one lock per node to record the step. Writing through here adds an append to a
list, on a path that was going to take the lock anyway.

## Why the scope, and not the run

A scope is advanced by *several* runs across a resume. Filing walk events under
the run would scatter one workflow's history across as many logs as it took to
finish it, and a watcher would have to find them all and merge them — which is
the ordering problem `seq` exists to avoid, reintroduced one level up. The scope
is the thing being watched, so the scope is where its account of itself lives.

## Persistence is a subscriber, not a publisher

`durable-run-layer`'s AC-5, honoured rather than worked around: `bus.py` gains
no file I/O and the walker does no writing of its own. The walker emits; this
files it. A test that wants the walk without the log simply does not install
this, which is what every walker test does today.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._events.bus import EventBus, StructuredEvent

__all__ = ["WalkLogSubscriber", "install_walk_log"]

logger = logging.getLogger(__name__)

#: The events this files, and the prefix it subscribes to.
#:
#: A prefix rather than a list of names: the walker owns this namespace, and a
#: subscriber enumerating the events it expects would be a second copy of the
#: walker's vocabulary, stale the first time a node kind is added.
WALK_EVENT_PREFIX = "workflow."


class WalkLogSubscriber:
    """Appends `workflow.*` events to the scope named in their payload.

    One instance per application, registered on the bus at boot.
    """

    __slots__ = ("_store_for",)

    def __init__(self, store_for: Any) -> None:
        """
        Args:
            store_for: Called with no arguments for the `ScopeStore` to write
                to. A callable rather than a store, for `run_log`'s reason: the
                store resolves from the engine's substrate and this object
                outlives any one walk.
        """
        self._store_for = store_for

    def __call__(self, event: StructuredEvent) -> None:
        """Bus callback. Writes through — see the module docstring.

        The scope comes from the payload, never from the resource. `resource`
        is the workflow's *name*, which is what a reader wants to see and is
        not unique: two concurrent runs of one workflow would file into each
        other's log.

        Exceptions are swallowed by the bus, and again here, because an
        observation must not be able to disturb a walk. A scope that has since
        been taken by another runner refuses this write by fencing, which is
        correct and is not an error worth surfacing.
        """
        scope_id = event.payload.get("scope_id")
        if not isinstance(scope_id, str) or not scope_id:
            return
        try:
            payload = {k: v for k, v in event.payload.items() if k != "scope_id"}
            self._store_for().append_event(
                scope_id,
                {
                    "event": event.event_name,
                    "resource": event.resource,
                    "at": event.timestamp,
                    "payload": payload,
                },
            )
        except Exception:  # noqa: BLE001 - an observation never disturbs a walk
            logger.debug("could not append a walk event", exc_info=True)


def install_walk_log(bus: EventBus, store_for: Any) -> WalkLogSubscriber:
    """Subscribe a `WalkLogSubscriber` to the walker's events on ``bus``."""
    subscriber = WalkLogSubscriber(store_for)
    bus.subscribe(f"{WALK_EVENT_PREFIX}*", subscriber)
    return subscriber
