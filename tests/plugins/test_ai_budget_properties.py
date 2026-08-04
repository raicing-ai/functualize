"""Property-based tests for AI budget enforcement.

Tests Properties 15 and 16 from the Phase 2–5 Domain SDKs design document.

Property 15: AI budget accumulation and enforcement — For any sequence of AI
calls with cost_usd values, cumulative spend equals sum(cost_usd). Budget check
raises BudgetExceededError iff cumulative >= limit.

Property 16: AI max_tool_calls enforcement — For any max_tool_calls=N,
check_tool_calls returns True iff tool_calls_made >= N.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4**
"""

from __future__ import annotations

import pytest
from functualize_ai._budget import BUDGET_SPENT_KEY, BudgetEnforcer
from functualize_ai._errors import BudgetExceededError
from functualize_ai._types import AILimits, TokenUsage
from hypothesis import given, settings
from hypothesis import strategies as st

# ===========================================================================
# Strategies
# ===========================================================================

# Strategy for positive cost values (realistic USD costs)
cost_usd_st = st.floats(
    min_value=0.0001, max_value=100.0, allow_nan=False, allow_infinity=False
)

# Strategy for budget limits (positive floats)
budget_limit_st = st.floats(
    min_value=0.0001, max_value=1000.0, allow_nan=False, allow_infinity=False
)

# Strategy for lists of cost_usd values representing a sequence of AI calls
cost_sequence_st = st.lists(cost_usd_st, min_size=1, max_size=20)

# Strategy for max_tool_calls (positive integers)
max_tool_calls_st = st.integers(min_value=1, max_value=1000)

# Strategy for tool_calls_made (non-negative integers)
tool_calls_made_st = st.integers(min_value=0, max_value=2000)

# Strategy for token counts (non-negative integers for building TokenUsage)
token_count_st = st.integers(min_value=0, max_value=100000)


# ===========================================================================
# Test helpers
# ===========================================================================


class FakeStateNamespace:
    """Minimal state namespace for testing budget persistence."""

    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)

    def set(self, key: str, value: object) -> None:
        self._data[key] = value


# ===========================================================================
# Property 15: AI budget accumulation and enforcement
# ===========================================================================


class TestBudgetAccumulationAndEnforcementProperty:
    """Property 15: AI budget accumulation and enforcement.

    For any sequence of AI calls with cost_usd values, cumulative spend equals
    sum(cost_usd). Budget check raises BudgetExceededError iff cumulative >= limit.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @given(costs=cost_sequence_st)
    @settings(max_examples=200)
    def test_cumulative_spend_equals_sum_of_costs(self, costs: list[float]) -> None:
        """After recording N calls, cumulative spend == sum(cost_usd).

        **Validates: Requirements 7.1, 7.3**
        """
        state = FakeStateNamespace()
        enforcer = BudgetEnforcer(state_ns=state)

        for cost in costs:
            usage = TokenUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=cost,
            )
            enforcer.record_spend(usage)

        expected = sum(costs)
        actual = enforcer.get_cumulative_spend()

        # Use approximate comparison due to floating point accumulation
        assert abs(actual - expected) < 1e-9, (
            f"Cumulative spend {actual} != expected sum {expected}"
        )

    @given(costs=cost_sequence_st, limit=budget_limit_st)
    @settings(max_examples=200)
    def test_budget_exceeded_iff_cumulative_ge_limit(
        self, costs: list[float], limit: float
    ) -> None:
        """Budget check raises BudgetExceededError iff cumulative spend >= limit.

        **Validates: Requirements 7.2**
        """
        state = FakeStateNamespace()
        enforcer = BudgetEnforcer(state_ns=state)

        # Record all costs
        for cost in costs:
            usage = TokenUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=cost,
            )
            enforcer.record_spend(usage)

        cumulative = enforcer.get_cumulative_spend()
        limits = AILimits(budget_usd=limit)

        if cumulative >= limit:
            # Should raise BudgetExceededError
            with pytest.raises(BudgetExceededError):
                enforcer.check_budget(limits)
        else:
            # Should NOT raise
            enforcer.check_budget(limits)  # no exception

    @given(
        costs=cost_sequence_st,
        limit=budget_limit_st,
    )
    @settings(max_examples=200)
    def test_budget_check_before_any_spend_passes(
        self, costs: list[float], limit: float
    ) -> None:
        """Budget check passes before any spend is recorded (cumulative=0).

        **Validates: Requirements 7.2**
        """
        state = FakeStateNamespace()
        enforcer = BudgetEnforcer(state_ns=state)
        limits = AILimits(budget_usd=limit)

        # Before any spend, cumulative is 0 which is < any positive limit
        enforcer.check_budget(limits)  # should not raise

    @given(
        cost=cost_usd_st,
        prompt_tokens=token_count_st,
        completion_tokens=token_count_st,
    )
    @settings(max_examples=200)
    def test_record_spend_with_none_cost_does_not_change_cumulative(
        self, cost: float, prompt_tokens: int, completion_tokens: int
    ) -> None:
        """Recording a TokenUsage with cost_usd=None does not change cumulative.

        **Validates: Requirements 7.3**
        """
        state = FakeStateNamespace()
        enforcer = BudgetEnforcer(state_ns=state)

        # First record a real cost
        usage_with_cost = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=cost,
        )
        enforcer.record_spend(usage_with_cost)
        spend_after_first = enforcer.get_cumulative_spend()

        # Then record with None cost
        usage_no_cost = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=None,
        )
        enforcer.record_spend(usage_no_cost)
        spend_after_none = enforcer.get_cumulative_spend()

        # Cumulative should not change
        assert spend_after_none == spend_after_first

    @given(costs=cost_sequence_st, limit=budget_limit_st)
    @settings(max_examples=200)
    def test_budget_state_persisted_via_state_namespace(
        self, costs: list[float], limit: float
    ) -> None:
        """Budget state is tracked via the state namespace's budget_spent key.

        **Validates: Requirements 7.1**
        """
        state = FakeStateNamespace()
        enforcer = BudgetEnforcer(state_ns=state)

        for cost in costs:
            usage = TokenUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=cost,
            )
            enforcer.record_spend(usage)

        # The state namespace should have the budget_spent key set
        raw_value = state.get(BUDGET_SPENT_KEY, 0.0)
        assert raw_value is not None
        assert abs(float(raw_value) - sum(costs)) < 1e-9


# ===========================================================================
# Property 16: AI max_tool_calls enforcement
# ===========================================================================


class TestMaxToolCallsEnforcementProperty:
    """Property 16: AI max_tool_calls enforcement.

    For any max_tool_calls=N, check_tool_calls returns True iff tool_calls_made >= N.

    **Validates: Requirements 7.4**
    """

    @given(
        max_tool_calls=max_tool_calls_st,
        tool_calls_made=tool_calls_made_st,
    )
    @settings(max_examples=500)
    def test_check_tool_calls_true_iff_made_ge_limit(
        self, max_tool_calls: int, tool_calls_made: int
    ) -> None:
        """check_tool_calls returns True iff tool_calls_made >= max_tool_calls.

        **Validates: Requirements 7.4**
        """
        enforcer = BudgetEnforcer()
        limits = AILimits(max_tool_calls=max_tool_calls)

        result = enforcer.check_tool_calls(tool_calls_made, limits)

        if tool_calls_made >= max_tool_calls:
            assert result is True, (
                f"Expected True for tool_calls_made={tool_calls_made} >= "
                f"max_tool_calls={max_tool_calls}"
            )
        else:
            assert result is False, (
                f"Expected False for tool_calls_made={tool_calls_made} < "
                f"max_tool_calls={max_tool_calls}"
            )

    @given(tool_calls_made=tool_calls_made_st)
    @settings(max_examples=200)
    def test_no_limit_always_returns_false(self, tool_calls_made: int) -> None:
        """When max_tool_calls is None, check_tool_calls always returns False.

        **Validates: Requirements 7.4**
        """
        enforcer = BudgetEnforcer()
        limits = AILimits(max_tool_calls=None)

        result = enforcer.check_tool_calls(tool_calls_made, limits)
        assert result is False

    @given(tool_calls_made=tool_calls_made_st)
    @settings(max_examples=200)
    def test_none_limits_always_returns_false(self, tool_calls_made: int) -> None:
        """When limits is None, check_tool_calls always returns False.

        **Validates: Requirements 7.4**
        """
        enforcer = BudgetEnforcer()

        result = enforcer.check_tool_calls(tool_calls_made, None)
        assert result is False

    @given(max_tool_calls=max_tool_calls_st)
    @settings(max_examples=200)
    def test_exactly_at_limit_returns_true(self, max_tool_calls: int) -> None:
        """When tool_calls_made == max_tool_calls, check_tool_calls returns True.

        **Validates: Requirements 7.4**
        """
        enforcer = BudgetEnforcer()
        limits = AILimits(max_tool_calls=max_tool_calls)

        result = enforcer.check_tool_calls(max_tool_calls, limits)
        assert result is True

    @given(max_tool_calls=max_tool_calls_st)
    @settings(max_examples=200)
    def test_one_below_limit_returns_false(self, max_tool_calls: int) -> None:
        """When tool_calls_made == max_tool_calls - 1, check_tool_calls returns False.

        **Validates: Requirements 7.4**
        """
        enforcer = BudgetEnforcer()
        limits = AILimits(max_tool_calls=max_tool_calls)

        result = enforcer.check_tool_calls(max_tool_calls - 1, limits)
        assert result is False
