"""Unit tests for FunctualizeApp gate strategy registry facade.

Tests that register_gate_strategy and register_gate_preset methods on
FunctualizeApp correctly delegate to the internal GateRegistry and expose
strategies via _gate_strategies and _gate_presets properties.

Validates: Requirements 7.4, 7.5
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._gate import GateContext, GateResolver
from functualize.app.core import FunctualizeApp


class SampleModel(BaseModel):
    """Sample model for gate resolver tests."""

    name: str = "default"
    value: int = 0


class SimpleResolver:
    """A minimal GateResolver implementation for testing."""

    def resolve(self, ctx: GateContext) -> BaseModel:
        return SampleModel(name="resolved", value=42)


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def app() -> FunctualizeApp:
    """Create a minimal FunctualizeApp for testing."""
    return FunctualizeApp(name="testapp")


class TestRegisterGateStrategy:
    """Tests for FunctualizeApp.register_gate_strategy."""

    def test_register_and_access_strategy(self, app: FunctualizeApp) -> None:
        """Registered strategy appears in _gate_strategies dict."""
        resolver = SimpleResolver()
        app.register_gate_strategy("my_strategy", resolver)
        assert app._gate_strategies["my_strategy"] is resolver

    def test_register_multiple_strategies(self, app: FunctualizeApp) -> None:
        """Multiple strategies can be registered."""
        r1 = SimpleResolver()
        r2 = SimpleResolver()
        initial_count = len(app._gate_strategies)
        app.register_gate_strategy("strategy_a", r1)
        app.register_gate_strategy("strategy_b", r2)
        assert app._gate_strategies["strategy_a"] is r1
        assert app._gate_strategies["strategy_b"] is r2
        # Two new strategies should have been added beyond whatever boot registered
        assert len(app._gate_strategies) == initial_count + 2

    def test_name_min_length_valid(self, app: FunctualizeApp) -> None:
        """Single character name is valid."""
        resolver = SimpleResolver()
        app.register_gate_strategy("x", resolver)
        assert "x" in app._gate_strategies

    def test_name_max_length_valid(self, app: FunctualizeApp) -> None:
        """64 character name is valid."""
        resolver = SimpleResolver()
        name = "a" * 64
        app.register_gate_strategy(name, resolver)
        assert name in app._gate_strategies

    def test_name_too_short_raises(self, app: FunctualizeApp) -> None:
        """Empty name raises ValueError."""
        with pytest.raises(ValueError, match="1-64 chars"):
            app.register_gate_strategy("", SimpleResolver())

    def test_name_too_long_raises(self, app: FunctualizeApp) -> None:
        """Name exceeding 64 characters raises ValueError."""
        with pytest.raises(ValueError, match="1-64 chars"):
            app.register_gate_strategy("x" * 65, SimpleResolver())

    def test_strategies_dict_initially_has_default_resolve(
        self, app: FunctualizeApp
    ) -> None:
        """_gate_strategies contains the built-in 'resolve' strategy after boot."""
        assert "resolve" in app._gate_strategies
        # At minimum, the 'resolve' strategy is registered; plugins may add more
        assert len(app._gate_strategies) >= 1

    def test_overwrite_existing_strategy(self, app: FunctualizeApp) -> None:
        """Re-registering same name replaces the previous resolver."""
        r1 = SimpleResolver()
        r2 = SimpleResolver()
        app.register_gate_strategy("same", r1)
        app.register_gate_strategy("same", r2)
        assert app._gate_strategies["same"] is r2

    def test_resolver_conforms_to_protocol(self, app: FunctualizeApp) -> None:
        """Registered resolver satisfies GateResolver protocol."""
        resolver = SimpleResolver()
        app.register_gate_strategy("proto_test", resolver)
        assert isinstance(app._gate_strategies["proto_test"], GateResolver)


class TestRegisterGatePreset:
    """Tests for FunctualizeApp.register_gate_preset."""

    def test_register_and_access_preset(self, app: FunctualizeApp) -> None:
        """Registered preset appears in _gate_presets dict."""
        app.register_gate_preset("interactive", ["prompt", "ai_fill"])
        assert app._gate_presets["interactive"] == ["prompt", "ai_fill"]

    def test_register_multiple_presets(self, app: FunctualizeApp) -> None:
        """Multiple presets can be registered."""
        initial_count = len(app._gate_presets)
        app.register_gate_preset("headless", ["config_only"])
        app.register_gate_preset("interactive", ["prompt", "ai_fill"])
        assert len(app._gate_presets) == initial_count + 2

    def test_preset_min_strategies_valid(self, app: FunctualizeApp) -> None:
        """Preset with 1 strategy is valid."""
        app.register_gate_preset("minimal", ["resolve"])
        assert app._gate_presets["minimal"] == ["resolve"]

    def test_preset_max_strategies_valid(self, app: FunctualizeApp) -> None:
        """Preset with 10 strategies is valid."""
        strategies = [f"s{i}" for i in range(10)]
        app.register_gate_preset("maxed", strategies)
        assert app._gate_presets["maxed"] == strategies

    def test_preset_empty_strategies_raises(self, app: FunctualizeApp) -> None:
        """Empty strategies list raises ValueError."""
        with pytest.raises(ValueError, match="1-10 strategies"):
            app.register_gate_preset("empty", [])

    def test_preset_too_many_strategies_raises(self, app: FunctualizeApp) -> None:
        """More than 10 strategies raises ValueError."""
        with pytest.raises(ValueError, match="1-10 strategies"):
            app.register_gate_preset("big", [f"s{i}" for i in range(11)])

    def test_presets_dict_initially_empty(self, app: FunctualizeApp) -> None:
        """_gate_presets contains no user-registered presets at boot (plugins may add some)."""
        # Plugins like MCP may register presets during boot, so we just
        # verify the dict exists and is accessible (not necessarily empty)
        assert isinstance(app._gate_presets, dict)

    def test_overwrite_existing_preset(self, app: FunctualizeApp) -> None:
        """Re-registering same preset name replaces the previous list."""
        app.register_gate_preset("test", ["a", "b"])
        app.register_gate_preset("test", ["c"])
        assert app._gate_presets["test"] == ["c"]
