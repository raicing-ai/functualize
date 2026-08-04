"""Tests for hook capabilities access (Requirement 22).

Verifies that PRE_EXECUTE and POST_EXECUTE (AFTER_SUCCESS) hooks can receive
a `capabilities: dict[type, Any]` keyword argument containing the resolved
per-invocation capabilities, and that hooks without the parameter are unaffected.

Requirements: 22.1, 22.2, 22.3, 22.4
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from functualize._events.hooks import HookDecision, HookEvent, HookRegistry
from functualize.job.capabilities import Log, Perf, State
from functualize.job.context import RunContext


@pytest.fixture
def registry():
    """Create a fresh HookRegistry instance."""
    return HookRegistry()


@pytest.fixture
def mock_rc():
    """Create a mock RunContext."""
    return MagicMock(spec=RunContext)


@pytest.fixture
def sample_capabilities():
    """Create sample capabilities dict keyed by type."""
    return {
        Log: Log(),
        State: State(),
        Perf: Perf(),
    }


class TestPreExecuteCapabilitiesAccess:
    """Tests for PRE_EXECUTE hooks receiving capabilities (Requirement 22.1)."""

    def test_hook_with_capabilities_param_receives_dict(
        self, registry, mock_rc, sample_capabilities
    ):
        """A PRE_EXECUTE hook that declares `capabilities` receives the dict."""
        received_caps: list[dict[type, Any]] = []

        def hook_with_caps(rc, kwargs, *, capabilities=None):
            received_caps.append(capabilities)
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, hook_with_caps)
        registry.invoke_pre_execute(
            "my_job", mock_rc, {"x": 1}, capabilities=sample_capabilities
        )

        assert len(received_caps) == 1
        assert received_caps[0] is sample_capabilities

    def test_hook_without_capabilities_param_not_affected(
        self, registry, mock_rc, sample_capabilities
    ):
        """A PRE_EXECUTE hook without `capabilities` param works normally (22.3)."""
        called = []

        def legacy_hook(rc, kwargs):
            called.append(True)
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, legacy_hook)
        # Should not raise TypeError
        result = registry.invoke_pre_execute(
            "my_job", mock_rc, {"x": 1}, capabilities=sample_capabilities
        )

        assert called == [True]
        assert result is None

    def test_mixed_hooks_some_with_capabilities_some_without(
        self, registry, mock_rc, sample_capabilities
    ):
        """Hooks with and without capabilities param coexist (22.3, 22.4)."""
        legacy_called = []
        new_received_caps: list[Any] = []

        def legacy_hook(rc, kwargs):
            legacy_called.append(True)
            return HookDecision.PROCEED()

        def new_hook(rc, kwargs, *, capabilities=None):
            new_received_caps.append(capabilities)
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, legacy_hook)
        registry.register_global(HookEvent.PRE_EXECUTE, new_hook)

        registry.invoke_pre_execute(
            "my_job", mock_rc, {"x": 1}, capabilities=sample_capabilities
        )

        assert legacy_called == [True]
        assert new_received_caps == [sample_capabilities]

    def test_capabilities_dict_keyed_by_type(
        self, registry, mock_rc, sample_capabilities
    ):
        """Capabilities dict is keyed by type (22.4)."""
        received_caps: list[dict[type, Any]] = []

        def hook(rc, kwargs, *, capabilities=None):
            received_caps.append(capabilities)
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, hook)
        registry.invoke_pre_execute(
            "my_job", mock_rc, {"x": 1}, capabilities=sample_capabilities
        )

        caps = received_caps[0]
        assert Log in caps
        assert State in caps
        assert Perf in caps
        assert isinstance(caps[Log], Log)
        assert isinstance(caps[State], State)

    def test_capabilities_same_instances_as_job_would_receive(
        self, registry, mock_rc, sample_capabilities
    ):
        """Hook receives the same instances that would be injected into the job (22.2)."""
        received_caps: list[dict[type, Any]] = []

        def hook(rc, kwargs, *, capabilities=None):
            received_caps.append(capabilities)
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, hook)
        registry.invoke_pre_execute(
            "my_job", mock_rc, {"x": 1}, capabilities=sample_capabilities
        )

        # The capabilities dict should be the exact same dict passed in
        assert received_caps[0] is sample_capabilities
        # And the instances inside should be the same objects
        assert received_caps[0][Log] is sample_capabilities[Log]

    def test_hook_with_var_kwargs_receives_capabilities(
        self, registry, mock_rc, sample_capabilities
    ):
        """A hook with **kwargs also receives capabilities."""
        received: list[Any] = []

        def hook_with_var_kwargs(rc, kwargs, **extra):
            received.append(extra.get("capabilities"))
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, hook_with_var_kwargs)
        registry.invoke_pre_execute(
            "my_job", mock_rc, {"x": 1}, capabilities=sample_capabilities
        )

        assert received[0] is sample_capabilities

    def test_no_capabilities_passed_when_none(self, registry, mock_rc):
        """When no capabilities are available, hook is called without it."""
        called = []

        def hook_with_caps(rc, kwargs, *, capabilities=None):
            called.append(capabilities)
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, hook_with_caps)
        registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})

        # capabilities defaults to None since no capabilities were passed
        # (empty dict doesn't trigger passing)
        assert called == [None]

    def test_block_decision_still_works_with_capabilities(
        self, registry, mock_rc, sample_capabilities
    ):
        """BLOCK decision works correctly when capabilities are passed."""
        received_caps: list[Any] = []

        def blocking_hook(rc, kwargs, *, capabilities=None):
            received_caps.append(capabilities)
            return HookDecision.BLOCK("blocked with caps")

        registry.register_global(HookEvent.PRE_EXECUTE, blocking_hook)
        result = registry.invoke_pre_execute(
            "my_job", mock_rc, {"x": 1}, capabilities=sample_capabilities
        )

        assert result is not None
        assert result.is_block
        assert received_caps[0] is sample_capabilities


class TestAfterSuccessCapabilitiesAccess:
    """Tests for AFTER_SUCCESS (POST_EXECUTE) hooks receiving capabilities (22.2)."""

    def test_hook_with_capabilities_param_receives_dict(
        self, registry, mock_rc, sample_capabilities
    ):
        """An AFTER_SUCCESS hook that declares `capabilities` receives the dict."""
        received_caps: list[dict[type, Any]] = []

        def hook_with_caps(rc, *, result=None, capabilities=None):
            received_caps.append(capabilities)

        registry.register_global(HookEvent.AFTER_SUCCESS, hook_with_caps)
        registry.invoke(
            HookEvent.AFTER_SUCCESS,
            "my_job",
            mock_rc,
            result="success_value",
            capabilities=sample_capabilities,
        )

        assert len(received_caps) == 1
        assert received_caps[0] is sample_capabilities

    def test_hook_without_capabilities_param_not_affected(
        self, registry, mock_rc, sample_capabilities
    ):
        """An AFTER_SUCCESS hook without `capabilities` param works normally."""
        called = []

        def legacy_hook(rc):
            called.append(True)

        registry.register_global(HookEvent.AFTER_SUCCESS, legacy_hook)
        # Should not raise TypeError
        registry.invoke(
            HookEvent.AFTER_SUCCESS,
            "my_job",
            mock_rc,
            result="value",
            capabilities=sample_capabilities,
        )

        assert called == [True]

    def test_hook_with_result_and_capabilities(
        self, registry, mock_rc, sample_capabilities
    ):
        """An AFTER_SUCCESS hook can receive both result and capabilities."""
        received: list[tuple[Any, Any]] = []

        def hook(rc, *, result=None, capabilities=None):
            received.append((result, capabilities))

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        registry.invoke(
            HookEvent.AFTER_SUCCESS,
            "my_job",
            mock_rc,
            result=42,
            capabilities=sample_capabilities,
        )

        assert received[0][0] == 42
        assert received[0][1] is sample_capabilities

    def test_hook_with_result_only_no_capabilities(
        self, registry, mock_rc, sample_capabilities
    ):
        """Hook accepting result but not capabilities still works."""
        received_results: list[Any] = []

        def hook(rc, *, result=None):
            received_results.append(result)

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        registry.invoke(
            HookEvent.AFTER_SUCCESS,
            "my_job",
            mock_rc,
            result="hello",
            capabilities=sample_capabilities,
        )

        assert received_results == ["hello"]

    def test_hook_with_capabilities_only_no_result(
        self, registry, mock_rc, sample_capabilities
    ):
        """Hook accepting capabilities but not result still works."""
        received_caps: list[Any] = []

        def hook(rc, *, capabilities=None):
            received_caps.append(capabilities)

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        registry.invoke(
            HookEvent.AFTER_SUCCESS,
            "my_job",
            mock_rc,
            result="value",
            capabilities=sample_capabilities,
        )

        assert received_caps[0] is sample_capabilities

    def test_mixed_hooks_some_with_capabilities_some_without(
        self, registry, mock_rc, sample_capabilities
    ):
        """Different hook signatures coexist for AFTER_SUCCESS."""
        legacy_calls: list[bool] = []
        result_calls: list[Any] = []
        caps_calls: list[Any] = []

        def legacy_hook(rc):
            legacy_calls.append(True)

        def result_hook(rc, *, result=None):
            result_calls.append(result)

        def full_hook(rc, *, result=None, capabilities=None):
            caps_calls.append(capabilities)

        registry.register_global(HookEvent.AFTER_SUCCESS, legacy_hook)
        registry.register_global(HookEvent.AFTER_SUCCESS, result_hook)
        registry.register_global(HookEvent.AFTER_SUCCESS, full_hook)

        registry.invoke(
            HookEvent.AFTER_SUCCESS,
            "my_job",
            mock_rc,
            result="ok",
            capabilities=sample_capabilities,
        )

        assert legacy_calls == [True]
        assert result_calls == ["ok"]
        assert caps_calls == [sample_capabilities]

    def test_capabilities_dict_keyed_by_type(
        self, registry, mock_rc, sample_capabilities
    ):
        """Capabilities dict is keyed by type (22.4)."""
        received_caps: list[dict[type, Any]] = []

        def hook(rc, *, capabilities=None):
            received_caps.append(capabilities)

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        registry.invoke(
            HookEvent.AFTER_SUCCESS,
            "my_job",
            mock_rc,
            result=None,
            capabilities=sample_capabilities,
        )

        caps = received_caps[0]
        assert Log in caps
        assert isinstance(caps[Log], Log)


class TestBackwardCompatibility:
    """Tests ensuring existing hooks are completely unaffected (22.3)."""

    def test_pre_execute_legacy_lambda_unaffected(
        self, registry, mock_rc, sample_capabilities
    ):
        """Lambdas as PRE_EXECUTE hooks still work."""
        registry.register_global(
            HookEvent.PRE_EXECUTE, lambda rc, kwargs: HookDecision.PROCEED()
        )
        # Should not raise
        result = registry.invoke_pre_execute(
            "my_job", mock_rc, {"x": 1}, capabilities=sample_capabilities
        )
        assert result is None

    def test_after_success_legacy_lambda_unaffected(
        self, registry, mock_rc, sample_capabilities
    ):
        """Lambdas as AFTER_SUCCESS hooks still work."""
        called = []
        registry.register_global(
            HookEvent.AFTER_SUCCESS, lambda rc: called.append(True)
        )
        # Should not raise
        registry.invoke(
            HookEvent.AFTER_SUCCESS,
            "my_job",
            mock_rc,
            result="value",
            capabilities=sample_capabilities,
        )
        assert called == [True]

    def test_no_capabilities_invocation_backward_compatible(self, registry, mock_rc):
        """Calling invoke_pre_execute without capabilities still works."""
        called = []

        def hook(rc, kwargs):
            called.append(True)
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, hook)
        # No capabilities kwarg passed — backward compatible
        result = registry.invoke_pre_execute("my_job", mock_rc, {"x": 1})
        assert called == [True]
        assert result is None

    def test_invoke_without_capabilities_backward_compatible(self, registry, mock_rc):
        """Calling invoke for AFTER_SUCCESS without capabilities still works."""
        called = []

        def hook(rc, *, result=None):
            called.append(result)

        registry.register_global(HookEvent.AFTER_SUCCESS, hook)
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc, result="val")
        assert called == ["val"]
