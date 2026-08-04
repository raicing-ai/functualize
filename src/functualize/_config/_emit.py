"""Forward-compatible emit points for observability instrumentation.

These functions are called at key moments during config resolution.
Initially they are no-ops. The observability-hooks system replaces
the emit implementation with structured event emission when installed
via the EventBusAdapter.

This module MUST NOT import heavy dependencies — it's called on every
config operation.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class EventSink(Protocol):
    """Protocol for receiving structured config events.

    The EventBusAdapter implements this to route config events through
    the observability EventBus. Plugins can register a sink to receive
    events without the full EventBus being present.
    """

    def emit(self, event_name: str, **payload: Any) -> None: ...


# Module-level sink (replaceable by observability adapter or plugin)
_sink: EventSink | None = None


def set_event_sink(sink: EventSink | None) -> None:
    """Replace the global event sink. Called by observability adapter.

    After the EventBusAdapter is installed, this function is monkey-patched
    to raise RuntimeError — callers should use app.event_bus.subscribe()
    instead.

    Args:
        sink: An EventSink implementation, or None to clear.
    """
    global _sink
    _sink = sink


def emit(event_name: str, *, resource: str = "", **payload: Any) -> None:
    """Emit a structured event if a sink is registered, otherwise no-op.

    Zero-cost when no sink: checks ``_sink is None`` and returns immediately
    without any allocation, string formatting, or time measurement.

    Args:
        event_name: Hierarchical event name (e.g., "config.path.resolve.start").
        resource: Explicit resource identifier (replaces heuristic derivation).
        **payload: Event-specific keyword arguments.
    """
    if _sink is not None:
        _sink.emit(event_name, resource=resource, **payload)
