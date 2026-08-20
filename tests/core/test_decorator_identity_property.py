"""Property-based tests for decorator identity preservation (Property 9).

Tests that ALL decorator forms (bare, empty-parens, string-parameterized) return
the EXACT SAME OBJECT as the input function (`decorated is original`). Also
verifies that `__name__` is preserved across all decorator types.

Uses the decorator factory functions directly with fake registries to isolate
the property under test from FunctualizeApp internals.

**Validates: Requirements 29.1, 29.2, 29.3, 29.4, 14.3, 15.3, 16.3, 17.4, 18.3, 22.2, 23.2, 24.2, 25.2, 26.2, 27.3, 28.3, 33.2, 34.3**
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize.job.decorators import (
    _make_global_only_decorator,
    _make_hook_decorator,
    _make_middleware_decorator,
)

# --- Strategies ---

# Generate valid Python identifier function names
function_names = st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True).filter(
    lambda s: s.isidentifier()
)

# Generate non-empty job name strings for parameterized decorator usage
job_names = st.from_regex(r"[a-z][a-z0-9_]{1,20}", fullmatch=True)

# Generate priority integers for middleware
priorities = st.integers(min_value=-100, max_value=100)


# --- Helpers ---


class FakeRegistry:
    """Simple registry that tracks registered functions without side effects."""

    def __init__(self) -> None:
        self.global_hooks: list[Callable[..., Any]] = []
        self.job_hooks: dict[str, list[Callable[..., Any]]] = []
        self.middleware: list[tuple[Callable[..., Any], int]] = []

    def register_global(self, fn: Callable[..., Any]) -> None:
        self.global_hooks.append(fn)

    def register_for_job(self, job_name: str, fn: Callable[..., Any]) -> None:
        self.global_hooks.append(fn)  # Just track it

    def register_middleware(self, fn: Callable[..., Any], priority: int) -> None:
        self.middleware.append((fn, priority))


def _make_function_with_name(name: str) -> Callable[..., Any]:
    """Create a regular function with a given __name__ that accepts *args."""

    def fn(*args: Any, **kwargs: Any) -> None:
        pass

    fn.__name__ = name
    fn.__qualname__ = name
    return fn


def _make_generator_function_with_name(name: str) -> Callable[..., Any]:
    """Create a generator function with a given __name__ (for middleware)."""

    def gen_fn(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        yield

    gen_fn.__name__ = name
    gen_fn.__qualname__ = name
    return gen_fn


# --- Property 9: Decorator identity preservation ---


class TestHookDecoratorIdentityPreservation:
    """Property 9 (hook decorators): For ALL invocation forms (bare, empty-parens,
    string-parameterized), the returned function is the EXACT SAME OBJECT as the
    input function and __name__ is preserved.

    **Validates: Requirements 29.1, 29.2, 29.3, 29.4, 14.3, 15.3, 16.3, 17.4**
    """

    @given(func_name=function_names)
    def test_bare_decorator_identity(self, func_name: str) -> None:
        """Bare form (@decorator applied directly) returns same object with same __name__.

        **Validates: Requirements 29.1**
        """
        registry = FakeRegistry()
        decorator = _make_hook_decorator(
            register_global=registry.register_global,
            register_for_job=registry.register_for_job,
            event_name="test_event",
        )

        fn = _make_function_with_name(func_name)
        result = decorator(fn)

        assert result is fn, (
            f"Bare hook decorator did not preserve identity for function '{func_name}'"
        )
        assert result.__name__ == func_name, (
            f"Bare hook decorator changed __name__ from '{func_name}' to '{result.__name__}'"
        )

    @given(func_name=function_names)
    def test_empty_parens_decorator_identity(self, func_name: str) -> None:
        """Empty-parens form (@decorator()) returns same object with same __name__.

        **Validates: Requirements 29.2**
        """
        registry = FakeRegistry()
        decorator = _make_hook_decorator(
            register_global=registry.register_global,
            register_for_job=registry.register_for_job,
            event_name="test_event",
        )

        fn = _make_function_with_name(func_name)
        wrapper = decorator()
        result = wrapper(fn)

        assert result is fn, (
            f"Empty-parens hook decorator did not preserve identity for function '{func_name}'"
        )
        assert result.__name__ == func_name, (
            f"Empty-parens hook decorator changed __name__ from '{func_name}' to '{result.__name__}'"
        )

    @given(func_name=function_names, job_name=job_names)
    def test_string_parameterized_decorator_identity(
        self, func_name: str, job_name: str
    ) -> None:
        """String-parameterized form (@decorator("job")) returns same object with same __name__.

        **Validates: Requirements 29.3**
        """
        registry = FakeRegistry()
        decorator = _make_hook_decorator(
            register_global=registry.register_global,
            register_for_job=registry.register_for_job,
            event_name="test_event",
        )

        fn = _make_function_with_name(func_name)
        wrapper = decorator(job_name)
        result = wrapper(fn)

        assert result is fn, (
            f"String-parameterized hook decorator did not preserve identity "
            f"for function '{func_name}' with job '{job_name}'"
        )
        assert result.__name__ == func_name, (
            f"String-parameterized hook decorator changed __name__ from "
            f"'{func_name}' to '{result.__name__}'"
        )


class TestGlobalOnlyDecoratorIdentityPreservation:
    """Property 9 (global-only decorators): The bare decorator returns the
    EXACT SAME OBJECT as the input function and __name__ is preserved.

    **Validates: Requirements 22.2, 23.2, 24.2, 25.2, 26.2, 27.3, 33.2**
    """

    @given(func_name=function_names)
    def test_global_only_decorator_identity(self, func_name: str) -> None:
        """Global-only decorator returns same object with same __name__.

        **Validates: Requirements 22.2, 23.2, 24.2, 25.2, 26.2, 27.3, 33.2**
        """
        registry = FakeRegistry()
        decorator = _make_global_only_decorator(
            register=registry.register_global,
        )

        fn = _make_function_with_name(func_name)
        result = decorator(fn)

        assert result is fn, (
            f"Global-only decorator did not preserve identity for function '{func_name}'"
        )
        assert result.__name__ == func_name, (
            f"Global-only decorator changed __name__ from '{func_name}' to '{result.__name__}'"
        )


class TestMiddlewareDecoratorIdentityPreservation:
    """Property 9 (middleware decorator): For ALL invocation forms (bare,
    parameterized with priority), the returned function is the EXACT SAME OBJECT
    as the input generator function and __name__ is preserved.

    **Validates: Requirements 18.3, 28.3, 34.3**
    """

    @given(func_name=function_names)
    def test_bare_middleware_decorator_identity(self, func_name: str) -> None:
        """Bare middleware decorator returns same generator function with same __name__.

        **Validates: Requirements 18.3, 28.3**
        """
        registry = FakeRegistry()
        decorator = _make_middleware_decorator(
            register=registry.register_middleware,
        )

        fn = _make_generator_function_with_name(func_name)
        result = decorator(fn)

        assert result is fn, (
            f"Bare middleware decorator did not preserve identity for "
            f"generator function '{func_name}'"
        )
        assert result.__name__ == func_name, (
            f"Bare middleware decorator changed __name__ from "
            f"'{func_name}' to '{result.__name__}'"
        )

    @given(func_name=function_names, priority=priorities)
    def test_parameterized_middleware_decorator_identity(
        self, func_name: str, priority: int
    ) -> None:
        """Parameterized middleware decorator returns same generator function with same __name__.

        **Validates: Requirements 18.3, 34.3**
        """
        registry = FakeRegistry()
        decorator = _make_middleware_decorator(
            register=registry.register_middleware,
        )

        fn = _make_generator_function_with_name(func_name)
        wrapper = decorator(priority=priority)
        result = wrapper(fn)

        assert result is fn, (
            f"Parameterized middleware decorator (priority={priority}) did not "
            f"preserve identity for generator function '{func_name}'"
        )
        assert result.__name__ == func_name, (
            f"Parameterized middleware decorator (priority={priority}) changed "
            f"__name__ from '{func_name}' to '{result.__name__}'"
        )
