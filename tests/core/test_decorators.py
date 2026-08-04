"""Unit tests for decorator factory functions in functualize.core.decorators."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from functualize.job.decorators import (
    _make_global_only_decorator,
    _make_hook_decorator,
    _make_middleware_decorator,
)

# --- Helpers ---


class FakeRegistry:
    """Simple registry that tracks registered functions and their context."""

    def __init__(self) -> None:
        self.global_hooks: list[Callable[..., Any]] = []
        self.job_hooks: dict[str, list[Callable[..., Any]]] = {}
        self.middleware: list[tuple[Callable[..., Any], int]] = []

    def register_global(self, fn: Callable[..., Any]) -> None:
        self.global_hooks.append(fn)

    def register_for_job(self, job_name: str, fn: Callable[..., Any]) -> None:
        if job_name not in self.job_hooks:
            self.job_hooks[job_name] = []
        self.job_hooks[job_name].append(fn)

    def register_middleware(self, fn: Callable[..., Any], priority: int) -> None:
        self.middleware.append((fn, priority))


# --- _make_hook_decorator tests ---


class TestMakeHookDecorator:
    """Tests for _make_hook_decorator factory."""

    def setup_method(self) -> None:
        self.registry = FakeRegistry()
        self.decorator = _make_hook_decorator(
            register_global=self.registry.register_global,
            register_for_job=self.registry.register_for_job,
            event_name="on_job_failure",
        )

    def test_bare_decorator_registers_globally(self) -> None:
        """@decorator applied directly to function → global registration."""

        def my_hook(rc: Any) -> None:
            pass

        result = self.decorator(my_hook)
        assert result is my_hook
        assert my_hook in self.registry.global_hooks

    def test_bare_decorator_preserves_name(self) -> None:
        """Bare usage preserves __name__."""

        def my_hook(rc: Any) -> None:
            pass

        result = self.decorator(my_hook)
        assert result.__name__ == "my_hook"

    def test_empty_parens_registers_globally(self) -> None:
        """@decorator() with no args → global registration."""
        wrapper = self.decorator()

        def my_hook(rc: Any) -> None:
            pass

        result = wrapper(my_hook)
        assert result is my_hook
        assert my_hook in self.registry.global_hooks

    def test_string_arg_registers_for_job(self) -> None:
        """@decorator("job_name") → job-scoped registration."""
        wrapper = self.decorator("deploy")

        def my_hook(rc: Any) -> None:
            pass

        result = wrapper(my_hook)
        assert result is my_hook
        assert "deploy" in self.registry.job_hooks
        assert my_hook in self.registry.job_hooks["deploy"]

    def test_empty_string_raises_valueerror(self) -> None:
        """@decorator("") → ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            self.decorator("")

    def test_identity_preserved_bare(self) -> None:
        """Bare decorator returns the exact same function object."""

        def my_hook(rc: Any) -> None:
            pass

        assert self.decorator(my_hook) is my_hook

    def test_identity_preserved_empty_parens(self) -> None:
        """Empty-parens decorator returns the exact same function object."""

        def my_hook(rc: Any) -> None:
            pass

        wrapper = self.decorator()
        assert wrapper(my_hook) is my_hook

    def test_identity_preserved_string(self) -> None:
        """String-parameterized decorator returns the exact same function object."""

        def my_hook(rc: Any) -> None:
            pass

        wrapper = self.decorator("my_job")
        assert wrapper(my_hook) is my_hook

    def test_multiple_registrations_independent(self) -> None:
        """Multiple decorations register independently."""

        def hook_a(rc: Any) -> None:
            pass

        def hook_b(rc: Any) -> None:
            pass

        self.decorator(hook_a)
        self.decorator("deploy")(hook_b)

        assert hook_a in self.registry.global_hooks
        assert "deploy" in self.registry.job_hooks
        assert hook_b in self.registry.job_hooks["deploy"]
        assert hook_b not in self.registry.global_hooks


# --- _make_global_only_decorator tests ---


class TestMakeGlobalOnlyDecorator:
    """Tests for _make_global_only_decorator factory."""

    def setup_method(self) -> None:
        self.registry = FakeRegistry()
        self.decorator = _make_global_only_decorator(
            register=self.registry.register_global,
        )

    def test_registers_globally(self) -> None:
        """Decorator registers the function globally."""

        def my_hook(rc: Any, step_name: str) -> None:
            pass

        result = self.decorator(my_hook)
        assert result is my_hook
        assert my_hook in self.registry.global_hooks

    def test_preserves_identity(self) -> None:
        """Returns the exact same function object."""

        def my_hook(rc: Any) -> None:
            pass

        assert self.decorator(my_hook) is my_hook

    def test_preserves_name(self) -> None:
        """Preserves __name__ attribute."""

        def my_special_hook(rc: Any) -> None:
            pass

        result = self.decorator(my_special_hook)
        assert result.__name__ == "my_special_hook"

    def test_multiple_functions_all_registered(self) -> None:
        """Multiple decorated functions are all registered."""

        def hook_a(rc: Any) -> None:
            pass

        def hook_b(rc: Any) -> None:
            pass

        self.decorator(hook_a)
        self.decorator(hook_b)

        assert hook_a in self.registry.global_hooks
        assert hook_b in self.registry.global_hooks


# --- _make_middleware_decorator tests ---


class TestMakeMiddlewareDecorator:
    """Tests for _make_middleware_decorator factory."""

    def setup_method(self) -> None:
        self.registry = FakeRegistry()
        self.decorator = _make_middleware_decorator(
            register=self.registry.register_middleware,
        )

    def test_bare_decorator_with_generator(self) -> None:
        """@decorator on a generator function → registers with priority 0."""

        def my_middleware(rc: Any):  # type: ignore[no-untyped-def]
            yield

        result = self.decorator(my_middleware)
        assert result is my_middleware
        assert (my_middleware, 0) in self.registry.middleware

    def test_parameterized_decorator_with_priority(self) -> None:
        """@decorator(priority=5) on a generator function → registers with priority."""

        def my_middleware(rc: Any):  # type: ignore[no-untyped-def]
            yield

        wrapper = self.decorator(priority=5)
        result = wrapper(my_middleware)
        assert result is my_middleware
        assert (my_middleware, 5) in self.registry.middleware

    def test_bare_non_generator_raises_typeerror(self) -> None:
        """@decorator on a non-generator → TypeError."""

        def not_a_generator(rc: Any) -> None:
            pass

        with pytest.raises(TypeError, match="generator function"):
            self.decorator(not_a_generator)

    def test_parameterized_non_generator_raises_typeerror(self) -> None:
        """@decorator(priority=3) on a non-generator → TypeError."""

        def not_a_generator(rc: Any) -> None:
            pass

        wrapper = self.decorator(priority=3)
        with pytest.raises(TypeError, match="generator function"):
            wrapper(not_a_generator)

    def test_identity_preserved_bare(self) -> None:
        """Bare middleware decorator returns same function object."""

        def my_middleware(rc: Any):  # type: ignore[no-untyped-def]
            yield

        assert self.decorator(my_middleware) is my_middleware

    def test_identity_preserved_parameterized(self) -> None:
        """Parameterized middleware decorator returns same function object."""

        def my_middleware(rc: Any):  # type: ignore[no-untyped-def]
            yield

        wrapper = self.decorator(priority=10)
        assert wrapper(my_middleware) is my_middleware

    def test_preserves_name(self) -> None:
        """Middleware decorator preserves __name__."""

        def my_named_middleware(rc: Any):  # type: ignore[no-untyped-def]
            yield

        result = self.decorator(my_named_middleware)
        assert result.__name__ == "my_named_middleware"

    def test_default_priority_is_zero(self) -> None:
        """Without priority arg, default is 0."""

        def my_middleware(rc: Any):  # type: ignore[no-untyped-def]
            yield

        self.decorator(my_middleware)
        assert self.registry.middleware[0] == (my_middleware, 0)
