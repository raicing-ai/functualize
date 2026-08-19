"""Property-based tests for Gate Resolution System.

Tests Properties 16–19 from the Phase 1 design document.

**Validates: Requirements 1.10, 7.6, 7.8, 7.9, 7.10**
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from functualize._gate import GateContext, GateRegistry
from functualize._types.errors import GateResolutionError

# --- Hypothesis Strategies ---

# Strategy for generating field values (simple JSON-compatible types)
field_values = st.one_of(
    st.text(min_size=1, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
)

# Strategy for field names (valid Python identifiers)
field_names = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True)

# Strategy for the number of strategies in an ordered fallback list
strategy_count = st.integers(min_value=1, max_value=5)

# Strategy for the index of the first succeeding strategy
# (must be generated relative to the total count)


# --- Test helpers ---


class DynamicModel(BaseModel):
    """A dynamic model used for testing. Has two required string fields."""

    alpha: str
    beta: str


class ThreeFieldModel(BaseModel):
    """Model with three required fields for richer testing."""

    x: str
    y: int
    z: bool


class FullyDefaultedModel(BaseModel):
    """Model with all defaults — always fully resolvable from config chain."""

    name: str = "default_name"
    count: int = 0
    active: bool = True


class _SuccessResolver:
    """Resolver that always succeeds by returning a model with given fill values."""

    def __init__(self, fill_values: dict[str, Any]) -> None:
        self.fill_values = fill_values
        self.call_count = 0

    def resolve(self, ctx: GateContext) -> BaseModel:
        self.call_count += 1
        fields = {**ctx.resolved_fields, **self.fill_values}
        return ctx.model_class(**fields)


class _FailingResolver:
    """Resolver that always raises an exception."""

    def __init__(self, message: str = "strategy failed") -> None:
        self.message = message
        self.call_count = 0

    def resolve(self, ctx: GateContext) -> BaseModel:
        self.call_count += 1
        raise RuntimeError(self.message)


class _TrackingResolver:
    """Resolver that tracks whether it was called."""

    def __init__(self, fill_values: dict[str, Any] | None = None) -> None:
        self.fill_values = fill_values or {}
        self.call_count = 0

    def resolve(self, ctx: GateContext) -> BaseModel:
        self.call_count += 1
        fields = {**ctx.resolved_fields, **self.fill_values}
        return ctx.model_class(**fields)


# --- Property 16: Force-gate always dispatches ---
# For any fully-resolvable BaseModel (all required fields have values from
# the config chain), when force_gate=True is set, the gate resolution system
# SHALL dispatch to the configured gate strategy regardless of resolution status.
# **Validates: Requirements 1.10, 7.8**


class TestForceGateAlwaysDispatches:
    """Property 16: Force-gate always dispatches."""

    @given(
        name=st.text(
            min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))
        ),
        count=st.integers(min_value=0, max_value=10000),
        active=st.booleans(),
    )
    def test_force_gate_dispatches_even_when_fully_resolved(
        self, name: str, count: int, active: bool
    ) -> None:
        """force_gate=True dispatches to strategy even when all fields are resolved.

        **Validates: Requirements 1.10, 7.8**
        """
        registry = GateRegistry()
        tracker = _TrackingResolver(
            fill_values={"name": name, "count": count, "active": active}
        )
        registry.register_strategy("resolve", tracker)

        # All fields are fully resolved via resolved_fields
        result = registry.resolve_gate(
            FullyDefaultedModel,
            force_gate=True,
            resolved_fields={"name": name, "count": count, "active": active},
        )

        # Strategy MUST have been called (dispatched)
        assert tracker.call_count == 1
        assert isinstance(result, FullyDefaultedModel)

    @given(
        name=st.text(
            min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))
        ),
        count=st.integers(min_value=0, max_value=10000),
    )
    def test_force_gate_dispatches_with_defaults_fully_resolved(
        self, name: str, count: int
    ) -> None:
        """force_gate=True dispatches even when model defaults make it fully resolved.

        **Validates: Requirements 1.10, 7.8**
        """
        registry = GateRegistry()
        tracker = _TrackingResolver(
            fill_values={"name": name, "count": count, "active": True}
        )
        registry.register_strategy("resolve", tracker)

        # Model has all defaults, so it's fully resolvable without explicit fields
        result = registry.resolve_gate(
            FullyDefaultedModel,
            force_gate=True,
        )

        # Strategy MUST have been called even though model has all defaults
        assert tracker.call_count == 1
        assert isinstance(result, FullyDefaultedModel)

    @given(
        strategy_name=st.from_regex(r"[a-z]{1,10}", fullmatch=True),
    )
    def test_force_gate_context_reflects_forced_flag(self, strategy_name: str) -> None:
        """When force_gate=True, the GateContext passed to resolver has force_gate=True.

        **Validates: Requirements 1.10, 7.8**
        """
        registry = GateRegistry()
        captured_ctx: list[GateContext] = []

        class _CapturingResolver:
            def resolve(self, ctx: GateContext) -> BaseModel:
                captured_ctx.append(ctx)
                return ctx.model_class(**ctx.resolved_fields)

        registry.register_strategy(strategy_name, _CapturingResolver())

        registry.resolve_gate(
            FullyDefaultedModel,
            force_gate=True,
            resolved_fields={"name": "test", "count": 1, "active": True},
            gate_strategy=strategy_name,
        )

        assert len(captured_ctx) == 1
        assert captured_ctx[0].force_gate is True


# --- Property 17: Gate skip when fully resolved ---
# For any BaseModel where all required fields are resolved from the config
# chain and force_gate=False, the gate resolution system SHALL use the resolved
# model directly without dispatching to any strategy.
# **Validates: Requirements 7.6**


class TestGateSkipWhenFullyResolved:
    """Property 17: Gate skip when fully resolved."""

    @given(
        name=st.text(
            min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))
        ),
        count=st.integers(min_value=0, max_value=10000),
        active=st.booleans(),
    )
    def test_fully_resolved_with_force_false_skips_dispatch(
        self, name: str, count: int, active: bool
    ) -> None:
        """Fully resolved model + force_gate=False skips strategy dispatch.

        **Validates: Requirements 7.6**
        """
        registry = GateRegistry()
        tracker = _TrackingResolver(
            fill_values={"name": name, "count": count, "active": active}
        )
        registry.register_strategy("resolve", tracker)

        result = registry.resolve_gate(
            FullyDefaultedModel,
            force_gate=False,
            resolved_fields={"name": name, "count": count, "active": active},
        )

        # Strategy must NOT have been called
        assert tracker.call_count == 0
        # The resolved model is returned directly
        assert isinstance(result, FullyDefaultedModel)
        assert result.name == name
        assert result.count == count
        assert result.active == active

    @given(
        name=st.text(
            min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))
        ),
        count=st.integers(min_value=0, max_value=10000),
    )
    def test_model_with_defaults_fully_resolved_skips_dispatch(
        self, name: str, count: int
    ) -> None:
        """Model where all required fields have defaults is fully resolved.

        **Validates: Requirements 7.6**
        """
        registry = GateRegistry()
        tracker = _TrackingResolver(
            fill_values={"name": "should_not_appear", "count": -1, "active": False}
        )
        registry.register_strategy("resolve", tracker)

        # FullyDefaultedModel has all defaults, so no resolved_fields needed
        result = registry.resolve_gate(
            FullyDefaultedModel,
            force_gate=False,
        )

        # Strategy must NOT have been called
        assert tracker.call_count == 0
        # Should use defaults
        assert isinstance(result, FullyDefaultedModel)
        assert result.name == "default_name"
        assert result.count == 0
        assert result.active is True

    @given(
        name=st.text(
            min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))
        ),
        count=st.integers(min_value=0, max_value=10000),
        active=st.booleans(),
    )
    def test_returned_model_matches_resolved_fields_exactly(
        self, name: str, count: int, active: bool
    ) -> None:
        """The returned model's field values match the resolved field values.

        **Validates: Requirements 7.6**
        """
        registry = GateRegistry()
        tracker = _TrackingResolver()
        registry.register_strategy("resolve", tracker)

        result = registry.resolve_gate(
            FullyDefaultedModel,
            force_gate=False,
            resolved_fields={"name": name, "count": count, "active": active},
        )

        assert result.name == name
        assert result.count == count
        assert result.active == active
        assert tracker.call_count == 0


# --- Property 18: Ordered strategy fallback ---
# For any ordered list of N gate strategies where the first M raise exceptions
# and strategy M+1 returns a valid model, the gate resolution system SHALL
# return the model from strategy M+1 and SHALL have called strategies 1
# through M+1 in sequence.
# **Validates: Requirements 7.9**


class TestOrderedStrategyFallback:
    """Property 18: Ordered strategy fallback."""

    @given(
        total_strategies=st.integers(min_value=2, max_value=5),
        data=st.data(),
    )
    def test_first_success_wins_after_failures(
        self, total_strategies: int, data: st.DataObject
    ) -> None:
        """Tries strategies in order, returns first success.

        **Validates: Requirements 7.9**
        """
        # Pick which strategy will succeed (0-indexed)
        success_idx = data.draw(
            st.integers(min_value=0, max_value=total_strategies - 1)
        )

        registry = GateRegistry()
        resolvers: list[_FailingResolver | _SuccessResolver] = []
        strategy_names: list[str] = []

        for i in range(total_strategies):
            name = f"strat_{i}"
            strategy_names.append(name)
            if i < success_idx:
                resolver = _FailingResolver(message=f"strat_{i} failed")
                resolvers.append(resolver)
                registry.register_strategy(name, resolver)
            elif i == success_idx:
                resolver = _SuccessResolver(
                    fill_values={"alpha": f"from_{i}", "beta": f"val_{i}"}
                )
                resolvers.append(resolver)
                registry.register_strategy(name, resolver)
            else:
                resolver = _SuccessResolver(
                    fill_values={"alpha": f"from_{i}", "beta": f"val_{i}"}
                )
                resolvers.append(resolver)
                registry.register_strategy(name, resolver)

        result = registry.resolve_gate(
            DynamicModel,
            gate_strategy=strategy_names,
        )

        # Result should come from the successful strategy
        assert isinstance(result, DynamicModel)
        assert result.alpha == f"from_{success_idx}"
        assert result.beta == f"val_{success_idx}"

        # Strategies before and including the successful one should be called
        for i in range(success_idx + 1):
            assert resolvers[i].call_count == 1

        # Strategies after the successful one should NOT be called
        for i in range(success_idx + 1, total_strategies):
            assert resolvers[i].call_count == 0

    @given(
        num_failing=st.integers(min_value=1, max_value=4),
    )
    def test_strategies_called_in_order(self, num_failing: int) -> None:
        """Strategies are tried in the exact order they appear in the list.

        **Validates: Requirements 7.9**
        """
        registry = GateRegistry()
        call_order: list[str] = []

        class _OrderTracker:
            def __init__(self, name: str, should_fail: bool) -> None:
                self.name = name
                self.should_fail = should_fail

            def resolve(self, ctx: GateContext) -> BaseModel:
                call_order.append(self.name)
                if self.should_fail:
                    raise RuntimeError(f"{self.name} fails")
                return ctx.model_class(alpha="ok", beta="ok")

        strategy_names: list[str] = []
        for i in range(num_failing):
            name = f"fail_{i}"
            strategy_names.append(name)
            registry.register_strategy(name, _OrderTracker(name, should_fail=True))

        # Add the final success strategy
        success_name = "success"
        strategy_names.append(success_name)
        registry.register_strategy(
            success_name, _OrderTracker(success_name, should_fail=False)
        )

        registry.resolve_gate(
            DynamicModel,
            gate_strategy=strategy_names,
        )

        # Verify call order is exactly as specified
        assert call_order == strategy_names


# --- Property 19: All strategies failing raises error ---
# For any ordered list of strategies that all raise exceptions, the gate
# resolution system SHALL raise a GateResolutionError containing the number
# of strategies attempted and the last exception message.
# **Validates: Requirements 7.10**


class TestAllStrategiesFailingRaisesError:
    """Property 19: All strategies failing raises error."""

    @given(
        num_strategies=st.integers(min_value=1, max_value=5),
        gate_name=st.text(
            min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))
        ),
    )
    def test_all_fail_raises_gate_resolution_error(
        self, num_strategies: int, gate_name: str
    ) -> None:
        """All strategies failing raises GateResolutionError.

        **Validates: Requirements 7.10**
        """
        registry = GateRegistry()
        strategy_names: list[str] = []

        for i in range(num_strategies):
            name = f"failing_{i}"
            strategy_names.append(name)
            registry.register_strategy(
                name, _FailingResolver(message=f"error from {name}")
            )

        with pytest.raises(GateResolutionError) as exc_info:
            registry.resolve_gate(
                DynamicModel,
                gate_strategy=strategy_names,
                gate_name=gate_name,
            )

        error = exc_info.value
        assert error.strategies_attempted == num_strategies
        assert error.gate_name == gate_name

    @given(
        num_strategies=st.integers(min_value=1, max_value=5),
        last_error_msg=st.text(
            min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N", "Z"))
        ),
    )
    def test_error_contains_last_exception_message(
        self, num_strategies: int, last_error_msg: str
    ) -> None:
        """GateResolutionError contains the last strategy's exception message.

        **Validates: Requirements 7.10**
        """
        registry = GateRegistry()
        strategy_names: list[str] = []

        for i in range(num_strategies):
            name = f"fail_{i}"
            strategy_names.append(name)
            # The last strategy's error message is what we check
            if i == num_strategies - 1:
                registry.register_strategy(
                    name, _FailingResolver(message=last_error_msg)
                )
            else:
                registry.register_strategy(
                    name, _FailingResolver(message=f"earlier error {i}")
                )

        with pytest.raises(GateResolutionError) as exc_info:
            registry.resolve_gate(
                DynamicModel,
                gate_strategy=strategy_names,
                gate_name="test_gate",
            )

        error = exc_info.value
        assert last_error_msg in error.last_error

    @given(
        num_strategies=st.integers(min_value=1, max_value=5),
    )
    def test_all_strategies_are_called_before_error(self, num_strategies: int) -> None:
        """Every strategy in the list is attempted before raising.

        **Validates: Requirements 7.10**
        """
        registry = GateRegistry()
        strategy_names: list[str] = []
        resolvers: list[_FailingResolver] = []

        for i in range(num_strategies):
            name = f"strat_{i}"
            strategy_names.append(name)
            resolver = _FailingResolver(message=f"{name} failed")
            resolvers.append(resolver)
            registry.register_strategy(name, resolver)

        with pytest.raises(GateResolutionError):
            registry.resolve_gate(
                DynamicModel,
                gate_strategy=strategy_names,
                gate_name="test",
            )

        # Every strategy must have been called exactly once
        for resolver in resolvers:
            assert resolver.call_count == 1
