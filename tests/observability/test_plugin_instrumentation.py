"""Unit tests for plugin boundary instrumentation points (Task 11.3).

Tests that plugin.discovery, plugin.load, and plugin.registration events
are emitted at the correct lifecycle boundaries with fault-tolerant wrapping.

Requirements: 6.3
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from functualize._events.bus import EventBus
from functualize._plugins.loader import PluginLoader

if TYPE_CHECKING:
    from functualize._events.bus import StructuredEvent


def _make_plugin(
    name: str = "test-plugin",
    version: str = "1.0.0",
    description: str = "A test plugin",
    call_side_effect: Any = None,
) -> Any:
    """Create a mock plugin satisfying PluginMetadata protocol."""
    plugin = MagicMock()
    plugin.name = name
    plugin.version = version
    plugin.description = description
    plugin.depends_on = []
    # Remove config attributes (legacy plugin)
    del plugin.config_model
    del plugin.config_section
    del plugin.on_config_resolved
    if call_side_effect:
        plugin.side_effect = call_side_effect
    return plugin


def _make_entry_point(name: str, plugin: Any) -> Any:
    """Create a mock entry point returning the given plugin."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = plugin
    return ep


def _make_app_with_event_bus() -> Any:
    """Create a minimal app mock with a working EventBus."""
    app = MagicMock()
    event_bus = EventBus()
    app.event_bus = event_bus
    app.plugin_config_registry = MagicMock()
    app.plugin_config_registry.has.return_value = False
    return app


class TestPluginDiscoveryInstrumentation:
    """Tests for plugin.discovery.start and plugin.discovery.end events."""

    @patch("functualize._plugins.loader.entry_points")
    def test_discovery_start_and_end_emitted(self, mock_entry_points: Any) -> None:
        """plugin.discovery.start and .end are emitted around plugin discovery."""
        plugin = _make_plugin()
        ep = _make_entry_point("test-ep", plugin)
        mock_entry_points.return_value = [ep]

        app = _make_app_with_event_bus()
        events: list[StructuredEvent] = []
        app.event_bus.subscribe("plugin.discovery.*", lambda e: events.append(e))

        loader = PluginLoader("functualize.plugins")
        loader.load_all(app, event_bus=app.event_bus)

        # Filter for discovery events
        discovery_events = [e for e in events if "discovery" in e.event_name]
        assert len(discovery_events) == 2

        start_event = discovery_events[0]
        assert start_event.event_name == "plugin.discovery.start"
        assert start_event.payload["group"] == "functualize.plugins"
        assert start_event.resource == "functualize.plugins"

        end_event = discovery_events[1]
        assert end_event.event_name == "plugin.discovery.end"
        assert end_event.payload["group"] == "functualize.plugins"
        assert end_event.payload["count"] == 1
        assert "duration_ms" in end_event.payload
        assert end_event.payload["duration_ms"] >= 0

    @patch("functualize._plugins.loader.entry_points")
    def test_discovery_end_count_reflects_valid_plugins_only(
        self, mock_entry_points: Any
    ) -> None:
        """Discovery end count only reflects successfully loaded plugins."""
        valid_plugin = _make_plugin(name="valid")
        # Invalid plugin with bad metadata
        invalid_plugin = MagicMock()
        invalid_plugin.name = "x" * 100  # exceeds 64 chars
        invalid_plugin.version = "1.0.0"
        invalid_plugin.description = "bad"
        invalid_plugin.depends_on = []
        del invalid_plugin.config_model
        del invalid_plugin.config_section
        del invalid_plugin.on_config_resolved

        ep_valid = _make_entry_point("valid-ep", valid_plugin)
        ep_invalid = _make_entry_point("invalid-ep", invalid_plugin)
        mock_entry_points.return_value = [ep_valid, ep_invalid]

        app = _make_app_with_event_bus()
        events: list[StructuredEvent] = []
        app.event_bus.subscribe("plugin.discovery.end", lambda e: events.append(e))

        loader = PluginLoader("functualize.plugins")
        loader.load_all(app, event_bus=app.event_bus)

        assert len(events) == 1
        # Only 1 valid plugin loaded
        assert events[0].payload["count"] == 1

    @patch("functualize._plugins.loader.entry_points")
    def test_discovery_emitted_with_no_plugins_found(
        self, mock_entry_points: Any
    ) -> None:
        """Discovery events emitted even when no plugins are found."""
        mock_entry_points.return_value = []

        app = _make_app_with_event_bus()
        events: list[StructuredEvent] = []
        app.event_bus.subscribe("plugin.*", lambda e: events.append(e))

        loader = PluginLoader("functualize.plugins")
        loader.load_all(app, event_bus=app.event_bus)

        discovery_events = [e for e in events if "discovery" in e.event_name]
        assert len(discovery_events) == 2
        assert discovery_events[0].event_name == "plugin.discovery.start"
        assert discovery_events[1].event_name == "plugin.discovery.end"
        assert discovery_events[1].payload["count"] == 0


class TestPluginLoadInstrumentation:
    """Tests for plugin.load.start and plugin.load.end events."""

    @patch("functualize._plugins.loader.entry_points")
    def test_load_start_and_end_emitted_per_plugin(
        self, mock_entry_points: Any
    ) -> None:
        """plugin.load.start and .end emitted for each entry point."""
        plugin_a = _make_plugin(name="alpha", version="1.0.0")
        plugin_b = _make_plugin(name="beta", version="2.0.0")
        ep_a = _make_entry_point("alpha-ep", plugin_a)
        ep_b = _make_entry_point("beta-ep", plugin_b)
        mock_entry_points.return_value = [ep_a, ep_b]

        app = _make_app_with_event_bus()
        events: list[StructuredEvent] = []
        app.event_bus.subscribe("plugin.load.*", lambda e: events.append(e))

        loader = PluginLoader("functualize.plugins")
        loader.load_all(app, event_bus=app.event_bus)

        load_events = [e for e in events if "load" in e.event_name]
        # 2 plugins × (start + end) = 4
        assert len(load_events) == 4

        # First plugin: start then end
        assert load_events[0].event_name == "plugin.load.start"
        assert load_events[0].payload["plugin_name"] == "alpha-ep"
        assert load_events[0].payload["entry_point"] == "alpha-ep"

        assert load_events[1].event_name == "plugin.load.end"
        assert load_events[1].payload["plugin_name"] == "alpha"
        assert load_events[1].payload["version"] == "1.0.0"
        assert "duration_ms" in load_events[1].payload

        # Second plugin: start then end
        assert load_events[2].event_name == "plugin.load.start"
        assert load_events[2].payload["plugin_name"] == "beta-ep"

        assert load_events[3].event_name == "plugin.load.end"
        assert load_events[3].payload["plugin_name"] == "beta"
        assert load_events[3].payload["version"] == "2.0.0"

    @patch("functualize._plugins.loader.entry_points")
    def test_load_end_emitted_even_on_load_failure(
        self, mock_entry_points: Any
    ) -> None:
        """plugin.load.end is emitted even when ep.load() raises."""
        ep = MagicMock()
        ep.name = "broken-ep"
        ep.load.side_effect = ImportError("module not found")
        mock_entry_points.return_value = [ep]

        app = _make_app_with_event_bus()
        events: list[StructuredEvent] = []
        app.event_bus.subscribe("plugin.load.*", lambda e: events.append(e))

        loader = PluginLoader("functualize.plugins")
        loader.load_all(app, event_bus=app.event_bus)

        load_events = [e for e in events if "load" in e.event_name]
        assert len(load_events) == 2
        assert load_events[0].event_name == "plugin.load.start"
        assert load_events[1].event_name == "plugin.load.end"
        assert "duration_ms" in load_events[1].payload


class TestPluginRegistrationInstrumentation:
    """Tests for plugin.registration.start and plugin.registration.end events."""

    @patch("functualize._plugins.loader.entry_points")
    def test_registration_start_and_end_emitted(self, mock_entry_points: Any) -> None:
        """plugin.registration.start and .end wrap plugin.__call__(app)."""
        plugin = _make_plugin(name="my-plugin")
        ep = _make_entry_point("my-ep", plugin)
        mock_entry_points.return_value = [ep]

        app = _make_app_with_event_bus()
        events: list[StructuredEvent] = []
        app.event_bus.subscribe("plugin.registration.*", lambda e: events.append(e))

        loader = PluginLoader("functualize.plugins")
        loader.load_all(app, event_bus=app.event_bus)

        reg_events = [e for e in events if "registration" in e.event_name]
        assert len(reg_events) == 2

        assert reg_events[0].event_name == "plugin.registration.start"
        assert reg_events[0].payload["plugin_name"] == "my-plugin"
        assert reg_events[0].resource == "my-plugin"

        assert reg_events[1].event_name == "plugin.registration.end"
        assert reg_events[1].payload["plugin_name"] == "my-plugin"
        assert "duration_ms" in reg_events[1].payload
        assert reg_events[1].payload["duration_ms"] >= 0

    @patch("functualize._plugins.loader.entry_points")
    def test_registration_end_emitted_on_call_failure(
        self, mock_entry_points: Any
    ) -> None:
        """plugin.registration.end emitted even when plugin(app) raises."""
        plugin = _make_plugin(name="failing-plugin")
        plugin.side_effect = RuntimeError("registration failed")
        ep = _make_entry_point("failing-ep", plugin)
        mock_entry_points.return_value = [ep]

        app = _make_app_with_event_bus()
        events: list[StructuredEvent] = []
        app.event_bus.subscribe("plugin.registration.*", lambda e: events.append(e))

        loader = PluginLoader("functualize.plugins")
        loader.load_all(app, event_bus=app.event_bus)

        reg_events = [e for e in events if "registration" in e.event_name]
        assert len(reg_events) == 2
        assert reg_events[0].event_name == "plugin.registration.start"
        assert reg_events[1].event_name == "plugin.registration.end"
        assert "duration_ms" in reg_events[1].payload


class TestPluginInstrumentationFaultTolerance:
    """Tests that instrumentation failures don't prevent plugin loading."""

    @patch("functualize._plugins.loader.entry_points")
    def test_plugin_loads_even_if_event_bus_emit_raises(
        self, mock_entry_points: Any
    ) -> None:
        """Plugin loading continues even if event_bus.emit raises."""
        plugin = _make_plugin(name="resilient-plugin")
        ep = _make_entry_point("resilient-ep", plugin)
        mock_entry_points.return_value = [ep]

        app = MagicMock()
        # event_bus.emit always raises
        app.event_bus.emit.side_effect = RuntimeError("event bus broken")
        app.plugin_config_registry = MagicMock()
        app.plugin_config_registry.has.return_value = False

        loader = PluginLoader("functualize.plugins")
        loader.load_all(app, event_bus=app.event_bus)

        # Plugin should still be registered despite event_bus failures
        assert "resilient-plugin" in loader.loaded_plugins

    @patch("functualize._plugins.loader.entry_points")
    def test_plugin_loads_even_if_event_bus_property_raises(
        self, mock_entry_points: Any
    ) -> None:
        """Plugin loading continues even if app.event_bus raises AttributeError."""
        plugin = _make_plugin(name="robust-plugin")
        ep = _make_entry_point("robust-ep", plugin)
        mock_entry_points.return_value = [ep]

        app = MagicMock()
        # event_bus property raises
        type(app).event_bus = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("no event bus"))
        )
        app.plugin_config_registry = MagicMock()
        app.plugin_config_registry.has.return_value = False

        loader = PluginLoader("functualize.plugins")
        # Pass event_bus=None to simulate unavailable event_bus.
        # The property raises on access, so we test that load_all handles None gracefully.
        loader.load_all(app, event_bus=None)

        # Plugin should still be registered
        assert "robust-plugin" in loader.loaded_plugins
