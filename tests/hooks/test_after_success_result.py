"""Unit tests for AFTER_SUCCESS result passing with signature-adaptive dispatch.

Tests the behavior specified in Requirements 1.1–1.5 and 28.1:
- Hooks that accept `result` param receive the job's return value
- Hooks that don't accept `result` are invoked without it (no TypeError)
- None is a valid result value (not omitted)
- Hook exceptions are logged at ERROR, remaining hooks still invoked
- Global hooks invoked first in registration order, then job-scoped hooks
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


class TestAfterSuccessResultPassing:
    """Tests for AFTER_SUCCESS hooks receiving job return value."""

    def test_hook_with_result_param_receives_value(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 1.1: hook receives result=return_value."""
        received: list[Any] = []

        def hook(rc, result=None):
            received.append(result)

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result=42)

        assert received == [42]

    def test_hook_with_result_param_receives_none(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 1.2: None is treated as valid result, not omitted."""
        received: list[Any] = []
        called = []

        def hook(rc, result=None):
            called.append(True)
            received.append(result)

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result=None)

        assert called == [True]
        assert received == [None]

    def test_hook_without_result_param_invoked_without_it(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 1.3: hooks that don't accept `result` are called without it."""
        called: list[bool] = []

        def legacy_hook(rc):
            called.append(True)

        registry.register_global(HookEvent.AFTER_SUCCESS, legacy_hook)
        # Should NOT raise TypeError
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result=42)

        assert called == [True]

    def test_hook_with_kwargs_catch_all_receives_result(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Hooks with **kwargs should also receive result."""
        received: list[Any] = []

        def hook(rc, **kwargs):
            received.append(kwargs.get("result"))

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result="hello")

        assert received == ["hello"]

    def test_hook_with_keyword_only_result_receives_value(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Hooks with keyword-only `result` parameter receive the value."""
        received: list[Any] = []

        def hook(rc, *, result):
            received.append(result)

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        registry.invoke(
            HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result={"key": "val"}
        )

        assert received == [{"key": "val"}]

    def test_all_hooks_receive_same_result(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 1.5: each hook receives the same result value."""
        results: list[Any] = []

        def hook1(rc, result=None):
            results.append(result)

        def hook2(rc, *, result):
            results.append(result)

        registry.register_global(HookEvent.AFTER_SUCCESS, hook1)
        registry.register_global(HookEvent.AFTER_SUCCESS, hook2)
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result=[1, 2, 3])

        assert results == [[1, 2, 3], [1, 2, 3]]

    def test_mixed_hooks_with_and_without_result(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Mix of hooks with and without result param all invoked correctly."""
        calls: list[tuple[str, Any]] = []

        def new_hook(rc, result=None):
            calls.append(("new", result))

        def legacy_hook(rc):
            calls.append(("legacy", None))

        registry.register_global(HookEvent.AFTER_SUCCESS, new_hook)
        registry.register_global(HookEvent.AFTER_SUCCESS, legacy_hook)
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result=99)

        assert calls == [("new", 99), ("legacy", None)]


class TestAfterSuccessExceptionIsolation:
    """Tests for hook exception isolation (Requirement 1.4)."""

    def test_exception_logged_at_error_level(
        self,
        registry: HookRegistry,
        mock_rc: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Requirement 1.4: hook exceptions logged at ERROR level."""

        def bad_hook(rc, result=None):
            raise RuntimeError("hook exploded")

        registry.register_global(HookEvent.AFTER_SUCCESS, bad_hook)

        with caplog.at_level(logging.ERROR, logger="functualize._events.hooks"):
            registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result=42)

        assert "bad_hook" in caplog.text
        assert "hook exploded" in caplog.text

    def test_remaining_hooks_invoked_after_exception(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 1.4: remaining hooks still invoked after one fails."""
        called: list[str] = []

        def bad_hook(rc, result=None):
            raise RuntimeError("fail")

        def good_hook(rc, result=None):
            called.append("good")

        registry.register_global(HookEvent.AFTER_SUCCESS, bad_hook)
        registry.register_global(HookEvent.AFTER_SUCCESS, good_hook)
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result=42)

        assert called == ["good"]

    def test_multiple_exceptions_all_logged_remaining_still_run(
        self,
        registry: HookRegistry,
        mock_rc: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Multiple failing hooks are all logged, and good hooks still run."""
        called: list[str] = []

        def bad1(rc, result=None):
            raise ValueError("error1")

        def bad2(rc, result=None):
            raise TypeError("error2")

        def good(rc, result=None):
            called.append("good")

        registry.register_global(HookEvent.AFTER_SUCCESS, bad1)
        registry.register_global(HookEvent.AFTER_SUCCESS, bad2)
        registry.register_global(HookEvent.AFTER_SUCCESS, good)

        with caplog.at_level(logging.ERROR, logger="functualize._events.hooks"):
            registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result="val")

        assert called == ["good"]
        assert "error1" in caplog.text
        assert "error2" in caplog.text


class TestAfterSuccessInvocationOrder:
    """Tests for hook invocation order (Requirement 1.5)."""

    def test_global_hooks_before_job_scoped(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Requirement 1.5: global hooks first, then job-scoped."""
        order: list[str] = []

        def global_hook(rc, result=None):
            order.append("global")

        def job_hook(rc, result=None):
            order.append("job")

        registry.register_global(HookEvent.AFTER_SUCCESS, global_hook)
        registry.register_for_job("my_job", HookEvent.AFTER_SUCCESS, job_hook)
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result=42)

        assert order == ["global", "job"]

    def test_registration_order_preserved_within_global(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Global hooks invoked in registration order."""
        order: list[int] = []

        for i in range(5):
            idx = i  # capture

            def hook(rc, result=None, _idx=idx):
                order.append(_idx)

            registry.register_global(HookEvent.AFTER_SUCCESS, hook)

        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result="x")
        assert order == [0, 1, 2, 3, 4]

    def test_registration_order_preserved_within_job_scoped(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Job-scoped hooks invoked in registration order."""
        order: list[int] = []

        for i in range(3):
            idx = i

            def hook(rc, result=None, _idx=idx):
                order.append(_idx)

            registry.register_for_job("my_job", HookEvent.AFTER_SUCCESS, hook)

        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result="x")
        assert order == [0, 1, 2]

    def test_full_ordering_global_then_job_scoped(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Full ordering: global1, global2, job1, job2."""
        order: list[str] = []

        registry.register_global(
            HookEvent.AFTER_SUCCESS, lambda rc, result=None: order.append("g1")
        )
        registry.register_global(
            HookEvent.AFTER_SUCCESS, lambda rc, result=None: order.append("g2")
        )
        registry.register_for_job(
            "my_job",
            HookEvent.AFTER_SUCCESS,
            lambda rc, result=None: order.append("j1"),
        )
        registry.register_for_job(
            "my_job",
            HookEvent.AFTER_SUCCESS,
            lambda rc, result=None: order.append("j2"),
        )

        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result="data")
        assert order == ["g1", "g2", "j1", "j2"]

    def test_job_scoped_hooks_not_invoked_for_other_jobs(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """Job-scoped hooks for one job don't fire for a different job."""
        called: list[str] = []

        registry.register_for_job(
            "job_a", HookEvent.AFTER_SUCCESS, lambda rc, result=None: called.append("a")
        )
        registry.register_for_job(
            "job_b", HookEvent.AFTER_SUCCESS, lambda rc, result=None: called.append("b")
        )

        registry.invoke(HookEvent.AFTER_SUCCESS, "job_a", mock_rc, result=1)
        assert called == ["a"]


class TestAfterSuccessNoResultProvided:
    """Tests for when invoke is called without result (backward compat)."""

    def test_no_result_kwarg_calls_hook_with_rc_only(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """When result is not passed, hook receives only rc."""
        received: list[Any] = []

        def hook(rc):
            received.append(rc)

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        # No result= keyword argument — backward compat path
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc)

        assert received == [mock_rc]

    def test_no_result_kwarg_hook_with_result_param_gets_rc_only(
        self, registry: HookRegistry, mock_rc: MagicMock
    ) -> None:
        """When result is not passed, even hooks with result param get only rc."""
        received: list[tuple] = []

        def hook(rc, result="sentinel"):
            received.append((rc, result))

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        # No result= keyword argument
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc)

        # Hook should receive only rc (via the plain `hook(rc)` path)
        assert received == [(mock_rc, "sentinel")]
