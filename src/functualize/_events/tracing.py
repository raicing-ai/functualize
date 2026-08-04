"""Propagation context for trace correlation via contextvars.

Provides PropagationContext — an immutable snapshot of trace correlation state
used to attach trace_id and span_id to structured events. Uses contextvars for
async-safe context propagation.

Zero-cost when no trace is active: current_context() returns a
pre-allocated empty singleton without any allocation.

Only imports from _types/, _primitives/, and stdlib.
"""

from __future__ import annotations

import contextvars
import os
from dataclasses import dataclass, field

# Pre-allocated empty context singleton
_EMPTY_CONTEXT: PropagationContext | None = None


@dataclass(frozen=True, slots=True)
class PropagationContext:
    """Immutable snapshot of trace correlation state.

    Attributes:
        trace_id: 32 hex character trace identifier, or None if no trace.
        span_id: 16 hex character span identifier, or None if no trace.
        parent_span_id: Previous span_id when in a child span, or None.
        session_id: Optional session identifier for grouping operations.
        baggage: Arbitrary key-value pairs for cross-cutting concerns.
    """

    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    session_id: str | None = None
    baggage: dict[str, str] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """True if a trace has been started."""
        return self.trace_id is not None


def _empty_context() -> PropagationContext:
    """Return the pre-allocated empty context singleton."""
    global _EMPTY_CONTEXT
    if _EMPTY_CONTEXT is None:
        _EMPTY_CONTEXT = PropagationContext()
    return _EMPTY_CONTEXT


# The context variable storing the active propagation context
_context_var: contextvars.ContextVar[PropagationContext] = contextvars.ContextVar(
    "functualize_propagation_context"
)


class ContextToken:
    """Opaque handle for restoring previous context state."""

    __slots__ = ("_token",)

    def __init__(self, token: contextvars.Token[PropagationContext]) -> None:
        self._token = token


def _generate_trace_id() -> str:
    """Generate a random 32-character hex trace ID."""
    return os.urandom(16).hex()


def _generate_span_id() -> str:
    """Generate a random 16-character hex span ID."""
    return os.urandom(8).hex()


def current_context() -> PropagationContext:
    """Return the active PropagationContext, or empty singleton if no trace.

    Zero-cost when no trace: returns pre-allocated singleton without allocation.
    """
    return _context_var.get(_empty_context())


def start_trace(
    session_id: str | None = None,
    baggage: dict[str, str] | None = None,
) -> ContextToken:
    """Start a new trace, generating trace_id and span_id.

    The generated trace_id becomes the active trace_id immediately.

    Args:
        session_id: Optional session identifier.
        baggage: Optional initial baggage key-value pairs.

    Returns:
        ContextToken to restore previous context via detach().
    """
    ctx = PropagationContext(
        trace_id=_generate_trace_id(),
        span_id=_generate_span_id(),
        parent_span_id=None,
        session_id=session_id,
        baggage=baggage or {},
    )
    token = _context_var.set(ctx)
    return ContextToken(token)


def start_span(
    name: str | None = None,
    baggage_update: dict[str, str] | None = None,
) -> ContextToken:
    """Create a child span within the current trace.

    Sets current span_id as parent_span_id, generates new span_id,
    preserves trace_id.

    Args:
        name: Optional span name (for plugin use, not stored in context).
        baggage_update: Optional additional baggage entries.

    Returns:
        ContextToken to restore previous context via detach().

    Raises:
        RuntimeError: If no active trace exists.
    """
    current = current_context()
    if not current.is_active:
        raise RuntimeError(
            "Cannot start a span without an active trace. Call start_trace() first."
        )

    new_baggage = dict(current.baggage)
    if baggage_update:
        new_baggage.update(baggage_update)

    ctx = PropagationContext(
        trace_id=current.trace_id,
        span_id=_generate_span_id(),
        parent_span_id=current.span_id,
        session_id=current.session_id,
        baggage=new_baggage,
    )
    token = _context_var.set(ctx)
    return ContextToken(token)


def detach(token: ContextToken) -> None:
    """Restore the PropagationContext that existed before the token was created.

    Args:
        token: ContextToken returned by start_trace() or start_span().
    """
    _context_var.reset(token._token)
