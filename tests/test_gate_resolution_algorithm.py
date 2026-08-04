"""Unit tests for the gate resolution algorithm (GateRegistry.resolve_gate).

Validates: Requirements 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 7.12
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize._gate import GateContext, GateRegistry, GateStrategy
from functualize._gate._resolver import ResolveResolver
from functualize._types.errors import GateResolutionError

# --- Test models ---


class FullyDefaultedModel(BaseModel):
    """Model with all fields having defaults (always fully resolvable)."""

    name: str = "default_name"
    count: int = 0


class PartialModel(BaseModel):
    """Model with some required and some defaulted fields."""

    required_field: str
    optional_field: str = "default_value"


class AllRequiredModel(BaseModel):
    """Model with all required fields (no defaults)."""

    host: str
    port: int


# --- Test resolvers ---


class SuccessResolver:
    """Resolver that always succeeds by filling in missing fields."""

    def __init__(self, fill_values: dict | None = None):
        self.fill_values = fill_values or {}
        self.call_count = 0

    def resolve(self, ctx: GateContext) -> BaseModel:
        self.call_count += 1
        fields = {**ctx.resolved_fields, **self.fill_values}
        return ctx.model_class(**fields)


class FailingResolver:
    """Resolver that always raises an exception."""

    def __init__(self, message: str = "strategy failed"):
        self.message = message
        self.call_count = 0

    def resolve(self, ctx: GateContext) -> BaseModel:
        self.call_count += 1
        raise RuntimeError(self.message)


class TrackingResolver:
    """Resolver that tracks calls and conditionally succeeds."""

    def __init__(self, should_fail: bool = False, fill_values: dict | None = None):
        self.should_fail = should_fail
        self.fill_values = fill_values or {}
        self.call_count = 0
        self.last_ctx: GateContext | None = None

    def resolve(self, ctx: GateContext) -> BaseModel:
        self.call_count += 1
        self.last_ctx = ctx
        if self.should_fail:
            raise RuntimeError("tracking resolver failed")
        fields = {**ctx.resolved_fields, **self.fill_values}
        return ctx.model_class(**fields)


class TestResolveGateShortCircuit:
    """Tests for Requirement 7.6: short-circuit when fully resolved."""

    def test_fully_resolved_no_force_returns_model_directly(self) -> None:
        """When all fields resolved and force_gate=False, returns model without strategy."""
        registry = GateRegistry()
        tracker = TrackingResolver()
        registry.register_strategy("resolve", tracker)

        result = registry.resolve_gate(
            FullyDefaultedModel,
            force_gate=False,
            resolved_fields={"name": "custom", "count": 5},
        )

        assert isinstance(result, FullyDefaultedModel)
        assert result.name == "custom"
        assert result.count == 5
        # Strategy should NOT have been called
        assert tracker.call_count == 0

    def test_defaults_count_as_resolved(self) -> None:
        """Fields with model defaults are treated as resolved."""
        registry = GateRegistry()
        tracker = TrackingResolver()
        registry.register_strategy("resolve", tracker)

        # Pass no explicit resolved_fields; model defaults make it fully resolved
        result = registry.resolve_gate(
            FullyDefaultedModel,
            force_gate=False,
        )

        assert isinstance(result, FullyDefaultedModel)
        assert result.name == "default_name"
        assert result.count == 0
        assert tracker.call_count == 0

    def test_partial_defaults_with_explicit_resolved(self) -> None:
        """Mix of explicit resolved and defaults still short-circuits."""
        registry = GateRegistry()
        tracker = TrackingResolver()
        registry.register_strategy("resolve", tracker)

        result = registry.resolve_gate(
            PartialModel,
            force_gate=False,
            resolved_fields={"required_field": "hello"},
        )

        assert isinstance(result, PartialModel)
        assert result.required_field == "hello"
        assert result.optional_field == "default_value"
        assert tracker.call_count == 0


class TestResolveGateDispatchOnUnresolved:
    """Tests for Requirement 7.7: dispatch when fields are unresolved."""

    def test_unresolved_fields_triggers_strategy(self) -> None:
        """When required fields are unresolved, dispatches to strategy."""
        registry = GateRegistry()
        resolver = SuccessResolver(fill_values={"host": "localhost", "port": 8080})
        registry.register_strategy("resolve", resolver)

        result = registry.resolve_gate(
            AllRequiredModel,
            force_gate=False,
        )

        assert isinstance(result, AllRequiredModel)
        assert result.host == "localhost"
        assert result.port == 8080
        assert resolver.call_count == 1

    def test_context_contains_unresolved_fields(self) -> None:
        """GateContext passed to resolver contains correct unresolved field list."""
        registry = GateRegistry()
        tracker = TrackingResolver(fill_values={"host": "h", "port": 1})
        registry.register_strategy("resolve", tracker)

        registry.resolve_gate(
            AllRequiredModel,
            force_gate=False,
            resolved_fields={"host": "myhost"},
        )

        assert tracker.last_ctx is not None
        assert "port" in tracker.last_ctx.unresolved_fields
        assert "host" not in tracker.last_ctx.unresolved_fields
        assert tracker.last_ctx.resolved_fields["host"] == "myhost"


class TestResolveGateForceGate:
    """Tests for Requirement 7.8: force_gate dispatches even when resolved."""

    def test_force_gate_dispatches_when_fully_resolved(self) -> None:
        """force_gate=True dispatches to strategy even when model is fully resolved."""
        registry = GateRegistry()
        tracker = TrackingResolver(fill_values={"name": "forced", "count": 99})
        registry.register_strategy("resolve", tracker)

        result = registry.resolve_gate(
            FullyDefaultedModel,
            force_gate=True,
            resolved_fields={"name": "original", "count": 1},
        )

        assert isinstance(result, FullyDefaultedModel)
        assert tracker.call_count == 1
        # Verify the context reflects force_gate=True
        assert tracker.last_ctx is not None
        assert tracker.last_ctx.force_gate is True

    def test_force_gate_passes_resolved_fields_to_strategy(self) -> None:
        """When force_gate=True, resolved fields are still passed in context."""
        registry = GateRegistry()
        tracker = TrackingResolver(fill_values={"name": "x", "count": 0})
        registry.register_strategy("resolve", tracker)

        registry.resolve_gate(
            FullyDefaultedModel,
            force_gate=True,
            resolved_fields={"name": "provided", "count": 42},
        )

        assert tracker.last_ctx is not None
        assert tracker.last_ctx.resolved_fields["name"] == "provided"
        assert tracker.last_ctx.resolved_fields["count"] == 42


class TestResolveGateOrderedFallback:
    """Tests for Requirement 7.9: ordered strategy fallback."""

    def test_first_success_wins(self) -> None:
        """First strategy that succeeds provides the result."""
        registry = GateRegistry()
        s1 = SuccessResolver(fill_values={"host": "first", "port": 1})
        s2 = SuccessResolver(fill_values={"host": "second", "port": 2})
        registry.register_strategy("s1", s1)
        registry.register_strategy("s2", s2)

        result = registry.resolve_gate(
            AllRequiredModel,
            gate_strategy=["s1", "s2"],
        )

        assert result.host == "first"
        assert s1.call_count == 1
        assert s2.call_count == 0

    def test_fallback_to_second_on_first_failure(self) -> None:
        """If first strategy fails, second is tried."""
        registry = GateRegistry()
        s1 = FailingResolver("first failed")
        s2 = SuccessResolver(fill_values={"host": "fallback", "port": 9999})
        registry.register_strategy("s1", s1)
        registry.register_strategy("s2", s2)

        result = registry.resolve_gate(
            AllRequiredModel,
            gate_strategy=["s1", "s2"],
        )

        assert result.host == "fallback"
        assert result.port == 9999
        assert s1.call_count == 1
        assert s2.call_count == 1

    def test_multiple_failures_before_success(self) -> None:
        """Strategies are tried in order until one succeeds."""
        registry = GateRegistry()
        s1 = FailingResolver("s1 failed")
        s2 = FailingResolver("s2 failed")
        s3 = SuccessResolver(fill_values={"host": "third", "port": 3})
        registry.register_strategy("s1", s1)
        registry.register_strategy("s2", s2)
        registry.register_strategy("s3", s3)

        result = registry.resolve_gate(
            AllRequiredModel,
            gate_strategy=["s1", "s2", "s3"],
        )

        assert result.host == "third"
        assert s1.call_count == 1
        assert s2.call_count == 1
        assert s3.call_count == 1

    def test_preset_expands_strategies_in_order(self) -> None:
        """Presets expand into their constituent strategies in order."""
        registry = GateRegistry()
        s1 = FailingResolver("s1 failed")
        s2 = SuccessResolver(fill_values={"host": "from_preset", "port": 42})
        registry.register_strategy("strategy_a", s1)
        registry.register_strategy("strategy_b", s2)
        registry.register_preset("my_preset", ["strategy_a", "strategy_b"])

        result = registry.resolve_gate(
            AllRequiredModel,
            gate_strategy="my_preset",
        )

        assert result.host == "from_preset"
        assert s1.call_count == 1
        assert s2.call_count == 1


class TestResolveGateAllFail:
    """Tests for Requirement 7.10: all strategies failing raises error."""

    def test_all_strategies_fail_raises_gate_resolution_error(self) -> None:
        """When all strategies fail, raises GateResolutionError."""
        registry = GateRegistry()
        s1 = FailingResolver("s1 error")
        s2 = FailingResolver("s2 error")
        registry.register_strategy("s1", s1)
        registry.register_strategy("s2", s2)

        with pytest.raises(GateResolutionError) as exc_info:
            registry.resolve_gate(
                AllRequiredModel,
                gate_strategy=["s1", "s2"],
                gate_name="test_gate",
            )

        error = exc_info.value
        assert error.gate_name == "test_gate"
        assert error.strategies_attempted == 2
        assert "s2 error" in error.last_error

    def test_single_strategy_fail_raises_error(self) -> None:
        """Single failing strategy raises GateResolutionError."""
        registry = GateRegistry()
        s1 = FailingResolver("only one failed")
        registry.register_strategy("s1", s1)

        with pytest.raises(GateResolutionError) as exc_info:
            registry.resolve_gate(
                AllRequiredModel,
                gate_strategy="s1",
                gate_name="single_gate",
            )

        error = exc_info.value
        assert error.strategies_attempted == 1
        assert "only one failed" in error.last_error


class TestResolveGateDefaultStrategy:
    """Tests for Requirement 7.11: default to GateStrategy.RESOLVE."""

    def test_no_strategy_defaults_to_resolve(self) -> None:
        """When no gate_strategy specified, defaults to GateStrategy.RESOLVE."""
        registry = GateRegistry()
        resolve_resolver = SuccessResolver(
            fill_values={"host": "default_resolved", "port": 80}
        )
        registry.register_strategy("resolve", resolve_resolver)

        result = registry.resolve_gate(
            AllRequiredModel,
            gate_strategy=None,
        )

        assert result.host == "default_resolved"
        assert resolve_resolver.call_count == 1

    def test_default_resolve_strategy_registered_at_boot(self) -> None:
        """The ResolveResolver is a valid resolver that resolves from fields."""
        resolver = ResolveResolver()
        ctx = GateContext(
            model_class=FullyDefaultedModel,
            resolved_fields={"name": "resolved", "count": 10},
            unresolved_fields=[],
            all_fields=["name", "count"],
            force_gate=True,
            workflow_context={},
        )

        result = resolver.resolve(ctx)
        assert isinstance(result, FullyDefaultedModel)
        assert result.name == "resolved"
        assert result.count == 10

    def test_resolve_resolver_raises_on_unresolved_fields(self) -> None:
        """ResolveResolver raises ValueError when fields are unresolved."""
        resolver = ResolveResolver()
        ctx = GateContext(
            model_class=AllRequiredModel,
            resolved_fields={"host": "myhost"},
            unresolved_fields=["port"],
            all_fields=["host", "port"],
            force_gate=False,
            workflow_context={},
        )

        with pytest.raises(ValueError, match="unresolved fields"):
            resolver.resolve(ctx)


class TestResolveGateUnregisteredStrategy:
    """Tests for Requirement 7.12: error on unregistered strategy in preset."""

    def test_unregistered_strategy_in_preset_raises_at_resolution_time(self) -> None:
        """Preset referencing unregistered strategy raises ValueError at resolution."""
        registry = GateRegistry()
        # Register a preset that references strategies that don't exist
        registry.register_preset(
            "broken_preset", ["registered_one", "unregistered_two"]
        )

        # Register only one of the referenced strategies
        s1 = FailingResolver("fails so we try next")
        registry.register_strategy("registered_one", s1)

        with pytest.raises(ValueError, match="Unregistered gate strategy") as exc_info:
            registry.resolve_gate(
                AllRequiredModel,
                gate_strategy="broken_preset",
            )

        # Error message should identify both the strategy and the preset
        error_msg = str(exc_info.value)
        assert "unregistered_two" in error_msg
        assert "broken_preset" in error_msg

    def test_unregistered_direct_strategy_raises(self) -> None:
        """Directly referencing an unregistered strategy raises ValueError."""
        registry = GateRegistry()

        with pytest.raises(ValueError, match="Unregistered gate strategy"):
            registry.resolve_gate(
                AllRequiredModel,
                gate_strategy="nonexistent",
                gate_name="my_gate",
            )

    def test_registered_preset_with_all_strategies_works(self) -> None:
        """Preset with all strategies registered works without error."""
        registry = GateRegistry()
        s1 = SuccessResolver(fill_values={"host": "h", "port": 1})
        s2 = SuccessResolver(fill_values={"host": "h2", "port": 2})
        registry.register_strategy("strat_a", s1)
        registry.register_strategy("strat_b", s2)
        registry.register_preset("valid_preset", ["strat_a", "strat_b"])

        result = registry.resolve_gate(
            AllRequiredModel,
            gate_strategy="valid_preset",
        )

        assert isinstance(result, AllRequiredModel)


class TestResolveGateContextBuilding:
    """Tests for correct GateContext construction."""

    def test_context_has_all_fields(self) -> None:
        """GateContext includes all model field names."""
        registry = GateRegistry()
        tracker = TrackingResolver(fill_values={"host": "h", "port": 1})
        registry.register_strategy("resolve", tracker)

        registry.resolve_gate(
            AllRequiredModel,
            resolved_fields={"host": "myhost"},
        )

        assert tracker.last_ctx is not None
        assert set(tracker.last_ctx.all_fields) == {"host", "port"}

    def test_workflow_context_passed_through(self) -> None:
        """workflow_context is passed through to GateContext."""
        registry = GateRegistry()
        tracker = TrackingResolver(fill_values={"host": "h", "port": 1})
        registry.register_strategy("resolve", tracker)

        registry.resolve_gate(
            AllRequiredModel,
            workflow_context={"step": "input", "iteration": 3},
        )

        assert tracker.last_ctx is not None
        assert tracker.last_ctx.workflow_context == {"step": "input", "iteration": 3}

    def test_gate_strategy_enum_value_accepted(self) -> None:
        """GateStrategy enum values are accepted as gate_strategy."""
        registry = GateRegistry()
        resolver = SuccessResolver(fill_values={"host": "h", "port": 1})
        registry.register_strategy("resolve", resolver)

        result = registry.resolve_gate(
            AllRequiredModel,
            gate_strategy=GateStrategy.RESOLVE,
        )

        assert isinstance(result, AllRequiredModel)
        assert resolver.call_count == 1

    def test_list_of_enum_and_string_strategies(self) -> None:
        """Mixed list of GateStrategy enum and strings works."""
        registry = GateRegistry()
        s1 = FailingResolver("enum failed")
        s2 = SuccessResolver(fill_values={"host": "mixed", "port": 42})
        registry.register_strategy("resolve", s1)
        registry.register_strategy("custom", s2)

        result = registry.resolve_gate(
            AllRequiredModel,
            gate_strategy=[GateStrategy.RESOLVE, "custom"],
        )

        assert result.host == "mixed"
        assert result.port == 42
