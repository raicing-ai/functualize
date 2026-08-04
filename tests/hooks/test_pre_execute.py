"""Unit tests for PRE_EXECUTE hook pipeline (invoke_pre_execute)."""

import logging
from unittest.mock import MagicMock

import pytest

from functualize._events.hooks import HookDecision, HookEvent, HookRegistry
from functualize.job.context import RunContext


@pytest.fixture
def registry():
    """Create a fresh HookRegistry instance."""
    return HookRegistry()


@pytest.fixture
def mock_rc():
    """Create a mock RunContext."""
    return MagicMock(spec=RunContext)


class TestInvokePreExecuteBasics:
    """Tests for basic PRE_EXECUTE hook invocation behavior."""

    def test_no_hooks_returns_none(self, registry, mock_rc):
        result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})
        assert result is None

    def test_single_proceed_hook_returns_none(self, registry, mock_rc):
        registry.register_global(
            HookEvent.PRE_EXECUTE, lambda rc, kwargs: HookDecision.PROCEED()
        )
        result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})
        assert result is None

    def test_hook_returning_none_treated_as_proceed(self, registry, mock_rc):
        registry.register_global(HookEvent.PRE_EXECUTE, lambda rc, kwargs: None)
        result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})
        assert result is None

    def test_single_block_hook_returns_block_decision(self, registry, mock_rc):
        registry.register_global(
            HookEvent.PRE_EXECUTE,
            lambda rc, kwargs: HookDecision.BLOCK("not allowed"),
        )
        result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})
        assert result is not None
        assert result.is_block
        assert result.reason == "not allowed"

    def test_single_modify_hook_returns_modify_decision(self, registry, mock_rc):
        registry.register_global(
            HookEvent.PRE_EXECUTE,
            lambda rc, kwargs: HookDecision.MODIFY({"x": 42}),
        )
        result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})
        assert result is not None
        assert result.is_modify
        assert result.kwargs == {"x": 42}


class TestInvokePreExecuteChaining:
    """Tests for PRE_EXECUTE hook chaining semantics."""

    def test_modify_chains_pass_modified_kwargs_to_next(self, registry, mock_rc):
        """Each subsequent hook receives kwargs modified by previous hooks."""
        received_kwargs = []

        def hook1(rc, kwargs):
            received_kwargs.append(dict(kwargs))
            return HookDecision.MODIFY({"x": kwargs["x"] + 10})

        def hook2(rc, kwargs):
            received_kwargs.append(dict(kwargs))
            return HookDecision.MODIFY({"x": kwargs["x"] + 100})

        registry.register_global(HookEvent.PRE_EXECUTE, hook1)
        registry.register_global(HookEvent.PRE_EXECUTE, hook2)

        result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})

        assert received_kwargs[0] == {"x": 1}
        assert received_kwargs[1] == {"x": 11}
        assert result is not None
        assert result.is_modify
        assert result.kwargs == {"x": 111}

    def test_block_stops_chain_immediately(self, registry, mock_rc):
        """A BLOCK decision stops the chain — subsequent hooks are not called."""
        called = []

        def hook1(rc, kwargs):
            called.append("hook1")
            return HookDecision.BLOCK("blocked")

        def hook2(rc, kwargs):
            called.append("hook2")
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, hook1)
        registry.register_global(HookEvent.PRE_EXECUTE, hook2)

        result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})

        assert called == ["hook1"]
        assert result is not None
        assert result.is_block
        assert result.reason == "blocked"

    def test_modify_then_block_stops_at_block(self, registry, mock_rc):
        """MODIFY followed by BLOCK — BLOCK takes precedence, chain stops."""

        def hook1(rc, kwargs):
            return HookDecision.MODIFY({"x": 99})

        def hook2(rc, kwargs):
            return HookDecision.BLOCK("denied")

        def hook3(rc, kwargs):
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, hook1)
        registry.register_global(HookEvent.PRE_EXECUTE, hook2)
        registry.register_global(HookEvent.PRE_EXECUTE, hook3)

        result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})

        assert result is not None
        assert result.is_block
        assert result.reason == "denied"

    def test_multiple_proceed_returns_none(self, registry, mock_rc):
        """Multiple PROCEED hooks result in None (no changes)."""
        registry.register_global(
            HookEvent.PRE_EXECUTE, lambda rc, kwargs: HookDecision.PROCEED()
        )
        registry.register_global(HookEvent.PRE_EXECUTE, lambda rc, kwargs: None)
        registry.register_global(
            HookEvent.PRE_EXECUTE, lambda rc, kwargs: HookDecision.PROCEED()
        )

        result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})
        assert result is None

    def test_global_hooks_invoked_before_job_scoped(self, registry, mock_rc):
        """Global hooks fire first, then job-scoped hooks."""
        order = []

        def global_hook(rc, kwargs):
            order.append("global")
            return HookDecision.PROCEED()

        def job_hook(rc, kwargs):
            order.append("job")
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, global_hook)
        registry.register_for_job("my_job", HookEvent.PRE_EXECUTE, job_hook)

        registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})
        assert order == ["global", "job"]

    def test_job_scoped_hooks_not_invoked_for_other_jobs(self, registry, mock_rc):
        """Job-scoped hooks are only invoked for their specific job."""
        called = []

        def job_hook(rc, kwargs):
            called.append("job_hook")
            return HookDecision.BLOCK("nope")

        registry.register_for_job("my_job", HookEvent.PRE_EXECUTE, job_hook)

        result = registry.invoke_pre_execute("other_job", mock_rc, {"x": 1})
        assert called == []
        assert result is None


class TestInvokePreExecuteExceptionHandling:
    """Tests for PRE_EXECUTE hook exception handling."""

    def test_exception_treated_as_proceed(self, registry, mock_rc, caplog):
        """A hook that raises is treated as returning PROCEED."""
        called = []

        def bad_hook(rc, kwargs):
            raise RuntimeError("hook error")

        def good_hook(rc, kwargs):
            called.append("good")
            return HookDecision.MODIFY({"x": 42})

        registry.register_global(HookEvent.PRE_EXECUTE, bad_hook)
        registry.register_global(HookEvent.PRE_EXECUTE, good_hook)

        with caplog.at_level(logging.ERROR, logger="functualize._events.hooks"):
            result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})

        assert called == ["good"]
        assert result is not None
        assert result.is_modify
        assert result.kwargs == {"x": 42}
        assert "hook error" in caplog.text
        assert "bad_hook" in caplog.text

    def test_exception_does_not_stop_chain(self, registry, mock_rc, caplog):
        """Multiple exceptions don't prevent subsequent hooks from running."""
        called = []

        def bad1(rc, kwargs):
            raise ValueError("error1")

        def bad2(rc, kwargs):
            raise TypeError("error2")

        def good(rc, kwargs):
            called.append("good")
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, bad1)
        registry.register_global(HookEvent.PRE_EXECUTE, bad2)
        registry.register_global(HookEvent.PRE_EXECUTE, good)

        with caplog.at_level(logging.ERROR, logger="functualize._events.hooks"):
            result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})

        assert called == ["good"]
        assert "error1" in caplog.text
        assert "error2" in caplog.text
        assert result is None

    def test_exception_between_modify_hooks_preserves_modifications(
        self, registry, mock_rc, caplog
    ):
        """An exception between MODIFY hooks doesn't lose previous modifications."""
        received_kwargs = []

        def modify1(rc, kwargs):
            return HookDecision.MODIFY({"x": 10})

        def bad_hook(rc, kwargs):
            received_kwargs.append(dict(kwargs))
            raise RuntimeError("oops")

        def modify2(rc, kwargs):
            received_kwargs.append(dict(kwargs))
            return HookDecision.MODIFY({"x": kwargs["x"] + 5})

        registry.register_global(HookEvent.PRE_EXECUTE, modify1)
        registry.register_global(HookEvent.PRE_EXECUTE, bad_hook)
        registry.register_global(HookEvent.PRE_EXECUTE, modify2)

        with caplog.at_level(logging.ERROR, logger="functualize._events.hooks"):
            result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})

        # bad_hook received modified kwargs from modify1
        assert received_kwargs[0] == {"x": 10}
        # modify2 also received modified kwargs from modify1 (bad_hook was treated as PROCEED)
        assert received_kwargs[1] == {"x": 10}
        # Final result is the modification from modify2
        assert result is not None
        assert result.is_modify
        assert result.kwargs == {"x": 15}


class TestInvokePreExecuteKwargsCopying:
    """Tests that kwargs are copied before passing to hooks."""

    def test_original_kwargs_not_mutated(self, registry, mock_rc):
        """The original kwargs dict passed to invoke_pre_execute is not mutated."""
        original = {"x": 1, "y": 2}
        original_copy = dict(original)

        def mutating_hook(rc, kwargs):
            kwargs["x"] = 999
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, mutating_hook)
        registry.invoke_pre_execute("my_job", mock_rc, original)

        assert original == original_copy

    def test_each_hook_receives_copy(self, registry, mock_rc):
        """Each hook receives its own copy — mutations by one don't affect the next
        (unless MODIFY is returned)."""
        received = []

        def hook1(rc, kwargs):
            kwargs["mutated_by_hook1"] = True
            received.append(dict(kwargs))
            return HookDecision.PROCEED()

        def hook2(rc, kwargs):
            received.append(dict(kwargs))
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, hook1)
        registry.register_global(HookEvent.PRE_EXECUTE, hook2)

        registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})

        # hook1 added a key via mutation, but since it returned PROCEED (not MODIFY),
        # the mutation doesn't propagate to hook2
        assert "mutated_by_hook1" in received[0]
        assert "mutated_by_hook1" not in received[1]

    def test_hooks_receive_rc(self, registry, mock_rc):
        """Each hook receives the RunContext instance."""
        received_rcs = []

        def hook(rc, kwargs):
            received_rcs.append(rc)
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, hook)
        registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})

        assert received_rcs == [mock_rc]
