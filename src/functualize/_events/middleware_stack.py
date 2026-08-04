"""Per-operation-point middleware registry and execution.

DISTINCT from functualize.job._middleware which handles per-job RunContext
wrapping. This module handles observability middleware at instrumentation points
(config operations, plugin loading, CLI parsing, etc.).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator
from typing import Any

logger = logging.getLogger(__name__)


class MiddlewareHandle:
    """Opaque handle for removing registered middleware.

    Returned by ``MiddlewareStack.register()`` and passed to
    ``MiddlewareStack.remove()`` to deregister a middleware.
    """

    __slots__ = ("_point", "_id")

    def __init__(self, point: str, id_: int) -> None:
        self._point = point
        self._id = id_


class OperationMiddlewareEntry:
    """A registered middleware for a specific operation point.

    Stores the middleware callable along with ordering metadata used
    to sort the execution chain by ``(priority, registration_order)``.
    """

    __slots__ = ("middleware", "priority", "_registration_order", "_id")

    def __init__(
        self,
        middleware: Callable[[dict[str, Any]], Generator[Any, Any]],
        priority: int,
        registration_order: int,
        id_: int,
    ) -> None:
        self.middleware = middleware
        self.priority = priority
        self._registration_order = registration_order
        self._id = id_


class MiddlewareStack:
    """Per-operation-point middleware registry.

    Middleware registered here wraps specific framework operations
    (config resolution, plugin loading, etc.) — NOT job execution
    (which uses ``functualize.context.middleware.MiddlewareRegistry``).

    Each middleware is a yield-based generator receiving a mutable context dict::

        def my_middleware(ctx: dict[str, Any]) -> Generator[Any, Any, None]:
            # Pre-operation: ctx contains operation metadata
            span = tracer.start_span(ctx["operation_point"])
            ctx["span"] = span
            try:
                result = yield  # Operation executes; result is sent back
            except Exception as exc:
                span.record_exception(exc)
                raise
            finally:
                span.end()

    Execution guarantees:

    - **Zero-cost when uninstrumented**: If no middleware is registered for an
      operation point, the operation is called directly without allocating
      generators or context dictionaries.
    - **Priority ordering**: Middleware sorted by ``(priority, registration_order)``
      where lower priority values are outermost (execute first).
    - **Shared context**: All middleware in a chain share the same mutable ``ctx``
      dict, allowing earlier middleware to store state for later ones.
    - **Exception propagation**: If the operation raises, the exception is thrown
      into each started middleware generator (in reverse order) for cleanup.
    """

    def __init__(self) -> None:
        self._points: dict[str, list[OperationMiddlewareEntry]] = {}
        self._counter: int = 0

    def has_middleware(self, operation_point: str) -> bool:
        """Check if any middleware is registered for the given operation point.

        Args:
            operation_point: The operation point name to check.

        Returns:
            True if at least one middleware is registered for this point.
        """
        entries = self._points.get(operation_point)
        return bool(entries)

    @property
    def has_any_middleware(self) -> bool:
        """True if any middleware is registered at any operation point.

        Useful for fast short-circuit checks at instrumentation sites.
        """
        return bool(self._points)

    def register(
        self,
        operation_point: str,
        middleware: Callable[[dict[str, Any]], Generator[Any, Any]],
        priority: int = 0,
    ) -> MiddlewareHandle:
        """Register middleware for an operation point.

        Args:
            operation_point: The operation to wrap (e.g., ``"job.execute"``).
            middleware: Yield-based generator callable receiving a context dict.
                The generator should yield exactly once; the operation's return
                value is sent back via the yield expression.
            priority: Execution priority. Lower values execute first (outermost).
                Middleware with equal priority execute in registration order.
                Default is 0.

        Returns:
            An opaque handle for later removal via ``remove()``.
        """
        self._counter += 1
        entry = OperationMiddlewareEntry(
            middleware=middleware,
            priority=priority,
            registration_order=self._counter,
            id_=self._counter,
        )
        if operation_point not in self._points:
            self._points[operation_point] = []
        self._points[operation_point].append(entry)
        return MiddlewareHandle(operation_point, self._counter)

    def remove(self, handle: MiddlewareHandle) -> None:
        """Remove a previously registered middleware.

        Args:
            handle: The handle returned by ``register()``.

        If the handle refers to a middleware that has already been removed or
        an unknown operation point, this is a no-op.
        """
        point = handle._point
        target_id = handle._id
        if point in self._points:
            self._points[point] = [e for e in self._points[point] if e._id != target_id]
            if not self._points[point]:
                del self._points[point]

    def execute(
        self,
        operation_point: str,
        operation_fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute the middleware chain around an operation.

        If no middleware is registered for the operation point, calls
        ``operation_fn`` directly (zero-cost bypass — no generator allocation,
        no context dict creation).

        The execution flow:

        1. Sort registered middleware by ``(priority, registration_order)``.
        2. Create a shared mutable context dict with operation metadata.
        3. **Pre-yield phase**: Start each middleware generator via ``next(gen)``.
        4. **Operation phase**: Call the wrapped operation.
        5. **Post-yield phase**: Send the result to generators in reverse order
           via ``gen.send(result)``, or throw the exception via ``gen.throw()``
           if the operation raised.

        Args:
            operation_point: The instrumentation point name.
            operation_fn: The wrapped operation callable.
            *args: Positional arguments passed to ``operation_fn``.
            **kwargs: Keyword arguments passed to ``operation_fn``.

        Returns:
            The operation's return value.

        Raises:
            Any exception raised by ``operation_fn`` (after propagating through
            middleware for cleanup).
        """
        entries = self._points.get(operation_point)
        if not entries:
            # ZERO-COST: direct invocation
            return operation_fn(*args, **kwargs)

        # Sort by (priority, registration_order)
        sorted_entries = sorted(
            entries, key=lambda e: (e.priority, e._registration_order)
        )

        # Build shared context dict
        ctx: dict[str, Any] = {
            "operation_point": operation_point,
            "args": args,
            "kwargs": kwargs,
        }

        # Pre-yield phase: start all generators
        generators: list[Generator[Any, Any]] = []
        for entry in sorted_entries:
            gen = entry.middleware(ctx)
            try:
                next(gen)
            except StopIteration:
                # Middleware didn't yield — skip it
                continue
            except BaseException as exc:
                # Pre-yield failure: propagate through already-started generators
                _throw_into_generators(generators, exc)
                raise
            generators.append(gen)

        # Execute the operation
        result: Any = None
        exception: BaseException | None = None
        try:
            result = operation_fn(*args, **kwargs)
        except BaseException as exc:
            exception = exc

        # Post-yield phase: send result or throw exception
        if exception is not None:
            _throw_into_generators(generators, exception)
            raise exception
        else:
            _send_result_to_generators(generators, result)

        return result


def _throw_into_generators(
    generators: list[Generator[Any, Any]],
    exception: BaseException,
) -> None:
    """Throw an exception into generators in reverse order for cleanup.

    Each generator receives the exception at its yield point so that
    try/except/finally blocks in middleware can execute cleanup logic.

    Middleware exceptions during cleanup are logged at ERROR level but
    do not interrupt cleanup of remaining generators.

    Args:
        generators: List of started middleware generators.
        exception: The exception to propagate.
    """
    for gen in reversed(generators):
        try:
            gen.throw(type(exception), exception, exception.__traceback__)
        except StopIteration:
            pass
        except BaseException as mw_exc:
            logger.error(f"Middleware raised during cleanup: {mw_exc}", exc_info=True)


def _send_result_to_generators(
    generators: list[Generator[Any, Any]],
    result: Any,
) -> None:
    """Send the operation result into generators in reverse order.

    Each generator receives the result at its yield point via ``gen.send()``,
    allowing post-yield logic to access the operation's return value.

    Middleware exceptions during post-yield are logged at ERROR level but
    do not interrupt post-yield processing of remaining generators.

    Args:
        generators: List of started middleware generators.
        result: The operation's return value to send.
    """
    for gen in reversed(generators):
        try:
            gen.send(result)
        except StopIteration:
            pass
        except BaseException as exc:
            logger.error(f"Middleware raised during post-yield: {exc}", exc_info=True)
