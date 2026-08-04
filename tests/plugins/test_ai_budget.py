"""Unit tests for the AI budget enforcement module."""

from __future__ import annotations

import time

import pytest
from functualize_ai._budget import BUDGET_SPENT_KEY, BudgetEnforcer
from functualize_ai._errors import BudgetExceededError
from functualize_ai._types import AILimits, TokenUsage

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeStateNamespace:
    """Minimal state namespace for testing budget persistence."""

    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)

    def set(self, key: str, value: object) -> None:
        self._data[key] = value


# ---------------------------------------------------------------------------
# Tests: Budget USD enforcement
# ---------------------------------------------------------------------------


class TestBudgetUSDEnforcement:
    """Tests for cumulative USD budget tracking and enforcement."""

    def test_check_budget_passes_when_under_limit(self) -> None:
        state = FakeStateNamespace()
        enforcer = BudgetEnforcer(state_ns=state)
        limits = AILimits(budget_usd=10.0)
        # Should not raise
        enforcer.check_budget(limits)

    def test_check_budget_raises_when_at_limit(self) -> None:
        state = FakeStateNamespace()
        state.set(BUDGET_SPENT_KEY, 10.0)
        enforcer = BudgetEnforcer(state_ns=state)
        limits = AILimits(budget_usd=10.0)
        with pytest.raises(BudgetExceededError, match="limit=\\$10.0000"):
            enforcer.check_budget(limits)

    def test_check_budget_raises_when_over_limit(self) -> None:
        state = FakeStateNamespace()
        state.set(BUDGET_SPENT_KEY, 15.5)
        enforcer = BudgetEnforcer(state_ns=state)
        limits = AILimits(budget_usd=10.0)
        with pytest.raises(BudgetExceededError, match="spent=\\$15.5000"):
            enforcer.check_budget(limits)

    def test_check_budget_no_limit_does_not_raise(self) -> None:
        state = FakeStateNamespace()
        state.set(BUDGET_SPENT_KEY, 99999.0)
        enforcer = BudgetEnforcer(state_ns=state)
        # No budget_usd set
        limits = AILimits()
        enforcer.check_budget(limits)

    def test_check_budget_none_limits_does_not_raise(self) -> None:
        state = FakeStateNamespace()
        enforcer = BudgetEnforcer(state_ns=state)
        enforcer.check_budget(None)

    def test_record_spend_accumulates(self) -> None:
        state = FakeStateNamespace()
        enforcer = BudgetEnforcer(state_ns=state)

        usage1 = TokenUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150, cost_usd=0.5
        )
        usage2 = TokenUsage(
            prompt_tokens=200, completion_tokens=100, total_tokens=300, cost_usd=1.0
        )

        enforcer.record_spend(usage1)
        assert enforcer.get_cumulative_spend() == 0.5

        enforcer.record_spend(usage2)
        assert enforcer.get_cumulative_spend() == 1.5

    def test_record_spend_no_cost_usd_does_not_update(self) -> None:
        state = FakeStateNamespace()
        enforcer = BudgetEnforcer(state_ns=state)

        usage = TokenUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150, cost_usd=None
        )
        enforcer.record_spend(usage)
        assert enforcer.get_cumulative_spend() == 0.0

    def test_record_spend_no_state_ns_is_noop(self) -> None:
        enforcer = BudgetEnforcer(state_ns=None)
        usage = TokenUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150, cost_usd=5.0
        )
        # Should not raise
        enforcer.record_spend(usage)
        assert enforcer.get_cumulative_spend() == 0.0

    def test_budget_enforcement_after_recording_spend(self) -> None:
        """Budget check fails after spend accumulates to the limit."""
        state = FakeStateNamespace()
        enforcer = BudgetEnforcer(state_ns=state)
        limits = AILimits(budget_usd=1.0)

        usage = TokenUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150, cost_usd=1.0
        )
        enforcer.record_spend(usage)

        with pytest.raises(BudgetExceededError):
            enforcer.check_budget(limits)


# ---------------------------------------------------------------------------
# Tests: Max tool calls enforcement
# ---------------------------------------------------------------------------


class TestMaxToolCallsEnforcement:
    """Tests for max_tool_calls termination."""

    def test_under_limit_returns_false(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits(max_tool_calls=5)
        assert enforcer.check_tool_calls(3, limits) is False

    def test_at_limit_returns_true(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits(max_tool_calls=5)
        assert enforcer.check_tool_calls(5, limits) is True

    def test_over_limit_returns_true(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits(max_tool_calls=5)
        assert enforcer.check_tool_calls(7, limits) is True

    def test_no_max_tool_calls_returns_false(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits()
        assert enforcer.check_tool_calls(100, limits) is False

    def test_none_limits_returns_false(self) -> None:
        enforcer = BudgetEnforcer()
        assert enforcer.check_tool_calls(100, None) is False


# ---------------------------------------------------------------------------
# Tests: Timeout enforcement
# ---------------------------------------------------------------------------


class TestTimeoutEnforcement:
    """Tests for timeout_seconds enforcement."""

    def test_under_timeout_returns_false(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits(timeout_seconds=10.0)
        start_time = time.time()  # Just started
        assert enforcer.check_timeout(start_time, limits) is False

    def test_over_timeout_returns_true(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits(timeout_seconds=5.0)
        start_time = time.time() - 10.0  # 10 seconds ago
        assert enforcer.check_timeout(start_time, limits) is True

    def test_at_timeout_returns_true(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits(timeout_seconds=5.0)
        start_time = time.time() - 5.0  # Exactly at limit
        assert enforcer.check_timeout(start_time, limits) is True

    def test_no_timeout_returns_false(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits()
        start_time = time.time() - 9999.0
        assert enforcer.check_timeout(start_time, limits) is False

    def test_none_limits_returns_false(self) -> None:
        enforcer = BudgetEnforcer()
        start_time = time.time() - 9999.0
        assert enforcer.check_timeout(start_time, None) is False


# ---------------------------------------------------------------------------
# Tests: enforce_run_limits convenience method
# ---------------------------------------------------------------------------


class TestEnforceRunLimits:
    """Tests for the combined enforce_run_limits method."""

    def test_no_limits_returns_none(self) -> None:
        enforcer = BudgetEnforcer()
        result = enforcer.enforce_run_limits(
            limits=None, tool_calls_made=100, start_time=time.time() - 9999.0
        )
        assert result is None

    def test_tool_calls_exceeded_returns_reason(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits(max_tool_calls=3)
        result = enforcer.enforce_run_limits(
            limits=limits, tool_calls_made=3, start_time=time.time()
        )
        assert result is not None
        assert "max_tool_calls" in result
        assert "3/3" in result

    def test_timeout_exceeded_returns_reason(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits(timeout_seconds=5.0)
        result = enforcer.enforce_run_limits(
            limits=limits, tool_calls_made=0, start_time=time.time() - 10.0
        )
        assert result is not None
        assert "timeout_seconds" in result

    def test_tool_calls_checked_before_timeout(self) -> None:
        """Tool calls limit is checked first; if both are exceeded, tool calls wins."""
        enforcer = BudgetEnforcer()
        limits = AILimits(max_tool_calls=2, timeout_seconds=5.0)
        result = enforcer.enforce_run_limits(
            limits=limits, tool_calls_made=5, start_time=time.time() - 10.0
        )
        assert result is not None
        assert "max_tool_calls" in result

    def test_neither_exceeded_returns_none(self) -> None:
        enforcer = BudgetEnforcer()
        limits = AILimits(max_tool_calls=10, timeout_seconds=60.0)
        result = enforcer.enforce_run_limits(
            limits=limits, tool_calls_made=2, start_time=time.time()
        )
        assert result is None
