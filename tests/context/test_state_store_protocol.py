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
from tests.context.conftest import new_state_store


class TestStateStoreProtocolCompliance:
    """Verify the existing StateStore satisfies StateStoreProtocol."""

    def test_state_store_is_instance_of_protocol(self) -> None:
        """StateStore satisfies StateStoreProtocol via isinstance check.

        **Validates: Requirements 7.1, 7.6**
        """
        store = new_state_store()
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
        store = new_state_store()
        # Verify all protocol methods exist and are callable
        assert callable(store.get)
        assert callable(store.set)
        assert callable(store.delete)
        assert callable(store.keys)
        assert callable(store.to_dict)
        assert callable(store.clear)

    def test_state_store_delete_method(self) -> None:
        """StateStore.delete removes a key, no-op for missing keys.

        **Validates: Requirements 7.1**
        """
        store = new_state_store()
        store.set("key", "value")
        assert store.get("key") == "value"
        store.delete("key")
        assert store.get("key") is None
        # No-op for missing key
        store.delete("nonexistent")

    def test_a_job_namespace_is_a_key_prefix_and_nothing_more(self) -> None:
        """The convention that replaced `get_job_state` (T12).

        A namespace was once two protocol methods — `get_job_state("job_a",
        "counter")` and `list_job_namespaces()`. Both were deleted: a framework
        namespace is a second concept for what a string prefix already does
        (ADR-021 §B), and the default store's implementation was literally
        `get(f"{job_name}.{key}")`.

        What replaces them is what a user writes by hand, asserted here so the
        convention stays real rather than becoming folklore: a dotted key, and
        a glob to enumerate one namespace.
        """
        store = new_state_store()
        store.set("job_a.counter", 42)
        store.set("job_a.rows", 7)
        store.set("job_b.counter", 1)

        assert store.get("job_a.counter") == 42
        assert store.get("job_a.missing", "default") == "default"
        assert store.get("nonexistent_job.key") is None
        assert sorted(store.keys()) == [
            "job_a.counter",
            "job_a.rows",
            "job_b.counter",
        ]

    def test_protocol_default_get_behavior(self) -> None:
        """StateStore.get with default value works per protocol contract.

        **Validates: Requirements 7.1, 7.6**
        """
        store = new_state_store()
        store.set("exists", "hello")
        assert store.get("exists") == "hello"
        assert store.get("missing") is None
        assert store.get("missing", "fallback") == "fallback"


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
