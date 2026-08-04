"""Generic middleware executor with yield-based generators.

Provides ``MiddlewareChain[TContext, TResult]`` — a composable chain-of-responsibility
executor supporting:

- Integer priority sorting (lower value executes first, default 100, range 0–999)
- Pre/post semantics via yield (code before yield = pre-phase, after = post-phase)
- Optional ``gen.send(result)`` for result-aware middleware
- Exception propagation in reverse order via ``generator.throw()``

Only imports from _types/ and stdlib — zero third-party runtime dependencies.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Generic, TypeVar

__all__ = ["MiddlewareChain"]

TContext = TypeVar("TContext")
TResult = TypeVar("TResult")

_MIN_PRIORITY = 0
_MAX_PRIORITY = 999
_DEFAULT_PRIORITY = 100


class _MiddlewareEntry(Generic[TContext, TResult]):
    """Internal storage for a registered middleware with priority metadata."""

    __slots__ = ("middleware", "priority", "_registration_order")

    def __init__(
        self,
        middleware: Callable[[TContext], Generator[None, TResult | None, None]],
        priority: int,
        registration_order: int,
    ) -> None:
        self.middleware = middleware
        self.priority = priority
        self._registration_order = registration_order


class MiddlewareChain(Generic[TContext, TResult]):
    """Generic middleware executor with yield-based generators.

    Supports:
    - Integer priority sorting (lower = first, default 100, range 0–999)
    - Pre/post semantics via yield
    - Optional gen.send(result) for result-aware middleware
    - Exception propagation in reverse order via generator.throw()

    Type Parameters:
        TContext: The context type passed to each middleware callable.
        TResult: The return type of the wrapped operation.

    Example::

        chain: MiddlewareChain[dict, str] = MiddlewareChain()

        def logging_middleware(ctx: dict):
            print(f"Before: {ctx}")
            result = yield  # receives operation result via gen.send()
            print(f"After: result={result}")

        chain.add(logging_middleware, priority=50)
        result = chain.execute({"user": "alice"}, lambda: "done")
    """

    __slots__ = ("_entries", "_counter", "_sorted_cache")

    def __init__(self) -> None:
        self._entries: list[_MiddlewareEntry[TContext, TResult]] = []
        self._counter: int = 0
        self._sorted_cache: list[_MiddlewareEntry[TContext, TResult]] | None = None

    def add(
        self,
        middleware: Callable[[TContext], Generator[None, TResult | None, None]],
        priority: int = _DEFAULT_PRIORITY,
    ) -> None:
        """Register a middleware callable with the given priority.

        Lower priority values execute first (outermost in the chain).
        Equal priorities execute in registration order.

        Args:
            middleware: A yield-based generator callable. Receives the context
                as its argument. Code before ``yield`` runs in pre-phase; code
                after ``yield`` runs in post-phase. The yield expression
                evaluates to the operation result (via ``gen.send(result)``)
                or ``None`` if the operation raised an exception.
            priority: Integer priority in range [0, 999]. Default is 100.

        Raises:
            ValueError: If priority is outside the valid range [0, 999].
        """
        if not (_MIN_PRIORITY <= priority <= _MAX_PRIORITY):
            msg = (
                f"Priority must be between {_MIN_PRIORITY} and {_MAX_PRIORITY}, "
                f"got {priority}"
            )
            raise ValueError(msg)

        entry: _MiddlewareEntry[TContext, TResult] = _MiddlewareEntry(
            middleware=middleware,
            priority=priority,
            registration_order=self._counter,
        )
        self._counter += 1
        self._entries.append(entry)
        # Invalidate sort cache
        self._sorted_cache = None

    def execute(
        self,
        context: TContext,
        operation: Callable[[], TResult],
    ) -> TResult:
        """Execute the middleware chain around an operation.

        Middleware runs in ascending priority order (lower first). Each
        middleware generator is advanced through its pre-phase (up to yield),
        then the operation runs, then middleware generators are resumed in
        reverse order with the operation result sent via ``gen.send(result)``.

        If the operation raises, generators receive the exception via
        ``generator.throw()`` in reverse order.

        If no middleware is registered, the operation is called directly
        with zero overhead.

        Args:
            context: The context object passed to each middleware.
            operation: A zero-argument callable that performs the core operation.

        Returns:
            The operation's return value.

        Raises:
            Any exception raised by middleware or the operation.
        """
        if not self._entries:
            return operation()

        sorted_entries = self._get_sorted()
        generators: list[Generator[None, TResult | None, None]] = []
        pre_yield_exception: BaseException | None = None

        # Pre-yield phase: start all generators in priority order
        for entry in sorted_entries:
            gen = entry.middleware(context)
            try:
                next(gen)
            except StopIteration:
                # Middleware didn't yield — skip silently
                continue
            except BaseException as exc:
                # Pre-yield exception: skip remaining middleware and the operation
                pre_yield_exception = exc
                break
            generators.append(gen)

        # If pre-yield raised, propagate through already-started middleware
        if pre_yield_exception is not None:
            _propagate_exception(generators, pre_yield_exception)
            raise pre_yield_exception

        # Execute the operation
        result: TResult
        operation_exception: BaseException | None = None
        try:
            result = operation()
        except BaseException as exc:
            operation_exception = exc
            # We still need to run post-yield phases with the exception
            final_exception = _resume_with_exception(generators, operation_exception)
            if final_exception is not None:
                raise final_exception from exc
            # Should not reach here since operation_exception is not None
            raise  # pragma: no cover

        # Post-yield phase: resume generators in reverse order with result
        post_exception = _resume_with_result(generators, result)
        if post_exception is not None:
            raise post_exception

        return result

    def _get_sorted(self) -> list[_MiddlewareEntry[TContext, TResult]]:
        """Return middleware sorted by priority then registration order (cached)."""
        if self._sorted_cache is None:
            self._sorted_cache = sorted(
                self._entries,
                key=lambda e: (e.priority, e._registration_order),
            )
        return self._sorted_cache


def _resume_with_result(
    generators: list[Generator[None, TResult | None, None]],
    result: TResult,
) -> BaseException | None:
    """Resume generators in reverse order, sending the operation result.

    If a middleware raises during post-yield, that becomes the exception
    to propagate. Subsequent (earlier-priority) middleware receive the
    exception via throw().

    Args:
        generators: Started generators to resume.
        result: The operation result to send.

    Returns:
        Exception to propagate, or None on success.
    """
    current_exception: BaseException | None = None

    for gen in reversed(generators):
        try:
            if current_exception is not None:
                gen.throw(current_exception)
            else:
                gen.send(result)
        except StopIteration:
            # Generator completed normally after receiving result
            pass
        except BaseException as mw_exc:
            if current_exception is None:
                current_exception = mw_exc
            # If there's already an exception, the original takes precedence
            # but we still need to propagate through remaining generators

    return current_exception


def _resume_with_exception(
    generators: list[Generator[None, TResult | None, None]],
    exception: BaseException,
) -> BaseException | None:
    """Resume generators in reverse order by throwing the operation exception.

    Each generator receives the exception via throw(). If a middleware
    suppresses the exception (catches and doesn't re-raise), the exception
    still propagates to earlier middleware.

    Args:
        generators: Started generators to propagate through.
        exception: The operation exception to throw.

    Returns:
        The exception to propagate (original or middleware-raised).
    """
    current_exception: BaseException | None = exception

    for gen in reversed(generators):
        try:
            gen.throw(current_exception)  # type: ignore[arg-type]
        except StopIteration:
            # Middleware absorbed the exception — but original still propagates
            pass
        except BaseException as mw_exc:
            if mw_exc is not current_exception and current_exception is None:
                # Middleware raised a new exception; original takes precedence
                # but track it for the chain
                current_exception = mw_exc

    return current_exception


def _propagate_exception(
    generators: list[Generator[None, TResult | None, None]],
    exception: BaseException,
) -> None:
    """Propagate exception through already-started generators in reverse.

    Used when a pre-yield phase raises — clean up generators that have
    already been advanced past their yield point (none should have, since
    we break immediately, but this handles the generators that were
    successfully started before the failing one).

    Args:
        generators: Generators that were successfully started.
        exception: The pre-yield exception to propagate.
    """
    for gen in reversed(generators):
        try:
            gen.throw(exception)
        except StopIteration:
            pass
        except BaseException:
            # Swallow additional exceptions from cleanup
            pass
