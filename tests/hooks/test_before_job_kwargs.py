"""Unit tests for BEFORE_JOB kwargs passing with signature-adaptive dispatch.

Tests the behavior specified in Requirements 9.1, 9.2, 9.3 and 28.1:
- BEFORE_JOB hooks that accept `kwargs` param receive the original kwargs dict
- BEFORE_JOB hooks that don't accept `kwargs` are invoked with only rc (no TypeError)
- Each hook receives an independent shallow copy (mutations don't propagate)
- Signature introspection correctly detects kwargs parameter presence
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from functualize._events.hooks import HookEvent, HookRegistry
from functualize.job.context import RunContext


@pytest.fixture
def registry() -> HookRegistry:
    """Create a fresh HookRegistry instance."""
    return HookRegistry()


@pytest.fixture
def mock_rc() -> MagicMock:
    """Create a mock RunContext."""
    return MagicMock(spec=RunContext)


class TestBeforeJobKwargsPassing:
    """Tests for BEFORE_JOB hooks receiving original kwargs."""

    def test_hook_with_kwargs_param_receives_dict(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 9.1: hook with kwargs param receives the original kwargs."""
        received: list[dict] = []

        def hook(rc, kwargs=None):
            received.append(kwargs)

        registry.register_global(HookEvent.BEFORE_JOB, hook)
        original = {"x": 1, "y": "hello"}
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs=original)

        assert len(received) == 1
        assert received[0] == {"x": 1, "y": "hello"}

    def test_hook_with_keyword_only_kwargs_receives_value(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Hooks with keyword-only `kwargs` parameter receive the value."""
        received: list[dict] = []

        def hook(rc, *, kwargs):
            received.append(kwargs)

        registry.register_global(HookEvent.BEFORE_JOB, hook)
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"a": 42})

        assert received == [{"a": 42}]

    def test_hook_without_kwargs_param_invoked_without_it(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 9.2: hooks without kwargs param get only rc (no TypeError)."""
        called: list[bool] = []

        def legacy_hook(rc):
            called.append(True)

        registry.register_global(HookEvent.BEFORE_JOB, legacy_hook)
        # Should NOT raise TypeError
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"key": "val"})

        assert called == [True]

    def test_hook_with_var_keyword_receives_kwargs(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Hooks with **kw catch-all receive kwargs."""
        received: list[Any] = []

        def hook(rc, **kw):
            received.append(kw.get("kwargs"))

        registry.register_global(HookEvent.BEFORE_JOB, hook)
        registry.invoke(
            HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"name": "test"}
        )

        assert received == [{"name": "test"}]

    def test_empty_kwargs_dict_passed_correctly(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Empty dict is a valid kwargs value."""
        received: list[dict] = []

        def hook(rc, kwargs=None):
            received.append(kwargs)

        registry.register_global(HookEvent.BEFORE_JOB, hook)
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={})

        assert received == [{}]

    def test_mixed_hooks_with_and_without_kwargs(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Mix of hooks with and without kwargs param all invoked correctly."""
        calls: list[tuple[str, Any]] = []

        def new_hook(rc, kwargs=None):
            calls.append(("new", kwargs))

        def legacy_hook(rc):
            calls.append(("legacy", None))

        registry.register_global(HookEvent.BEFORE_JOB, new_hook)
        registry.register_global(HookEvent.BEFORE_JOB, legacy_hook)
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"foo": "bar"})

        assert calls == [("new", {"foo": "bar"}), ("legacy", None)]


class TestBeforeJobKwargsIsolation:
    """Tests for shallow copy isolation (Requirement 9.3)."""

    def test_each_hook_gets_independent_copy(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 9.3: each hook gets its own shallow copy."""
        received: list[dict] = []

        def hook1(rc, kwargs=None):
            received.append(kwargs)

        def hook2(rc, kwargs=None):
            received.append(kwargs)

        registry.register_global(HookEvent.BEFORE_JOB, hook1)
        registry.register_global(HookEvent.BEFORE_JOB, hook2)
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"x": 1})

        # Each hook should get a different dict object (independent copies)
        assert len(received) == 2
        assert received[0] is not received[1]
        # But both contain the same data
        assert received[0] == received[1] == {"x": 1}

    def test_mutation_by_one_hook_does_not_affect_next(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 9.3: mutations by one hook don't propagate to next."""
        received: list[dict] = []

        def mutating_hook(rc, kwargs=None):
            kwargs["mutated"] = True
            kwargs["x"] = 999

        def observer_hook(rc, kwargs=None):
            received.append(dict(kwargs))

        registry.register_global(HookEvent.BEFORE_JOB, mutating_hook)
        registry.register_global(HookEvent.BEFORE_JOB, observer_hook)
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"x": 1})

        # Second hook should see original values, not mutated ones
        assert received == [{"x": 1}]

    def test_original_kwargs_not_modified(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 9.3: original kwargs dict not modified by hooks."""
        original = {"x": 1, "y": 2}

        def mutating_hook(rc, kwargs=None):
            kwargs["x"] = 999
            kwargs["new_key"] = "added"

        registry.register_global(HookEvent.BEFORE_JOB, mutating_hook)
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs=original)

        # Original dict should be unchanged
        assert original == {"x": 1, "y": 2}

    def test_shallow_copy_shares_nested_objects(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Shallow copy means nested mutable objects are shared (not deep copied)."""
        inner_list = [1, 2, 3]
        received: list[Any] = []

        def hook(rc, kwargs=None):
            received.append(kwargs["data"])

        registry.register_global(HookEvent.BEFORE_JOB, hook)
        registry.invoke(
            HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"data": inner_list}
        )

        # Shallow copy: inner objects are same reference
        assert received[0] is inner_list


class TestBeforeJobKwargsExceptionHandling:
    """Tests for exception isolation with kwargs dispatch."""

    def test_exception_logged_remaining_hooks_still_invoked(
        self,
        registry: HookRegistry,
        mock_rc: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Hook exceptions are logged and remaining hooks continue."""
        called: list[str] = []

        def bad_hook(rc, kwargs=None):
            raise RuntimeError("hook exploded")

        def good_hook(rc, kwargs=None):
            called.append("good")

        registry.register_global(HookEvent.BEFORE_JOB, bad_hook)
        registry.register_global(HookEvent.BEFORE_JOB, good_hook)

        with caplog.at_level(logging.ERROR, logger="functualize._events.hooks"):
            registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"a": 1})

        assert called == ["good"]
        assert "bad_hook" in caplog.text
        assert "hook exploded" in caplog.text

    def test_legacy_hook_exception_still_allows_new_hooks(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Exception in legacy hook doesn't prevent kwargs hooks from running."""
        received: list[dict] = []

        def bad_legacy_hook(rc):
            raise ValueError("legacy fail")

        def good_new_hook(rc, kwargs=None):
            received.append(kwargs)

        registry.register_global(HookEvent.BEFORE_JOB, bad_legacy_hook)
        registry.register_global(HookEvent.BEFORE_JOB, good_new_hook)
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"x": 42})

        assert received == [{"x": 42}]


class TestBeforeJobKwargsOrdering:
    """Tests for hook invocation order with kwargs."""

    def test_global_hooks_before_job_scoped(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Global hooks invoked first, then job-scoped."""
        order: list[str] = []

        def global_hook(rc, kwargs=None):
            order.append("global")

        def job_hook(rc, kwargs=None):
            order.append("job")

        registry.register_global(HookEvent.BEFORE_JOB, global_hook)
        registry.register_for_job("my_job", HookEvent.BEFORE_JOB, job_hook)
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"a": 1})

        assert order == ["global", "job"]

    def test_job_scoped_hooks_get_independent_copies_too(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Both global and job-scoped hooks get independent copies."""
        received: list[dict] = []

        def global_hook(rc, kwargs=None):
            kwargs["source"] = "global"
            received.append(dict(kwargs))

        def job_hook(rc, kwargs=None):
            received.append(dict(kwargs))

        registry.register_global(HookEvent.BEFORE_JOB, global_hook)
        registry.register_for_job("my_job", HookEvent.BEFORE_JOB, job_hook)
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs={"x": 1})

        # Global hook mutated its copy, but job hook should see original
        assert received[0] == {"x": 1, "source": "global"}
        assert received[1] == {"x": 1}


class TestBeforeJobKwargsBackwardCompat:
    """Tests for backward compatibility when kwargs is not provided."""

    def test_no_kwargs_kwarg_calls_hook_with_rc_only(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """When kwargs= is not passed to invoke, hooks get only rc."""
        received: list[Any] = []

        def hook(rc):
            received.append(rc)

        registry.register_global(HookEvent.BEFORE_JOB, hook)
        # No kwargs= keyword argument — backward compat path
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc)

        assert received == [mock_rc]

    def test_kwargs_none_calls_hook_with_rc_only(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """When kwargs=None is passed, hooks get only rc (same as omitted)."""
        received: list[Any] = []

        def hook(rc, kwargs="sentinel"):
            received.append(kwargs)

        registry.register_global(HookEvent.BEFORE_JOB, hook)
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc, kwargs=None)

        # kwargs=None means "not provided", so plain hook(rc) path
        assert received == ["sentinel"]
