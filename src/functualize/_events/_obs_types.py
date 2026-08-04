"""Core data types for the observability subsystem."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class StructuredEvent:
    """Immutable structured event emitted through the Event_Bus.

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
    """

    event_name: str
    description: str
    payload_fields: dict[str, str]  # field_name -> type description
    module: str  # Module where the event is emitted
    domain: str  # e.g., "job", "config", "plugin"


@dataclass(frozen=True, slots=True)
class OperationPoint:
    """Identifies a location where middleware can be applied.

    Each operation point has a unique name following the same naming grammar.
    """

    name: str
    description: str
    module: str
