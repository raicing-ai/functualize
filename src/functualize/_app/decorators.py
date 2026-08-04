"""Lifecycle hook and middleware decorator factories.

These internal factory functions produce identity-preserving decorators for
lifecycle hooks and middleware registration. They are used by _app/impl.py
to create the decorator properties on FunctualizeApp.

Moved here from functualize.job.decorators to comply with the architectural
rule: internal packages (_app) must not import from public packages (job/).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar, overload

F = TypeVar("F", bound=Callable[..., Any])


def _make_hook_decorator(
    register_global: Callable[[Callable[..., Any]], None],
    register_for_job: Callable[[str, Callable[..., Any]], None],
    event_name: str,
) -> Callable[..., Any]:
    """Factory for hook decorators that support bare/@()/@ ("name") forms.

    The returned decorator handles three invocation patterns:
    1. @app.on_job_failure        → fn is the decorated function (bare)
    2. @app.on_job_failure()      → fn_or_name is None (empty parens)
    3. @app.on_job_failure("x")   → fn_or_name is a string (job-scoped)

    Algorithm:
    - If called with a callable → bare decorator, register globally, return fn
    - If called with None → return a decorator that registers globally
    - If called with a string → validate non-empty, return a decorator that
      registers for that specific job

    Returns the original function unchanged in all cases (identity-preserving).
    """

    @overload
    def decorator(fn_or_name: F) -> F: ...

    @overload
    def decorator(fn_or_name: str) -> Callable[[F], F]: ...

    @overload
    def decorator(fn_or_name: None = ...) -> Callable[[F], F]: ...

    def decorator(
        fn_or_name: str | Callable[..., Any] | None = None,
    ) -> Any:
        # Case 1: Bare decorator — @app.on_job_failure applied directly to fn
        if callable(fn_or_name):
            register_global(fn_or_name)
            return fn_or_name

        # Case 2: Empty parens — @app.on_job_failure()
        if fn_or_name is None:

            def _global_wrapper(fn: F) -> F:
                register_global(fn)
                return fn

            return _global_wrapper

        # Case 3: Job name string — @app.on_job_failure("deploy")
        if not isinstance(fn_or_name, str):
            raise TypeError(
                f"Expected a callable or job name string, "
                f"got {type(fn_or_name).__name__}"
            )
        if fn_or_name == "":
            raise ValueError(f"Job name for {event_name} decorator must be non-empty")
        job_name = fn_or_name

        def _job_wrapper(fn: F) -> F:
            register_for_job(job_name, fn)
            return fn

        return _job_wrapper

    return decorator


def _make_global_only_decorator(
    register: Callable[[Callable[..., Any]], None],
) -> Callable[[F], F]:
    """Factory for decorators that only support global registration (no job scoping).

    Supports bare usage only:
        @app.on_phase_failure
        def my_hook(rc, phase_name, status, msg): ...

    The decorated function is registered globally and returned unchanged.
    """

    def decorator(fn: F) -> F:
        register(fn)
        return fn

    return decorator


def _make_middleware_decorator(
    register: Callable[[Callable[..., Any], int], None],
) -> Callable[..., Any]:
    """Factory for the middleware decorator.

    Supports:
    1. @app.run_middleware              → bare, priority=0
    2. @app.run_middleware(priority=5)  → parameterized with priority

    Validates that the decorated function is a generator function
    (contains yield). Raises TypeError if not.
    """

    @overload
    def decorator(fn: F) -> F: ...

    @overload
    def decorator(*, priority: int) -> Callable[[F], F]: ...

    def decorator(
        fn: Callable[..., Any] | None = None,
        *,
        priority: int = 0,
    ) -> Any:
        if fn is not None:
            # Bare: @app.run_middleware
            if not inspect.isgeneratorfunction(fn):
                raise TypeError(
                    f"Middleware must be a generator function "
                    f"(must contain yield), got {fn.__name__!r}"
                )
            register(fn, priority)
            return fn

        # Parameterized: @app.run_middleware(priority=5)
        def wrapper(f: F) -> F:
            if not inspect.isgeneratorfunction(f):
                raise TypeError(
                    f"Middleware must be a generator function "
                    f"(must contain yield), got {f.__name__!r}"
                )
            register(f, priority)
            return f

        return wrapper

    return decorator
