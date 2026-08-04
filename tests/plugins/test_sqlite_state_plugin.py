"""Tests for the SQLiteStatePlugin (_plugin.py) — DI registration and scope lifecycle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from functualize_state import ExecutionStore, StateBackend
from functualize_state_sqlite._plugin import SQLiteStatePlugin

from functualize._events.hooks import HookEvent


class MockHookRegistry:
    """Minimal mock hook registry that captures registered hooks."""

    def __init__(self) -> None:
        self._global_hooks: dict[str, list] = {}

    def register_global(self, event: str, handler) -> None:
        self._global_hooks.setdefault(event, []).append(handler)


class MockApp:
    """Minimal mock of FunctualizeApp for plugin testing."""

    def __init__(self, db_path: str) -> None:
        self.hook_registry = MockHookRegistry()
        self._provided: dict[type, object] = {}
        self._db_path = db_path

    def provide(self, type_: type, instance: object, qualifier=None) -> None:
        self._provided[type_] = instance

    def resolve_model(self, section: str, model_class: type):
        """Return a config model with our test db_path."""

        class FakeConfig:
            db_path = self._db_path

        return FakeConfig()


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> str:
    """Provide a temporary database path as a string."""
    return str(tmp_path / "test_state.db")


@pytest.fixture
def mock_app(tmp_db_path: str) -> MockApp:
    """Create a mock app pointing to a temp database."""
    return MockApp(tmp_db_path)


@pytest.fixture
def plugin() -> SQLiteStatePlugin:
    """Create a fresh SQLiteStatePlugin instance."""
    return SQLiteStatePlugin()


@pytest.fixture
def registered_plugin(
    plugin: SQLiteStatePlugin, mock_app: MockApp
) -> SQLiteStatePlugin:
    """Plugin that has been registered with the app (hooks installed)."""
    plugin(mock_app)
    return plugin


@pytest.fixture
def booted_plugin(
    registered_plugin: SQLiteStatePlugin, mock_app: MockApp
) -> SQLiteStatePlugin:
    """Plugin that has been booted (APP_READY fired)."""
    # Fire APP_READY hooks
    for handler in mock_app.hook_registry._global_hooks.get(HookEvent.APP_READY, []):
        handler(mock_app)
    return registered_plugin


class TestPluginRegistration:
    """Test that the plugin registers lifecycle hooks correctly."""

    def test_registers_app_ready_hook(
        self, registered_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """Plugin registers an APP_READY hook."""
        assert HookEvent.APP_READY in mock_app.hook_registry._global_hooks
        assert len(mock_app.hook_registry._global_hooks[HookEvent.APP_READY]) == 1

    def test_registers_on_scope_created_hook(
        self, registered_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """Plugin registers an ON_SCOPE_CREATED hook."""
        assert HookEvent.ON_SCOPE_CREATED in mock_app.hook_registry._global_hooks
        assert (
            len(mock_app.hook_registry._global_hooks[HookEvent.ON_SCOPE_CREATED]) == 1
        )

    def test_plugin_metadata(self, plugin: SQLiteStatePlugin):
        """Plugin has expected metadata attributes."""
        assert plugin.name == "sqlite-state"
        assert plugin.version == "0.1.0"
        assert plugin.description is not None


class TestDIRegistration:
    """Test that APP_READY registers StateBackend and ExecutionStore via app.provide()."""

    def test_provides_state_backend(
        self, booted_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """After APP_READY, StateBackend is registered in DI."""
        assert StateBackend in mock_app._provided
        assert isinstance(mock_app._provided[StateBackend], StateBackend)

    def test_provides_execution_store(
        self, booted_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """After APP_READY, ExecutionStore is registered in DI."""
        assert ExecutionStore in mock_app._provided
        assert isinstance(mock_app._provided[ExecutionStore], ExecutionStore)

    def test_backend_is_sqlite(
        self, booted_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """The registered StateBackend is an SQLiteStateBackend."""
        from functualize_state_sqlite._backend import SQLiteStateBackend

        assert isinstance(mock_app._provided[StateBackend], SQLiteStateBackend)

    def test_execution_store_is_sqlite(
        self, booted_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """The registered ExecutionStore is an SQLiteExecutionStore."""
        from functualize_state_sqlite._execution_store import SQLiteExecutionStore

        assert isinstance(mock_app._provided[ExecutionStore], SQLiteExecutionStore)

    def test_backend_and_store_share_db_path(
        self, booted_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """StateBackend and ExecutionStore share the same database path."""
        backend = mock_app._provided[StateBackend]
        store = mock_app._provided[ExecutionStore]
        assert backend.db_path == store.db_path

    def test_plugin_backend_property(self, booted_plugin: SQLiteStatePlugin):
        """Plugin exposes backend property after boot."""
        assert booted_plugin.backend is not None

    def test_plugin_execution_store_property(self, booted_plugin: SQLiteStatePlugin):
        """Plugin exposes execution_store property after boot."""
        assert booted_plugin.execution_store is not None


class TestScopeCreated:
    """Test ON_SCOPE_CREATED replaces scope state with SQLite-backed store."""

    def test_scope_state_store_replaced(
        self, booted_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """ON_SCOPE_CREATED replaces the scope's state store."""
        scope = MagicMock()
        scope.scope_id = "test-scope-1"

        # Fire ON_SCOPE_CREATED
        for handler in mock_app.hook_registry._global_hooks.get(
            HookEvent.ON_SCOPE_CREATED, []
        ):
            handler(scope)

        scope.replace_state_store.assert_called_once()

    def test_scope_gets_sqlite_state_store(
        self, booted_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """The replacement store is a SQLiteStateStore."""
        from functualize_state_sqlite.state_store import SQLiteStateStore

        scope = MagicMock()
        scope.scope_id = "test-scope-2"

        for handler in mock_app.hook_registry._global_hooks.get(
            HookEvent.ON_SCOPE_CREATED, []
        ):
            handler(scope)

        store_arg = scope.replace_state_store.call_args[0][0]
        assert isinstance(store_arg, SQLiteStateStore)

    def test_no_replacement_before_boot(
        self, registered_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """ON_SCOPE_CREATED does nothing if backend is not initialized."""
        scope = MagicMock()
        scope.scope_id = "test-scope-3"

        for handler in mock_app.hook_registry._global_hooks.get(
            HookEvent.ON_SCOPE_CREATED, []
        ):
            handler(scope)

        scope.replace_state_store.assert_not_called()


class TestShutdown:
    """Test plugin shutdown behavior."""

    def test_shutdown_closes_backend(
        self, booted_plugin: SQLiteStatePlugin, mock_app: MockApp
    ):
        """on_shutdown closes the backend and execution store."""
        assert booted_plugin.backend is not None
        assert booted_plugin.execution_store is not None

        booted_plugin.on_shutdown(mock_app)

        assert booted_plugin.backend is None
        assert booted_plugin.execution_store is None

    def test_shutdown_safe_when_not_initialized(self, plugin: SQLiteStatePlugin):
        """on_shutdown is safe when nothing was initialized."""
        plugin.on_shutdown(MagicMock())  # Should NOT raise
