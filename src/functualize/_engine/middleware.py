"""Middleware chain for job execution.

Provides MiddlewareEntry registration and ExecutionMiddlewareChain — a
specialized middleware chain for job execution that integrates with the
DI resolution plan for parameter injection into middleware functions.

Only imports from `_types/`, `_primitives/`, `_events/`, and stdlib.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any

from functualize._engine.resolution import ResolutionPlan, build_resolution_plan

if TYPE_CHECKING:
    from functualize._engine.context import ExecutionContext
    from functualize._primitives import DIRegistry

__all__ = [
    "ExecutionMiddlewareChain",
    "MiddlewareEntry",
]


class MiddlewareEntry:
    """A registered middleware with priority metadata.

    Attributes:
        middleware: The yield-based middleware callable.
        priority: Execution priority (lower = earlier / outermost).
    """

    __slots__ = ("middleware", "priority", "_registration_order")

    def __init__(
        self,
        middleware: Callable[..., Generator[None]],
        priority: int = 0,
    ) -> None:
        self.middleware = middleware
        self.priority = priority
        self._registration_order: int = 0


class ExecutionMiddlewareChain:
    """Middleware chain for job execution with DI-aware parameter resolution.

    Supports yield-based middleware with:
    - Priority-based ordering (lower = earlier / outermost)
    - DI parameter injection into middleware functions
    - Pre/post yield semantics around job execution
    - Exception propagation in reverse order via generator.throw()

    When no middleware is registered, job execution proceeds directly
    with zero allocation overhead.
    """

    __slots__ = ("_entries", "_counter")

    def __init__(self) -> None:
        self._entries: list[MiddlewareEntry] = []
        self._counter: int = 0

    def register(
        self,
        middleware: Callable[..., Generator[None]],
        priority: int = 0,
    ) -> None:
        """Register a middleware callable with optional priority.

        Lower priority values execute first (outermost in the chain).
        Equal priorities execute in registration order.

        Args:
            middleware: A yield-based generator callable. Receives resolved
                DI parameters or the ExecutionContext.
            priority: Execution priority (default 0).
        """
        entry = MiddlewareEntry(middleware, priority)
        entry._registration_order = self._counter
        self._counter += 1
        self._entries.append(entry)

    @property
    def has_middleware(self) -> bool:
        """Return True if any middleware is registered."""
        return len(self._entries) > 0

    def get_sorted(self) -> list[MiddlewareEntry]:
        """Return middleware sorted by priority then registration order."""
        return sorted(
            self._entries,
            key=lambda e: (e.priority, e._registration_order),
        )

    def execute(
        self,
        context: ExecutionContext,
        job_fn: Callable[..., Any],
        *,
        di_registry: DIRegistry | None = None,
        resolution_plan_cache: dict[int, ResolutionPlan] | None = None,
    ) -> Any:
        """Execute the middleware chain around a job function.

        Builds a generator stack where each middleware yields to the next.
        If no middleware entries are provided, calls job_fn directly with
        zero allocation overhead.

        Supports DI parameter resolution: when di_registry and cache are
        provided, middleware functions can declare type-annotated parameters
        which are resolved from the registry.

        Args:
            context: The ExecutionContext for this invocation.
            job_fn: The wrapped job function to invoke.
            di_registry: Optional DI registry for resolving middleware params.
            resolution_plan_cache: Shared cache for ResolutionPlans.

        Returns:
            The job function's return value.

        Raises:
            Any exception raised by middleware or the job function.
        """
        sorted_entries = self.get_sorted()

        if not sorted_entries:
            return job_fn()

        generators: list[Generator[None]] = []
        pre_yield_exception: BaseException | None = None

        # Pre-yield phase: start all generators in order
        for entry in sorted_entries:
            mw_kwargs = _resolve_middleware_kwargs(
                entry.middleware,
                context=context,
                di_registry=di_registry,
                resolution_plan_cache=resolution_plan_cache,
            )
            if mw_kwargs:
                gen = entry.middleware(**mw_kwargs)
            else:
                # Fallback: pass RunContext from capabilities (for RunContext middleware)
                from functualize._engine.capabilities.runcontext import (
                    RunContext as _RunContext,
                )

                rc = (
                    context.capabilities.get(_RunContext, context)
                    if context.capabilities
                    else context
                )
                gen = entry.middleware(rc)
            try:
                next(gen)
            except StopIteration:
                continue
            except BaseException as exc:
                pre_yield_exception = exc
                break
            generators.append(gen)

        # If pre-yield raised, propagate through already-started middleware
        if pre_yield_exception is not None:
            _resume_generators(generators, pre_yield_exception)
            raise pre_yield_exception

        # Execute the job
        result: Any = None
        job_exception: BaseException | None = None
        try:
            result = job_fn()
        except BaseException as exc:
            job_exception = exc

        # Post-yield phase: resume generators in reverse order
        final_exception = _resume_generators(generators, job_exception)

        if final_exception is not None:
            raise final_exception

        return result


def _resolve_middleware_kwargs(
    middleware_fn: Callable[..., Any],
    *,
    context: ExecutionContext,
    di_registry: DIRegistry | None,
    resolution_plan_cache: dict[int, ResolutionPlan] | None,
) -> dict[str, Any] | None:
    """Resolve DI parameters for a middleware function.

    Uses ResolutionPlan caching keyed by id(function). Per-invocation
    capability instances from the context are shared between middleware
    and the job in the same invocation.

    If DI infrastructure is not available, returns None to signal the
    caller should fall back to passing the context directly.

    Args:
        middleware_fn: The middleware callable to analyze.
        context: The ExecutionContext for this invocation.
        di_registry: The DI registry for resolving non-capability types.
        resolution_plan_cache: Shared cache for ResolutionPlans.

    Returns:
        Dict of resolved kwargs if DI is available, or None for direct path.
    """
    if resolution_plan_cache is None:
        return None

    func_id = id(middleware_fn)
    if func_id in resolution_plan_cache:
        plan = resolution_plan_cache[func_id]
    else:
        # Build the set of registered types for plan construction
        registered_types: set[type] = set(context.capabilities.keys())
        if di_registry is not None:
            registered_types.update(di_registry.available_types())

        plan = build_resolution_plan(
            middleware_fn,
            registered_types=registered_types,
            runcontext_type=None,  # Middleware doesn't get RunContext via DI here
        )
        resolution_plan_cache[func_id] = plan

    # If the plan has no resolvable params, fall back to direct context path
    has_resolvable = any(b.source == "di" for b in plan.params)
    if not has_resolvable:
        return None

    resolved: dict[str, Any] = {}
    for binding in plan.params:
        if binding.source == "skip":
            continue

        if binding.source == "di":
            # Per-invocation capabilities take precedence
            if binding.annotation in context.capabilities and binding.qualifier is None:
                resolved[binding.name] = context.capabilities[binding.annotation]
                continue

            # Try resolving from the DI registry
            if di_registry is not None:
                try:
                    instance = di_registry.resolve(
                        binding.annotation,
                        qualifier=binding.qualifier,
                        caps=context.capabilities,
                    )
                    resolved[binding.name] = instance
                except Exception:
                    if binding.is_optional:
                        resolved[binding.name] = None
                    continue
            elif binding.is_optional:
                resolved[binding.name] = None

    return resolved if resolved else None


def _resume_generators(
    generators: list[Generator[None]],
    exception: BaseException | None,
) -> BaseException | None:
    """Resume or throw into generators in reverse order.

    If a middleware raises during post-yield and no prior exception exists,
    that middleware exception becomes the propagated exception.

    Args:
        generators: The started generator objects to clean up.
        exception: If not None, thrown into each generator.

    Returns:
        The exception to propagate (if any), or None on success.
    """
    current_exception = exception
    for gen in reversed(generators):
        try:
            if current_exception is not None:
                gen.throw(
                    type(current_exception),
                    current_exception,
                    current_exception.__traceback__,
                )
            else:
                with contextlib.suppress(StopIteration):
                    gen.send(None)
        except StopIteration:
            pass
        except BaseException as mw_exc:
            if current_exception is None:
                current_exception = mw_exc
    return current_exception
