"""Unit tests for FunctualizeApp.register_surface() and get_plugin()."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp


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


class _ValidCollector:
    """Satisfies PromptCollector (has collect)."""

    def collect(self, request: Any) -> Any:
        pass


class _ValidSurface:
    """Satisfies Surface (has handle_event)."""

    def handle_event(self, event: Any) -> None:
        pass


class _EmptyPlugin:
    """Object satisfying neither Surface nor PromptCollector."""

    name = "incomplete"


class TestRegisterSurface:
    """Tests for FunctualizeApp.register_surface()."""

    def test_registers_collector(self, app: FunctualizeApp) -> None:
        """A PromptCollector is appended to the surface list."""
        plugin = _ValidCollector()
        app.register_surface(plugin)
        assert plugin in app._surfaces

    def test_registers_surface(self, app: FunctualizeApp) -> None:
        """A Surface is appended to the surface list."""
        plugin = _ValidSurface()
        app.register_surface(plugin)
        assert plugin in app._surfaces

    def test_multiple_plugins_registered(self, app: FunctualizeApp) -> None:
        """Multiple distinct surfaces can be registered."""
        initial_count = len(app._surfaces)
        p1 = _ValidCollector()
        p2 = _ValidSurface()
        app.register_surface(p1)
        app.register_surface(p2)
        assert len(app._surfaces) == initial_count + 2
        assert p1 in app._surfaces
        assert p2 in app._surfaces

    def test_skip_duplicate_same_instance(self, app: FunctualizeApp) -> None:
        """Registering the same instance twice is a no-op (skips duplicate)."""
        plugin = _ValidCollector()
        app.register_surface(plugin)
        app.register_surface(plugin)
        assert app._surfaces.count(plugin) == 1

    def test_different_instances_same_class_both_registered(
        self, app: FunctualizeApp
    ) -> None:
        """Two different instances of the same class are both registered."""
        initial_count = len(app._surfaces)
        p1 = _ValidCollector()
        p2 = _ValidCollector()
        app.register_surface(p1)
        app.register_surface(p2)
        assert len(app._surfaces) == initial_count + 2

    def test_raises_type_error_empty_plugin(self, app: FunctualizeApp) -> None:
        """TypeError raised for an object satisfying neither protocol."""
        plugin = _EmptyPlugin()
        with pytest.raises(TypeError, match="Surface protocol"):
            app.register_surface(plugin)

    def test_type_error_message_indicates_missing_members(
        self, app: FunctualizeApp
    ) -> None:
        """TypeError message names both methods a registrant may implement."""
        plugin = _EmptyPlugin()
        with pytest.raises(
            TypeError, match="handle_event.*collect|collect.*handle_event"
        ):
            app.register_surface(plugin)

    def test_non_conforming_not_added_to_list(self, app: FunctualizeApp) -> None:
        """Non-conforming object is not added to the surface list."""
        initial_count = len(app._surfaces)
        plugin = _EmptyPlugin()
        with pytest.raises(TypeError):
            app.register_surface(plugin)
        assert len(app._surfaces) == initial_count


class TestGetPlugin:
    """Tests for FunctualizeApp.get_plugin()."""

    def test_returns_plugin_by_name(self, app: FunctualizeApp) -> None:
        """get_plugin returns the registered plugin instance by name."""
        plugin = _ValidCollector()
        app._plugin_name_index["valid-plugin"] = plugin
        assert app.get_plugin("valid-plugin") is plugin

    def test_case_sensitive_lookup(self, app: FunctualizeApp) -> None:
        """Lookup is case-sensitive."""
        plugin = _ValidCollector()
        app._plugin_name_index["valid-plugin"] = plugin
        with pytest.raises(KeyError):
            app.get_plugin("Valid-Plugin")

    def test_raises_key_error_on_miss(self, app: FunctualizeApp) -> None:
        """KeyError raised when plugin name is not registered."""
        with pytest.raises(KeyError, match="not found"):
            app.get_plugin("nonexistent")

    def test_error_message_includes_registered_names(self, app: FunctualizeApp) -> None:
        """KeyError message includes list of registered plugin names."""
        p1 = _ValidCollector()
        p2 = _ValidSurface()
        app._plugin_name_index["valid-plugin"] = p1
        app._plugin_name_index["another-plugin"] = p2
        with pytest.raises(KeyError, match="valid-plugin"):
            app.get_plugin("missing")

    def test_empty_registry_error_message(self, app: FunctualizeApp) -> None:
        """KeyError raised when plugin name is not registered."""
        with pytest.raises(KeyError, match="not found"):
            app.get_plugin("anything-nonexistent-xyz")

    def test_only_returns_completed_plugins(self, app: FunctualizeApp) -> None:
        """Plugins are only available via get_plugin after indexing (post-__call__)."""
        # Initially not indexed
        with pytest.raises(KeyError):
            app.get_plugin("valid-plugin")

        # After indexing (simulating post-__call__ success)
        plugin = _ValidCollector()
        app._plugin_name_index["valid-plugin"] = plugin
        assert app.get_plugin("valid-plugin") is plugin

    def test_multiple_plugins_each_retrievable(self, app: FunctualizeApp) -> None:
        """Multiple registered plugins are each retrievable by their name."""
        p1 = _ValidCollector()
        p2 = _ValidSurface()
        app._plugin_name_index["valid-plugin"] = p1
        app._plugin_name_index["another-plugin"] = p2
        assert app.get_plugin("valid-plugin") is p1
        assert app.get_plugin("another-plugin") is p2
