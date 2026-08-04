"""Central event bus with TrieRouter-based subscriber routing.

The EventBus is the core component for structured event emission. It routes
events to subscribers via a TrieRouter supporting exact, prefix-wildcard,
and global-wildcard pattern matching.

Key properties:
- Zero-cost when uninstrumented: emit() returns after a single boolean check
  if no subscribers exist.
- Subscriber exceptions are logged at ERROR level; dispatch continues.
- Events are dispatched synchronously in registration order.
- PropagationContext (trace_id, span_id) is auto-attached to every event.

Only imports from _types/, _primitives/, and stdlib.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from functualize._events.tracing import current_context

logger = logging.getLogger(__name__)

# Compiled pattern for event name validation.
# Format: {domain}.{resource}.{action} with at least 3 dot-separated segments.
# Each segment starts with a lowercase letter followed by lowercase alphanumeric/underscores.
_EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,}$")


@dataclass(frozen=True, slots=True)
class StructuredEvent:
    """Immutable structured event emitted through the EventBus.

    Attributes:
        event_name: Hierarchical name following {domain}.{resource}.{action} grammar.
        resource: Primary resource identifier (e.g., file path, job name).
        related: Associated resource identifiers.
        payload: Event-specific data dictionary.
        timestamp: Seconds since epoch (from time.time()).
        trace_id: Active trace ID (auto-attached from PropagationContext).
        span_id: Active span ID (auto-attached from PropagationContext).
    """

    event_name: str
    resource: str
    related: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    trace_id: str | None = None
    span_id: str | None = None


@dataclass(frozen=True, slots=True)
class EventMetadata:
    """Machine-readable metadata for a registered instrumentation point.

    Used by the event catalog for plugin introspection.

    Attributes:
        event_name: The fully-qualified event name.
        description: Human-readable description.
        payload_fields: Mapping of field name to type description.
        module: Module where the event is emitted.
        domain: Domain category (e.g., "job", "config", "plugin").
    """

    event_name: str
    description: str
    payload_fields: dict[str, str]
    module: str
    domain: str


SubscriberCallback = Callable[[StructuredEvent], None]


class SubscriptionHandle:
    """Opaque handle returned by subscribe() for later unsubscription.

    Attributes (internal):
        _pattern: The subscription pattern (exact name, prefix wildcard, or "*").
        _callback: The registered subscriber callable.
        _id: Unique registration order identifier.
    """

    __slots__ = ("_pattern", "_callback", "_id")

    def __init__(self, pattern: str, callback: SubscriberCallback, id_: int) -> None:
        self._pattern = pattern
        self._callback = callback
        self._id = id_


class TrieRouter:
    """Prefix-trie router for efficient pattern matching of event subscribers.

    Supports three subscription patterns:
    - Exact match: "config.remote.fetch.end" matches only that specific event.
    - Prefix wildcard: "config.remote.*" matches all events starting with
      "config.remote." (any depth below that prefix).
    - Global wildcard: "*" matches all emitted events.

    Subscribers are tracked with monotonic registration IDs to ensure
    deterministic dispatch order regardless of pattern type.
    """

    __slots__ = ("_exact", "_prefix", "_global", "_counter")

    def __init__(self) -> None:
        self._exact: dict[str, list[tuple[int, SubscriberCallback]]] = {}
        self._prefix: dict[str, list[tuple[int, SubscriberCallback]]] = {}
        self._global: list[tuple[int, SubscriberCallback]] = []
        self._counter: int = 0

    @property
    def has_subscribers(self) -> bool:
        """Fast boolean check — True if any subscriber is registered anywhere.

        Used as the first gate in the zero-cost bypass path.
        """
        return bool(self._exact or self._prefix or self._global)

    def has_subscribers_for(self, event_name: str) -> bool:
        """Check if any subscriber would match the given event name.

        This is the second-level check in the zero-cost path: even if
        subscribers exist globally, this confirms at least one would
        actually receive this specific event before constructing it.

        Args:
            event_name: The fully-qualified event name to check.

        Returns:
            True if at least one subscriber matches.
        """
        if self._global:
            return True
        if event_name in self._exact:
            return True
        # Check prefix matches by walking up the hierarchy
        parts = event_name.split(".")
        for i in range(1, len(parts)):
            prefix = ".".join(parts[:i])
            if prefix in self._prefix:
                return True
        return False

    def subscribe(
        self, pattern: str, callback: SubscriberCallback
    ) -> SubscriptionHandle:
        """Register a subscriber for the given pattern.

        Args:
            pattern: One of:
                - Exact event name (e.g., "config.remote.fetch.end")
                - Prefix wildcard ending with ".*" (e.g., "config.*")
                - Global wildcard "*"
            callback: Function receiving a StructuredEvent instance.

        Returns:
            SubscriptionHandle for later unsubscription via unsubscribe().
        """
        self._counter += 1
        handle = SubscriptionHandle(pattern, callback, self._counter)

        if pattern == "*":
            self._global.append((self._counter, callback))
        elif pattern.endswith(".*"):
            prefix = pattern[:-2]  # Strip trailing ".*"
            if prefix not in self._prefix:
                self._prefix[prefix] = []
            self._prefix[prefix].append((self._counter, callback))
        else:
            if pattern not in self._exact:
                self._exact[pattern] = []
            self._exact[pattern].append((self._counter, callback))

        return handle

    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        """Remove a subscriber by its handle.

        After unsubscription, the callback will no longer be invoked
        for any future events. Cleans up empty registry entries.

        Args:
            handle: The SubscriptionHandle returned by subscribe().
        """
        pattern = handle._pattern
        target_id = handle._id

        if pattern == "*":
            self._global = [(id_, cb) for id_, cb in self._global if id_ != target_id]
        elif pattern.endswith(".*"):
            prefix = pattern[:-2]
            if prefix in self._prefix:
                self._prefix[prefix] = [
                    (id_, cb) for id_, cb in self._prefix[prefix] if id_ != target_id
                ]
                if not self._prefix[prefix]:
                    del self._prefix[prefix]
        else:
            if pattern in self._exact:
                self._exact[pattern] = [
                    (id_, cb) for id_, cb in self._exact[pattern] if id_ != target_id
                ]
                if not self._exact[pattern]:
                    del self._exact[pattern]

    def match(self, event_name: str) -> list[SubscriberCallback]:
        """Return all matching subscriber callbacks sorted by registration order.

        Collects callbacks from exact matches, prefix matches, and global
        subscribers, then sorts by their registration ID to ensure
        deterministic invocation order.

        Args:
            event_name: The fully-qualified event name to match against.

        Returns:
            List of callbacks in registration order.
        """
        results: list[tuple[int, SubscriberCallback]] = []

        # Exact matches
        if event_name in self._exact:
            results.extend(self._exact[event_name])

        # Prefix matches — walk up the hierarchy
        parts = event_name.split(".")
        for i in range(1, len(parts)):
            prefix = ".".join(parts[:i])
            if prefix in self._prefix:
                results.extend(self._prefix[prefix])

        # Global subscribers
        results.extend(self._global)

        # Sort by registration order (monotonic int ID)
        results.sort(key=lambda t: t[0])
        return [cb for _, cb in results]


class EventCatalog:
    """Registry of known event metadata for introspection.

    Plugins and framework internals register EventMetadata at startup
    so that subscribers can discover available events programmatically.
    """

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: dict[str, EventMetadata] = {}

    def register(self, metadata: EventMetadata) -> None:
        """Register event metadata.

        Args:
            metadata: The EventMetadata to register.
        """
        self._entries[metadata.event_name] = metadata

    def contains(self, event_name: str) -> bool:
        """Check if an event name is registered in the catalog.

        Args:
            event_name: The event name to check.

        Returns:
            True if registered.
        """
        return event_name in self._entries

    def all(self) -> dict[str, EventMetadata]:
        """Return the full event catalog mapping.

        Returns:
            Mapping of event names to their EventMetadata.
        """
        return dict(self._entries)


class EventBus:
    """Central event emission and subscriber routing.

    The EventBus is the primary interface for emitting structured events
    and registering subscribers. It delegates pattern matching to an
    internal TrieRouter and maintains an EventCatalog for introspection.

    Zero-cost guarantee: when no subscribers are registered, emit() returns
    after a single ``self._router.has_subscribers`` check — no event object
    construction, no string formatting, no time.time() call.

    Usage::

        bus = EventBus()
        handle = bus.subscribe("config.file.*", my_callback)
        bus.emit("config.file.parse.end", resource="/path/to/file.toml", duration=0.05)
        bus.unsubscribe(handle)
    """

    def __init__(self) -> None:
        self._router = TrieRouter()
        self._catalog = EventCatalog()

    @property
    def has_subscribers(self) -> bool:
        """True if any subscriber is registered on the bus."""
        return self._router.has_subscribers

    def subscribe(
        self, pattern: str, callback: SubscriberCallback
    ) -> SubscriptionHandle:
        """Subscribe to events matching the given pattern.

        Args:
            pattern: One of:
                - Exact event name ("config.file.parse.end")
                - Prefix wildcard ("config.*")
                - Global wildcard ("*")
            callback: Callable receiving a StructuredEvent.

        Returns:
            SubscriptionHandle for later unsubscription.
        """
        return self._router.subscribe(pattern, callback)

    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        """Remove a previously registered subscriber.

        Args:
            handle: The SubscriptionHandle returned by subscribe().
        """
        self._router.unsubscribe(handle)

    def emit(
        self,
        event_name: str,
        resource: str = "",
        related: list[str] | None = None,
        **payload: Any,
    ) -> None:
        """Emit a structured event to all matching subscribers.

        Implements a zero-cost bypass path:
        1. If no subscribers exist at all → return immediately.
        2. If no subscribers match this specific event → return.
        3. Validate event name format.
        4. Attach PropagationContext (trace_id, span_id).
        5. Construct StructuredEvent.
        6. Dispatch to matching callbacks in registration order.

        If a subscriber raises an exception, it is logged at ERROR level
        and dispatch continues to remaining subscribers.

        Args:
            event_name: Must match the grammar
                ``{domain}.{resource}.{action}`` (at least 3 dot-separated
                segments of lowercase alphanumeric/underscores).
            resource: Primary resource identifier (e.g., file path, job name).
            related: Optional list of associated resource identifiers.
            **payload: Arbitrary event-specific key-value data.
        """
        # ZERO-COST CHECK 1: bail if no subscribers at all
        if not self._router.has_subscribers:
            return

        # ZERO-COST CHECK 2: bail if no subscribers match this event
        if not self._router.has_subscribers_for(event_name):
            return

        # Fast-path: known events in catalog skip regex validation
        if not self._catalog.contains(event_name) and not _EVENT_NAME_RE.match(
            event_name
        ):
            logger.warning(
                f"Invalid event name format: {event_name!r}. "
                f"Expected {{domain}}.{{resource}}.{{action}}."
            )
            return

        # Attach propagation context automatically
        ctx = current_context()
        event = StructuredEvent(
            event_name=event_name,
            resource=resource,
            related=related or [],
            payload=payload,
            trace_id=ctx.trace_id,
            span_id=ctx.span_id,
        )

        # Dispatch to subscribers synchronously in registration order
        callbacks = self._router.match(event_name)
        for callback in callbacks:
            try:
                callback(event)
            except Exception as exc:
                logger.error(
                    f"Subscriber {callback!r} raised during event "
                    f"'{event_name}': {exc}",
                    exc_info=True,
                )

    def catalog(self) -> dict[str, EventMetadata]:
        """Return the full event catalog for plugin introspection.

        Returns:
            Mapping of event names to their EventMetadata.
        """
        return self._catalog.all()

    def register_event_metadata(self, metadata: EventMetadata) -> None:
        """Register event metadata in the catalog.

        Allows plugins to register custom event metadata alongside
        framework-defined events.

        Args:
            metadata: The EventMetadata to register.
        """
        self._catalog.register(metadata)
