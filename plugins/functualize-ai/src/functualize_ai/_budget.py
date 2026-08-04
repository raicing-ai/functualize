"""Budget enforcement logic for the AI Domain SDK.

Provides budget tracking (cumulative USD spend), max tool call limits, and
timeout enforcement for AI calls. Budget state is persisted via a
StateNamespace with the ``ai:`` prefix, ensuring isolation from other domains.

The BudgetEnforcer is duck-typed with respect to its state_ns dependency:
- state_ns must have ``get(key, default=None)`` and ``set(key, value)`` methods.
This allows it to work with both a real StateNamespace and in-memory test doubles.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from functualize_ai._errors import BudgetExceededError

if TYPE_CHECKING:
    from functualize_ai._types import AILimits, TokenUsage

# Key used to track cumulative budget spend in StateBackend
BUDGET_SPENT_KEY = "budget_spent"


class BudgetEnforcer:
    """Enforces AI call budget, tool call, and timeout limits.

    The enforcer uses a state namespace (duck-typed with get/set) to persist
    cumulative spend across calls within a WorkflowScope.

    Args:
        state_ns: A state namespace (duck-typed with get/set) for persisting
            budget data. If None, budget tracking is disabled (no enforcement).
    """

    def __init__(self, state_ns: Any | None = None) -> None:
        self._state_ns = state_ns

    def get_cumulative_spend(self) -> float:
        """Return the current cumulative spend from state.

        Returns:
            The cumulative spend in USD, or 0.0 if no state is available.
        """
        if self._state_ns is None:
            return 0.0
        return float(self._state_ns.get(BUDGET_SPENT_KEY, 0.0))

    def check_budget(self, limits: AILimits | None) -> None:
        """Check if the budget limit has been reached before making a call.

        Args:
            limits: The AILimits for the current call. If None or budget_usd
                is None, no budget check is performed.

        Raises:
            BudgetExceededError: If cumulative spend >= budget_usd limit.
        """
        if limits is None or limits.budget_usd is None:
            return

        current_spend = self.get_cumulative_spend()
        if current_spend >= limits.budget_usd:
            raise BudgetExceededError(
                f"Budget exceeded: limit=${limits.budget_usd:.4f}, "
                f"spent=${current_spend:.4f}"
            )

    def record_spend(self, usage: TokenUsage) -> None:
        """Record the spend from a completed AI call.

        Adds the call's cost_usd to the cumulative budget_spent in state.

        Args:
            usage: The TokenUsage from a completed call. If cost_usd is None
                or state_ns is None, no update is performed.
        """
        if self._state_ns is None:
            return
        if usage.cost_usd is None:
            return

        current = self.get_cumulative_spend()
        self._state_ns.set(BUDGET_SPENT_KEY, current + usage.cost_usd)

    def check_tool_calls(self, tool_calls_made: int, limits: AILimits | None) -> bool:
        """Check if the max tool calls limit has been reached.

        Args:
            tool_calls_made: The number of tool calls made so far in this run.
            limits: The AILimits for the current call.

        Returns:
            True if the run should be terminated (limit reached), False otherwise.
        """
        if limits is None or limits.max_tool_calls is None:
            return False
        return tool_calls_made >= limits.max_tool_calls

    def check_timeout(self, start_time: float, limits: AILimits | None) -> bool:
        """Check if the timeout has been exceeded.

        Args:
            start_time: The wall-clock time (from time.time()) when the run started.
            limits: The AILimits for the current call.

        Returns:
            True if the run should be terminated (timeout exceeded), False otherwise.
        """
        if limits is None or limits.timeout_seconds is None:
            return False
        elapsed = time.time() - start_time
        return elapsed >= limits.timeout_seconds

    def enforce_run_limits(
        self,
        *,
        limits: AILimits | None,
        tool_calls_made: int,
        start_time: float,
    ) -> str | None:
        """Check all run-level limits and return the reason for termination.

        This is a convenience method that checks both max_tool_calls and
        timeout_seconds in a single call.

        Args:
            limits: The AILimits for the current run.
            tool_calls_made: The number of tool calls made so far.
            start_time: The wall-clock start time of the run.

        Returns:
            A string describing the reason for termination, or None if no
            limit has been reached.
        """
        if self.check_tool_calls(tool_calls_made, limits):
            return (
                f"max_tool_calls limit reached: "
                f"{tool_calls_made}/{limits.max_tool_calls}"  # type: ignore[union-attr]
            )

        if self.check_timeout(start_time, limits):
            elapsed = time.time() - start_time
            return (
                f"timeout_seconds exceeded: "
                f"{elapsed:.1f}s/{limits.timeout_seconds}s"  # type: ignore[union-attr]
            )

        return None
