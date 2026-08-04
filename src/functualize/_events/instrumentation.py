"""Instrumentation point helpers for combining EventBus and MiddlewareStack.

This module provides `instrument_point()` which wraps an operation with:
- Event emission (.start / .end / .error) through the EventBus
- Middleware execution through the MiddlewareStack

Key design properties:
- **Zero-cost when uninstrumented**: If no subscribers are registered on the
  EventBus AND no middleware is registered for the operation point, the
  operation is called directly without any wrapping overhead.
- **Fault-tolerant instrumentation**: If event emission or middleware raises,
  the operation's result is still returned (or its exception still raised).
  Instrumentation failures are logged but never interrupt the operation.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._events.bus import EventBus
    from functualize._events.middleware_stack import MiddlewareStack

logger = logging.getLogger(__name__)


def instrument_point(
    event_bus: EventBus,
    middleware_stack: MiddlewareStack,
    operation_point: str,
    operation_fn: Callable[..., Any],
    *args: Any,
    resource: str = "",
    related: list[str] | None = None,
    **extra_payload: Any,
) -> Any:
    """Execute an operation with instrumentation (events + middleware).

    Zero-cost path: if no subscribers on event_bus and no middleware registered
    for this operation_point, calls operation_fn directly without any wrapping.

    Otherwise:
    1. Emits ``{operation_point}.start`` event
    2. Executes middleware_stack.execute(operation_point, operation_fn, *args)
       or calls operation_fn directly if no middleware is registered
    3. On success: emits ``{operation_point}.end`` event with ``duration_ms``
    4. On failure: emits ``{operation_point}.error`` event with ``duration_ms``,
       ``error_type``, and ``message``

    IMPORTANT: If event emission or middleware raises, the operation's result
    is still returned (or the operation's exception is still raised) —
    instrumentation failures are logged but never interrupt the operation.

    Args:
        event_bus: The EventBus instance for event emission.
        middleware_stack: The MiddlewareStack for middleware execution.
        operation_point: Name of the instrumentation point (e.g., "job.execute").
        operation_fn: The operation to instrument.
        *args: Arguments to pass to operation_fn.
        resource: Primary resource identifier for events.
        related: Related resource identifiers.
        **extra_payload: Additional payload fields for events.

    Returns:
        The operation's return value.

    Raises:
        Any exception raised by operation_fn (after emitting the error event).
    """
    # ZERO-COST PATH: no subscribers and no middleware → direct call
    if not event_bus.has_subscribers and not middleware_stack.has_middleware(
        operation_point
    ):
        return operation_fn(*args)

    # Emit start event (fault-tolerant)
    try:
        event_bus.emit(
            f"{operation_point}.start",
            resource=resource,
            related=related,
            **extra_payload,
        )
    except Exception as exc:
        logger.error(f"Failed to emit {operation_point}.start: {exc}", exc_info=True)

    # Execute with middleware (or direct if no middleware)
    start_time = time.perf_counter()
    try:
        if middleware_stack.has_middleware(operation_point):
            result = middleware_stack.execute(operation_point, operation_fn, *args)
        else:
            result = operation_fn(*args)
    except BaseException as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000
        # Emit error event (fault-tolerant)
        try:
            event_bus.emit(
                f"{operation_point}.error",
                resource=resource,
                related=related,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                message=str(exc),
                **extra_payload,
            )
        except Exception as emit_exc:
            logger.error(
                f"Failed to emit {operation_point}.error: {emit_exc}",
                exc_info=True,
            )
        raise

    duration_ms = (time.perf_counter() - start_time) * 1000
    # Emit end event (fault-tolerant)
    try:
        event_bus.emit(
            f"{operation_point}.end",
            resource=resource,
            related=related,
            duration_ms=duration_ms,
            **extra_payload,
        )
    except Exception as exc:
        logger.error(f"Failed to emit {operation_point}.end: {exc}", exc_info=True)

    return result
