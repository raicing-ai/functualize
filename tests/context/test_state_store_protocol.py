"""Tests verifying StateStoreProtocol compliance and PluginWithShutdown protocol.

Validates:
- Requirements 7.1: StateStoreProtocol is defined as runtime-checkable
- Requirements 7.6: Existing in-memory StateStore satisfies the protocol
- Requirements 11.1: PluginWithShutdown protocol is defined as runtime-checkable
"""

from __future__ import annotations

from typing import Any

from functualize._types.protocols import PluginWithShutdown
from functualize.job._protocols import StateStoreProtocol
from functualize.job._state_store import StateStore


class TestStateStoreProtocolCompliance:
    """Verify the existing StateStore satisfies StateStoreProtocol."""

    def test_state_store_is_instance_of_protocol(self) -> None:
        """StateStore satisfies StateStoreProtocol via isinstance check.

        **Validates: Requirements 7.1, 7.6**
        """
        store = StateStore()
        assert isinstance(store, StateStoreProtocol)

    def test_protocol_is_runtime_checkable(self) -> None:
        """StateStoreProtocol can be used with isinstance at runtime.

        **Validates: Requirements 7.1**
        """

        # A class missing methods should NOT satisfy the protocol
        class IncompleteStore:
            def get(self, key: str, default: Any = None) -> Any:
                return None

            def set(self, key: str, value: Any) -> None:
                pass

        incomplete = IncompleteStore()
        assert not isinstance(incomplete, StateStoreProtocol)

    def test_state_store_has_all_protocol_methods(self) -> None:
        """StateStore implements all methods defined in StateStoreProtocol.

        **Validates: Requirements 7.6**
        """
        store = StateStore()
        # Verify all protocol methods exist and are callable
        assert callable(store.get)
        assert callable(store.set)
        assert callable(store.delete)
        assert callable(store.keys)
        assert callable(store.to_dict)
        assert callable(store.clear)
        assert callable(store.get_job_state)
        assert callable(store.list_job_namespaces)

    def test_state_store_delete_method(self) -> None:
        """StateStore.delete removes a key, no-op for missing keys.

        **Validates: Requirements 7.1**
        """
        store = StateStore()
        store.set("key", "value")
        assert store.get("key") == "value"
        store.delete("key")
        assert store.get("key") is None
        # No-op for missing key
        store.delete("nonexistent")

    def test_state_store_get_job_state(self) -> None:
        """StateStore.get_job_state reads from job namespaces.

        **Validates: Requirements 7.1**
        """
        store = StateStore()
        store._set_job_state("job_a", "counter", 42)
        assert store.get_job_state("job_a", "counter") == 42
        assert store.get_job_state("job_a", "missing", "default") == "default"
        assert store.get_job_state("nonexistent_job", "key") is None

    def test_state_store_list_job_namespaces(self) -> None:
        """StateStore.list_job_namespaces returns job names with state.

        **Validates: Requirements 7.1**
        """
        store = StateStore()
        assert store.list_job_namespaces() == []
        store._set_job_state("job_a", "key", "value")
        store._set_job_state("job_b", "key", "value")
        namespaces = store.list_job_namespaces()
        assert sorted(namespaces) == ["job_a", "job_b"]

    def test_protocol_default_get_behavior(self) -> None:
        """StateStore.get with default value works per protocol contract.

        **Validates: Requirements 7.1, 7.6**
        """
        store = StateStore()
        store.set("exists", "hello")
        assert store.get("exists") == "hello"
        assert store.get("missing") is None
        assert store.get("missing", "fallback") == "fallback"

    def test_backward_compatible_typed_get(self) -> None:
        """StateStore.get still supports typed get for backward compatibility.

        **Validates: Requirements 7.6**
        """
        store = StateStore()
        store.set("name", "alice")
        # Old-style typed get still works
        assert store.get("name", str) == "alice"
        assert store.get("missing_key", str) is None


class TestPluginWithShutdownProtocol:
    """Verify PluginWithShutdown protocol is correctly defined."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """PluginWithShutdown can be used with isinstance at runtime.

        **Validates: Requirements 11.1**
        """

        class ShutdownPlugin:
            def on_shutdown(self, app: Any) -> None:
                pass

        plugin = ShutdownPlugin()
        assert isinstance(plugin, PluginWithShutdown)

    def test_object_without_on_shutdown_fails_check(self) -> None:
        """Objects without on_shutdown don't satisfy the protocol.

        **Validates: Requirements 11.1**
        """

        class NoShutdownPlugin:
            def some_other_method(self) -> None:
                pass

        plugin = NoShutdownPlugin()
        assert not isinstance(plugin, PluginWithShutdown)

    def test_plugin_with_shutdown_called_with_app(self) -> None:
        """PluginWithShutdown.on_shutdown accepts app argument.

        **Validates: Requirements 11.1**
        """
        calls: list[Any] = []

        class MyPlugin:
            def on_shutdown(self, app: Any) -> None:
                calls.append(app)

        plugin = MyPlugin()
        assert isinstance(plugin, PluginWithShutdown)
        plugin.on_shutdown("mock_app")
        assert calls == ["mock_app"]
