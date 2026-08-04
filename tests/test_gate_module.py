"""Unit tests for the Gate module (GateStrategy, GateContext, GateResolver, GateRegistry).

Validates: Requirements 7.1, 7.2, 7.3
"""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import BaseModel

from functualize._gate import GateContext, GateRegistry, GateResolver, GateStrategy


class SampleModel(BaseModel):
    """Sample BaseModel for testing GateContext."""

    name: str = "default"
    age: int = 0


class TestGateStrategy:
    """Tests for the GateStrategy enum."""

    def test_resolve_variant_exists(self) -> None:
        """GateStrategy has a RESOLVE variant."""
        assert hasattr(GateStrategy, "RESOLVE")

    def test_resolve_value(self) -> None:
        """GateStrategy.RESOLVE has value 'resolve'."""
        assert GateStrategy.RESOLVE.value == "resolve"

    def test_is_string_enum(self) -> None:
        """GateStrategy inherits from str, allowing string comparison."""
        assert isinstance(GateStrategy.RESOLVE, str)
        assert GateStrategy.RESOLVE == "resolve"

    def test_enum_from_value(self) -> None:
        """GateStrategy can be constructed from string value."""
        assert GateStrategy("resolve") is GateStrategy.RESOLVE


class TestGateContext:
    """Tests for the GateContext frozen dataclass."""

    def test_all_fields(self) -> None:
        """GateContext stores all required fields correctly."""
        ctx = GateContext(
            model_class=SampleModel,
            resolved_fields={"name": "Alice"},
            unresolved_fields=["age"],
            all_fields=["name", "age"],
            force_gate=True,
            workflow_context={"step": "input"},
        )
        assert ctx.model_class is SampleModel
        assert ctx.resolved_fields == {"name": "Alice"}
        assert ctx.unresolved_fields == ["age"]
        assert ctx.all_fields == ["name", "age"]
        assert ctx.force_gate is True
        assert ctx.workflow_context == {"step": "input"}

    def test_workflow_context_defaults_to_empty(self) -> None:
        """GateContext.workflow_context defaults to an empty dict."""
        ctx = GateContext(
            model_class=SampleModel,
            resolved_fields={},
            unresolved_fields=["name", "age"],
            all_fields=["name", "age"],
            force_gate=False,
        )
        assert ctx.workflow_context == {}

    def test_frozen(self) -> None:
        """GateContext is immutable (frozen dataclass)."""
        ctx = GateContext(
            model_class=SampleModel,
            resolved_fields={},
            unresolved_fields=[],
            all_fields=[],
            force_gate=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.force_gate = True  # type: ignore[misc]

    def test_field_names(self) -> None:
        """GateContext has exactly the expected fields."""
        field_names = [f.name for f in dataclasses.fields(GateContext)]
        expected = [
            "model_class",
            "resolved_fields",
            "unresolved_fields",
            "all_fields",
            "force_gate",
            "workflow_context",
        ]
        assert field_names == expected


class TestGateResolver:
    """Tests for the GateResolver protocol."""

    def test_runtime_checkable(self) -> None:
        """GateResolver supports isinstance checks at runtime."""

        class ValidResolver:
            def resolve(self, ctx: GateContext) -> BaseModel:
                return SampleModel(name="resolved", age=30)

        resolver = ValidResolver()
        assert isinstance(resolver, GateResolver)

    def test_non_conforming_class_not_instance(self) -> None:
        """Classes without resolve method are not GateResolver instances."""

        class NotAResolver:
            def do_something(self) -> None:
                pass

        assert not isinstance(NotAResolver(), GateResolver)

    def test_resolver_can_be_called(self) -> None:
        """A conforming resolver can produce a BaseModel from a GateContext."""

        class MyResolver:
            def resolve(self, ctx: GateContext) -> BaseModel:
                return ctx.model_class(**ctx.resolved_fields, age=42)

        ctx = GateContext(
            model_class=SampleModel,
            resolved_fields={"name": "Test"},
            unresolved_fields=["age"],
            all_fields=["name", "age"],
            force_gate=False,
        )
        result = MyResolver().resolve(ctx)
        assert isinstance(result, SampleModel)
        assert result.name == "Test"
        assert result.age == 42


class TestGateRegistry:
    """Tests for the GateRegistry class."""

    def test_register_and_get_strategy(self) -> None:
        """Registered strategies can be retrieved by name."""

        class MyResolver:
            def resolve(self, ctx: GateContext) -> BaseModel:
                return SampleModel()

        registry = GateRegistry()
        resolver = MyResolver()
        registry.register_strategy("my_strategy", resolver)
        assert registry.get_strategy("my_strategy") is resolver

    def test_get_unregistered_strategy_returns_none(self) -> None:
        """Getting an unregistered strategy returns None."""
        registry = GateRegistry()
        assert registry.get_strategy("nonexistent") is None

    def test_strategy_name_too_short_raises(self) -> None:
        """Strategy name must be at least 1 character."""

        class MyResolver:
            def resolve(self, ctx: GateContext) -> BaseModel:
                return SampleModel()

        registry = GateRegistry()
        with pytest.raises(ValueError, match="1-64 chars"):
            registry.register_strategy("", MyResolver())

    def test_strategy_name_too_long_raises(self) -> None:
        """Strategy name must be at most 64 characters."""

        class MyResolver:
            def resolve(self, ctx: GateContext) -> BaseModel:
                return SampleModel()

        registry = GateRegistry()
        with pytest.raises(ValueError, match="1-64 chars"):
            registry.register_strategy("x" * 65, MyResolver())

    def test_strategy_name_at_boundary_64(self) -> None:
        """Strategy name of exactly 64 characters is valid."""

        class MyResolver:
            def resolve(self, ctx: GateContext) -> BaseModel:
                return SampleModel()

        registry = GateRegistry()
        name = "a" * 64
        registry.register_strategy(name, MyResolver())
        assert registry.get_strategy(name) is not None

    def test_register_and_get_preset(self) -> None:
        """Registered presets can be retrieved by name."""
        registry = GateRegistry()
        registry.register_preset("interactive", ["prompt", "ai_fill"])
        assert registry.get_preset("interactive") == ["prompt", "ai_fill"]

    def test_get_unregistered_preset_returns_none(self) -> None:
        """Getting an unregistered preset returns None."""
        registry = GateRegistry()
        assert registry.get_preset("nonexistent") is None

    def test_preset_too_few_strategies_raises(self) -> None:
        """Preset must reference at least 1 strategy."""
        registry = GateRegistry()
        with pytest.raises(ValueError, match="1-10 strategies"):
            registry.register_preset("empty", [])

    def test_preset_too_many_strategies_raises(self) -> None:
        """Preset must reference at most 10 strategies."""
        registry = GateRegistry()
        with pytest.raises(ValueError, match="1-10 strategies"):
            registry.register_preset("big", [f"s{i}" for i in range(11)])

    def test_preset_at_boundary_10(self) -> None:
        """Preset with exactly 10 strategies is valid."""
        registry = GateRegistry()
        strategies = [f"strategy_{i}" for i in range(10)]
        registry.register_preset("max", strategies)
        assert registry.get_preset("max") == strategies
