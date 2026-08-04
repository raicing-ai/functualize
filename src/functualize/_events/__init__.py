"""Cross-cutting concerns package for functualize internal layers.

Contains event infrastructure available to all layers:
- EventBus: Trie-based topic router for structured event emission
- HookRegistry: Lifecycle hook management (facade over EventBus pattern)
- PropagationContext: Request context / correlation tracking via contextvars
- PerfTimeline: Timing marks for boot and execution performance tracking

This package imports ONLY from `_types/`, `_primitives/`, and Python stdlib.
No other internal package imports are allowed.
"""

from functualize._events.bus import (
    EventBus,
    EventCatalog,
    EventMetadata,
    StructuredEvent,
    SubscriberCallback,
    SubscriptionHandle,
    TrieRouter,
)
from functualize._events.hooks import (
    ConfigHookEvent,
    HookDecision,
    HookEvent,
    HookRegistry,
)
from functualize._events.perf import PerfReport, PerfTimeline, Phase
from functualize._events.tracing import (
    ContextToken,
    PropagationContext,
    current_context,
    detach,
    start_span,
    start_trace,
)

__all__ = [
    # EventBus and related types
    "EventBus",
    "EventCatalog",
    "EventMetadata",
    "StructuredEvent",
    "SubscriberCallback",
    "SubscriptionHandle",
    "TrieRouter",
    # Hook registry
    "ConfigHookEvent",
    "HookDecision",
    "HookEvent",
    "HookRegistry",
    # Performance timeline
    "PerfReport",
    "PerfTimeline",
    "Phase",
    # Propagation context / tracing
    "ContextToken",
    "PropagationContext",
    "current_context",
    "detach",
    "start_span",
    "start_trace",
]
