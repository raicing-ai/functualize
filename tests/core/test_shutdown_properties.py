"""Property-based tests for plugin shutdown lifecycle (Property 17).

Property 17: Plugin shutdown invoked in reverse loading order with exception isolation.

For any sequence of N plugins loaded that satisfy PluginWithShutdown,
on_shutdown(app) is invoked in reverse loading order. If any plugin's
on_shutdown raises, the remaining plugins still receive their on_shutdown call.

**Validates: Requirements 11.3, 11.4**
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._types.protocols import PluginWithShutdown
from functualize.app.core import FunctualizeApp

# --- Helpers ---


class ShutdownPlugin:
    """A real plugin satisfying PluginWithShutdown protocol."""

    def __init__(
        self, name: str, should_raise: bool = False, error: Exception | None = None
    ):
        self.name = name
        self.version = "1.0.0"
        self.description = f"Test plugin {name}"
        self._should_raise = should_raise
        self._error = error or RuntimeError(f"{name} shutdown failed")
        self.shutdown_called = False
        self.shutdown_call_order: list[str] | None = None

    def on_shutdown(self, app: Any) -> None:
        self.shutdown_called = True
        if self.shutdown_call_order is not None:
            self.shutdown_call_order.append(self.name)
        if self._should_raise:
            raise self._error


# --- Strategies ---

# Strategy for plugin names (unique identifiers)
plugin_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=20,
)

# Strategy for whether a plugin should raise during shutdown
should_raise_st = st.booleans()

# Strategy for generating a plugin spec (name + whether it raises)
plugin_spec_st = st.tuples(plugin_name_st, should_raise_st)

# Strategy for sequences of plugin specs with unique names
plugin_sequence_st = st.lists(
    plugin_spec_st,
    min_size=1,
    max_size=15,
    unique_by=lambda spec: spec[0],
)


class TestShutdownReverseOrderProperty:
    """Property 17: Plugin shutdown invoked in reverse loading order with exception isolation.

    **Validates: Requirements 11.3, 11.4**
    """

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        plugin_specs=st.lists(
            plugin_name_st,
            min_size=2,
            max_size=15,
            unique=True,
        ),
    )
    def test_shutdown_invoked_in_reverse_loading_order(
        self,
        plugin_specs: list[str],
    ):
        """**Validates: Requirements 11.3**

        For any sequence of N plugins loaded in order, on_shutdown is
        invoked in reverse loading order (last loaded = first shutdown).
        """
        app = FunctualizeApp(name="testapp")
        call_order: list[str] = []

        # Create plugins and register them in loading order
        plugins = []
        for name in plugin_specs:
            plugin = ShutdownPlugin(name)
            plugin.shutdown_call_order = call_order
            plugins.append(plugin)
            app.plugin_loader._loaded_instances.append(plugin)

        app._shutdown_plugins()

        # Verify reverse loading order
        expected_order = list(reversed(plugin_specs))
        assert call_order == expected_order

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        plugin_specs=plugin_sequence_st,
    )
    def test_exception_isolation_all_plugins_receive_shutdown(
        self,
        plugin_specs: list[tuple[str, bool]],
    ):
        """**Validates: Requirements 11.3, 11.4**

        For any sequence of N plugins where some raise exceptions during shutdown,
        all plugins still receive their on_shutdown call regardless of earlier failures.
        """
        app = FunctualizeApp(name="testapp")
        call_order: list[str] = []

        # Create plugins and register them
        plugins = []
        for name, should_raise in plugin_specs:
            plugin = ShutdownPlugin(name, should_raise=should_raise)
            plugin.shutdown_call_order = call_order
            plugins.append(plugin)
            app.plugin_loader._loaded_instances.append(plugin)

        app._shutdown_plugins()

        # ALL plugins with shutdown should be called, regardless of exceptions
        expected_names = [name for name, _ in reversed(plugin_specs)]
        assert call_order == expected_names

        # Verify each plugin's shutdown_called flag is set
        for plugin in plugins:
            assert plugin.shutdown_called, (
                f"Plugin '{plugin.name}' did not receive on_shutdown call"
            )

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        plugin_specs=st.lists(
            plugin_name_st,
            min_size=1,
            max_size=10,
            unique=True,
        ),
        raising_indices=st.data(),
    )
    def test_order_preserved_despite_exceptions(
        self,
        plugin_specs: list[str],
        raising_indices: st.DataObject,
    ):
        """**Validates: Requirements 11.3, 11.4**

        For any subset of plugins that raise exceptions, the invocation order
        remains strictly reverse loading order, and no plugins are skipped.
        """
        # Determine which plugins will raise (random subset)
        raises_mask = raising_indices.draw(
            st.lists(
                st.booleans(),
                min_size=len(plugin_specs),
                max_size=len(plugin_specs),
            )
        )

        app = FunctualizeApp(name="testapp")
        call_order: list[str] = []

        plugins = []
        for i, name in enumerate(plugin_specs):
            plugin = ShutdownPlugin(name, should_raise=raises_mask[i])
            plugin.shutdown_call_order = call_order
            plugins.append(plugin)
            app.plugin_loader._loaded_instances.append(plugin)

        app._shutdown_plugins()

        # Shutdown must happen in reverse order regardless of which ones raise
        expected_order = list(reversed(plugin_specs))
        assert call_order == expected_order

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        non_shutdown_count=st.integers(min_value=0, max_value=5),
        shutdown_names=st.lists(
            plugin_name_st,
            min_size=1,
            max_size=10,
            unique=True,
        ),
    )
    def test_only_plugins_with_shutdown_protocol_are_invoked(
        self,
        non_shutdown_count: int,
        shutdown_names: list[str],
    ):
        """**Validates: Requirements 11.3**

        For any mix of plugins where some satisfy PluginWithShutdown and some don't,
        only those satisfying the protocol receive on_shutdown calls, and they are
        invoked in reverse loading order among themselves.
        """
        app = FunctualizeApp(name="testapp")
        call_order: list[str] = []

        # Add non-shutdown plugins (no on_shutdown method)
        for i in range(non_shutdown_count):
            mock = MagicMock()
            mock.name = f"no-shutdown-{i}"
            mock.version = "1.0.0"
            # Remove on_shutdown to make it not satisfy the protocol
            del mock.on_shutdown
            app.plugin_loader._loaded_instances.append(mock)

        # Add plugins with shutdown (interleaved after non-shutdown ones)
        shutdown_plugins = []
        for name in shutdown_names:
            plugin = ShutdownPlugin(name)
            plugin.shutdown_call_order = call_order
            shutdown_plugins.append(plugin)
            app.plugin_loader._loaded_instances.append(plugin)

        app._shutdown_plugins()

        # Only shutdown-capable plugins should be called, in reverse loading order
        expected_order = list(reversed(shutdown_names))
        assert call_order == expected_order

        # Verify protocol check works
        for plugin in shutdown_plugins:
            assert isinstance(plugin, PluginWithShutdown)
