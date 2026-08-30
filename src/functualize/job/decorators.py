"""Job decorator definitions for functualize.

This module consolidates all job-related decorators:
- job: Declares a job's identity and operational contract (deps/cache/guards/
  exec) via a frozen JobDeclaration on ``__functualize_job__`` (§A.3).
- surface_hint / suppress_live: per-job render-surface preferences.
- _make_hook_decorator: Factory for lifecycle hook decorators supporting bare,
  empty-parens, and parameterized invocation patterns.
- _make_global_only_decorator: Factory for decorators that only support global
  registration (no job scoping).
- _make_middleware_decorator: Factory for the middleware decorator supporting
  bare and parameterized forms.

All factories produce identity-preserving decorators — `decorated is original`
always holds.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Literal, TypeVar, overload

from functualize._types.job_declaration import (
    Deps,
    Exec,
    Fingerprint,
    Guards,
    JobDeclaration,
)

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# Job Metadata Decorator
# ---------------------------------------------------------------------------

__all__ = [
    "job",
    "suppress_live",
    "surface_hint",
]


def job(
    _func: F | None = None,
    *,
    group: str | None = None,
    extra_description: str | None = None,
    category: str | None = None,
    examples: tuple[str, ...] | list[str] = (),
    tags: tuple[str, ...] | list[str] = (),
    visibility: Literal["external", "internal"] = "external",
    config_section: str | None = None,
    deps: Deps | None = None,
    cache: Fingerprint | None = None,
    guards: Guards | None = None,
    exec: Exec | None = None,
) -> F | Callable[[F], F]:
    """Declare a job's identity and operational contract (proposal §A.3–A.6).

    Identity and description are flat kwargs (that is what ``@job`` is about);
    operational concerns are grouped, self-validating value objects
    (``Deps``/``Fingerprint``/``Guards``/``Exec``). Usable bare (``@job``) for
    plain opt-in or with any subset of kwargs::

        @job
        def build(sh: Shell): ...

        @job(
            group="infra",
            deps=Deps("lint", "test"),
            cache=Fingerprint(sources=["src/**/*.py"], generates=["dist/*.whl"]),
            exec=Exec(retry=Retry(attempts=2)),
        )
        def deploy(sh: Shell, config: DeployConfig): ...

    The frozen :class:`JobDeclaration` is stored on the function as
    ``__functualize_job__``; discovery reads it (falling back to convention).
    ``group`` overrides the module-level ``JOB_GROUP``; the addressable name
    is always derived from ``__name__`` by normalization, so there is exactly
    one spelling of a job. Identity-preserving: ``decorated is original`` always holds,
    so ``@job`` composes with other job decorators in any order.

    Raises:
        ValueError: If any field or value object violates its invariants
            (validated eagerly at decoration time).
    """
    declaration = JobDeclaration(
        group=group,
        extra_description=extra_description,
        category=category,
        examples=tuple(examples),
        tags=tuple(tags),
        visibility=visibility,
        config_section=config_section,
        deps=deps,
        cache=cache,
        guards=guards,
        exec=exec,
    )

    def apply(func: F) -> F:
        func.__functualize_job__ = declaration  # type: ignore[attr-defined]
        return func

    # Bare @job (function passed directly) vs @job(...)/@job() (returns decorator).
    if _func is not None:
        return apply(_func)
    return apply


#: Render-surface names a job may declare a preference for.
_VALID_SURFACE_HINTS = ("stdout", "panel")


def surface_hint(surface: str) -> Callable[[F], F]:
    """Declare a job's preferred render surface.

    The surface-resolution ladder consults this before the
    ``tui.default_surface`` setting and the framework default::

        @surface_hint("stdout")
        def report(log: Log) -> None:
            log("Renders on the released terminal, even from the TUI")

    A hint is a preference, not a requirement — a HARD constraint like a
    bare ``tty: TTY`` capability still wins, and a "panel" hint is ignored
    on a direct CLI run (there is no TUI to render a panel).

    Identity-preserving, like every decorator here: ``decorated is original``.

    Args:
        surface: "stdout" or "panel".

    Returns:
        A decorator attaching the declaration to the function.

    Raises:
        ValueError: If ``surface`` is not a recognized surface name.
    """
    if surface not in _VALID_SURFACE_HINTS:
        raise ValueError(
            f"surface_hint must be one of {_VALID_SURFACE_HINTS}, got {surface!r}"
        )

    def decorator(func: F) -> F:
        func.__functualize_surface_hint__ = surface  # type: ignore[attr-defined]
        return func

    return decorator


def suppress_live(*names: str) -> Callable[[F], F]:
    """Opt a job out of one or more ambient live constructs.

    Ambient constructs are the ones a plugin registered to render by default
    (a flow-viz execution tree, say). A job whose output reads better without
    one says so declaratively::

        @suppress_live("flow-viz")
        def simple_task(log: Log) -> None:
            log("No tree needed here")

    The imperative equivalent is ``live.suppress("flow-viz")`` inside the body;
    project-wide, it is ``[live] suppress`` in config.

    Identity-preserving, like every decorator here: ``decorated is original``.

    Args:
        *names: Ambient construct names to suppress. Passing none is a no-op.

    Returns:
        A decorator attaching the declaration to the function.
    """

    def decorator(func: F) -> F:
        existing = getattr(func, "__functualize_suppress_live__", ())
        func.__functualize_suppress_live__ = (  # type: ignore[attr-defined]
            tuple(existing) + names
        )
        return func

    return decorator


# ---------------------------------------------------------------------------
# Lifecycle Hook and Middleware Decorator Factories
# ---------------------------------------------------------------------------


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
