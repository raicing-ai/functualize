"""Middleware registry and execution engine for RunContext.

Provides a yield-based chain-of-responsibility pattern around job execution,
enabling plugins to wrap jobs with pre/post logic. Middleware executes in
priority order (lowest first), and resumes in reverse order after the job.

When no middleware is registered, the job function is called directly with
zero overhead (no generator objects allocated).

Supports DI parameter resolution: middleware functions can declare type-annotated
parameters (e.g., ``def timing(log: Log)``) which are resolved from the DI registry
using the same ResolutionPlan caching mechanism as job functions. Middleware with
a ``RunContext`` parameter still receives the full RunContext (backward-compatible).
Per-invocation capability instances are shared between middleware and the job.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._engine.resolution import ResolutionPlan
    from functualize._primitives.di import DIRegistry

__all__ = [
    "MiddlewareEntry",
    "MiddlewareRegistry",
    "execute_middleware_chain",
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
        self._registration_order: int = 0  # Set by registry


class MiddlewareRegistry:
    """Registry for RunContext middleware callables.

    Tracks registration order to provide stable sorting among
    middleware with equal priority values.
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
            middleware: A yield-based generator callable receiving RunContext.
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
        """Return middleware sorted by priority then registration order.

        Returns:
            A new list of MiddlewareEntry objects in execution order.
        """
        return sorted(
            self._entries,
            key=lambda e: (e.priority, e._registration_order),
        )


def execute_middleware_chain(
    rc: Any,
    middleware_entries: list[MiddlewareEntry],
    job_fn: Callable[..., Any],
    job_args: tuple[Any, ...],
    job_kwargs: dict[str, Any],
    *,
    capabilities: dict[type, Any] | None = None,
    di_registry: DIRegistry | None = None,
    resolution_plan_cache: dict[int, ResolutionPlan] | None = None,
) -> Any:
    """Execute the middleware chain around a job function.

    Builds a generator stack where each middleware yields to the next.
    If no middleware entries are provided, calls job_fn directly with
    zero allocation overhead.

    The pre-yield phase advances each generator (in order). If a middleware
    raises during pre-yield, the job is skipped and the exception propagates
    through already-started middleware post-yield phases via ``.throw()``.

    The post-yield phase resumes generators in reverse order. If the job
    raised an exception, each generator receives it via ``.throw()``.

    Supports DI parameter resolution: when ``capabilities`` and ``di_registry``
    are provided, middleware functions can declare type-annotated parameters
    which are resolved from the registry. Middleware with a ``RunContext`` param
    still receives the full RunContext (backward-compatible). The same
    per-invocation capability instances are shared between middleware and the job.

    Args:
        rc: The RunContext instance (used for backward-compatible middleware).
        middleware_entries: Sorted middleware entries (from get_sorted()).
        job_fn: The wrapped job function to invoke.
        job_args: Positional args for the job.
        job_kwargs: Keyword args for the job.
        capabilities: Per-invocation capability instances (type → instance).
            When provided, used for DI resolution in middleware parameters.
        di_registry: The DI registry for resolving non-capability types.
        resolution_plan_cache: Shared cache dict (keyed by id(function)) for
            middleware ResolutionPlans. Uses the same caching mechanism as
            job functions.

    Returns:
        The job function's return value.

    Raises:
        Any exception raised by middleware or the job function.
    """
    if not middleware_entries:
        return job_fn(*job_args, **job_kwargs)

    generators: list[Generator[None]] = []
    pre_yield_exception: BaseException | None = None

    # Pre-yield phase: start all generators in order
    for entry in middleware_entries:
        # Resolve middleware parameters via DI if infrastructure is available
        mw_kwargs = _resolve_middleware_kwargs(
            entry.middleware,
            rc=rc,
            capabilities=capabilities,
            di_registry=di_registry,
            resolution_plan_cache=resolution_plan_cache,
        )
        gen = entry.middleware(**mw_kwargs) if mw_kwargs else entry.middleware(rc)
        try:
            next(gen)
        except StopIteration:
            # Middleware didn't yield — skip it silently
            continue
        except BaseException as exc:
            # Pre-yield exception: skip remaining middleware and the job
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
        result = job_fn(*job_args, **job_kwargs)
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
    rc: Any,
    capabilities: dict[type, Any] | None,
    di_registry: DIRegistry | None,
    resolution_plan_cache: dict[int, ResolutionPlan] | None,
) -> dict[str, Any] | None:
    """Resolve DI parameters for a middleware function.

    Uses the same ResolutionPlan caching mechanism (keyed by id(function))
    as job function resolution. Per-invocation capability instances are shared
    between the middleware and the job in the same invocation.

    If DI infrastructure is not available (capabilities/di_registry/cache are None),
    returns None to signal the caller should fall back to passing rc directly.

    For backward compatibility: middleware with a RunContext parameter receives
    the full RunContext.

    Args:
        middleware_fn: The middleware callable to analyze.
        rc: The RunContext for this invocation.
        capabilities: Per-invocation capability instances (type → instance).
        di_registry: The DI registry for resolving non-capability types.
        resolution_plan_cache: Shared cache for ResolutionPlans.

    Returns:
        Dict of resolved kwargs if DI is available, or None to use direct RunContext path.
    """
    if capabilities is None or resolution_plan_cache is None:
        return None

    from functualize._engine.capabilities.runcontext import RunContext as RunContextType
    from functualize._engine.resolution import build_resolution_plan

    func_id = id(middleware_fn)
    if func_id in resolution_plan_cache:
        plan = resolution_plan_cache[func_id]
    else:
        # Build the set of registered types for plan construction
        registered_types: set[type] = set(capabilities.keys())
        if di_registry is not None:
            registered_types.update(di_registry.available_types())

        plan = build_resolution_plan(
            middleware_fn,
            registered_types=registered_types,
            runcontext_type=RunContextType,
        )
        resolution_plan_cache[func_id] = plan

    # If the plan has no resolvable params, fall back to direct RunContext path
    has_resolvable = any(b.source in ("di", "runcontext") for b in plan.params)
    if not has_resolvable:
        return None

    resolved: dict[str, Any] = {}
    for binding in plan.params:
        if binding.source == "skip":
            continue

        if binding.source == "runcontext":
            resolved[binding.name] = rc
            continue

        if binding.source == "di":
            # Per-invocation capabilities take precedence
            if binding.annotation in capabilities and binding.qualifier is None:
                resolved[binding.name] = capabilities[binding.annotation]
                continue

            # Try resolving from the DI registry
            if di_registry is not None:
                try:
                    instance = di_registry.resolve(
                        binding.annotation,
                        qualifier=binding.qualifier,
                        caps=capabilities,
                    )
                    resolved[binding.name] = instance
                except Exception:
                    if binding.is_optional:
                        resolved[binding.name] = None
                    # For non-optional missing providers in middleware,
                    # skip silently (don't crash the chain)
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
    that middleware exception becomes the propagated exception. If a prior
    exception already exists, it takes precedence.

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
            # Middleware raised during post-yield; becomes the new exception
            # only if no prior exception exists (original takes precedence).
            if current_exception is None:
                current_exception = mw_exc
    return current_exception
