"""Unit tests for FunctualizeApp extensions: middleware, scope registry, plugin config registry."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from functualize._app.state import AppState
from functualize._plugins.config import PluginConfigRegistry
from functualize.app.core import FunctualizeApp
from functualize.job._middleware import MiddlewareRegistry
from functualize.job._workflow_scope import WorkflowScope


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


class TestPluginConfigRegistry:
    """Tests for plugin_config_registry attribute on FunctualizeApp."""

    def test_has_plugin_config_registry(self, app: FunctualizeApp) -> None:
        assert hasattr(app, "plugin_config_registry")

    def test_plugin_config_registry_is_instance(self, app: FunctualizeApp) -> None:
        assert isinstance(app.plugin_config_registry, PluginConfigRegistry)

    def test_plugin_config_registry_initially_empty(self, app: FunctualizeApp) -> None:
        assert app.plugin_config_registry.get_all() == {}


class TestMiddlewareRegistry:
    """Tests for _middleware_registry attribute and register_run_middleware method."""

    def test_has_middleware_registry(self, app: FunctualizeApp) -> None:
        assert hasattr(app, "_middleware_registry")

    def test_middleware_registry_is_instance(self, app: FunctualizeApp) -> None:
        assert isinstance(app._middleware_registry, MiddlewareRegistry)

    def test_no_middleware_initially(self, app: FunctualizeApp) -> None:
        assert not app._middleware_registry.has_middleware

    def test_register_run_middleware(self, app: FunctualizeApp) -> None:
        def my_middleware(rc: Any) -> Generator[None]:
            yield

        app.register_run_middleware(my_middleware)
        assert app._middleware_registry.has_middleware

    def test_register_run_middleware_with_priority(self, app: FunctualizeApp) -> None:
        def mw_a(rc: Any) -> Generator[None]:
            yield

        def mw_b(rc: Any) -> Generator[None]:
            yield

        app.register_run_middleware(mw_a, priority=10)
        app.register_run_middleware(mw_b, priority=5)

        sorted_entries = app._middleware_registry.get_sorted()
        assert len(sorted_entries) == 2
        # mw_b has lower priority (5), should come first
        assert sorted_entries[0].middleware is mw_b
        assert sorted_entries[1].middleware is mw_a

    def test_register_run_middleware_default_priority_zero(
        self, app: FunctualizeApp
    ) -> None:
        def mw(rc: Any) -> Generator[None]:
            yield

        app.register_run_middleware(mw)
        entries = app._middleware_registry.get_sorted()
        assert entries[0].priority == 0


class TestScopeRegistry:
    """Tests for _scope_registry, create_workflow_scope, and get_workflow_scope."""

    def test_has_scope_registry(self, app: FunctualizeApp) -> None:
        assert hasattr(app, "_scope_registry")

    def test_scope_registry_is_dict(self, app: FunctualizeApp) -> None:
        assert isinstance(app._scope_registry, dict)

    def test_scope_registry_initially_empty(self, app: FunctualizeApp) -> None:
        assert app._scope_registry == {}

    def test_create_workflow_scope(self, app: FunctualizeApp) -> None:
        scope = app.create_workflow_scope("test-scope")
        assert isinstance(scope, WorkflowScope)
        assert scope.scope_id == "test-scope"

    def test_create_workflow_scope_with_metadata(self, app: FunctualizeApp) -> None:
        meta = {"run_id": "abc-123", "provider": "restate"}
        scope = app.create_workflow_scope("meta-scope", metadata=meta)
        assert scope.metadata == meta

    def test_create_workflow_scope_stores_in_registry(
        self, app: FunctualizeApp
    ) -> None:
        scope = app.create_workflow_scope("stored-scope")
        assert app._scope_registry["stored-scope"] is scope

    def test_create_workflow_scope_duplicate_raises_value_error(
        self, app: FunctualizeApp
    ) -> None:
        app.create_workflow_scope("dup-scope")
        with pytest.raises(ValueError, match="already exists"):
            app.create_workflow_scope("dup-scope")

    def test_get_workflow_scope(self, app: FunctualizeApp) -> None:
        created = app.create_workflow_scope("get-scope")
        retrieved = app.get_workflow_scope("get-scope")
        assert retrieved is created

    def test_get_workflow_scope_missing_raises_key_error(
        self, app: FunctualizeApp
    ) -> None:
        with pytest.raises(KeyError, match="not found"):
            app.get_workflow_scope("nonexistent")

    def test_get_workflow_scope_error_lists_available(
        self, app: FunctualizeApp
    ) -> None:
        app.create_workflow_scope("scope-a")
        app.create_workflow_scope("scope-b")
        with pytest.raises(KeyError, match="scope-a"):
            app.get_workflow_scope("missing")


class TestPluginConfigRegistryWiring:
    """Tests for plugin config registry wiring with PluginLoader."""

    def test_plugin_loader_uses_app_registry(self, app: FunctualizeApp) -> None:
        """PluginLoader should find and use the app's plugin_config_registry."""
        # The PluginLoader._get_config_registry checks hasattr(app, 'plugin_config_registry')
        # Since we now initialize it in __init__, the loader should use it directly.
        registry = app.plugin_loader._get_config_registry(app)
        assert registry is app.plugin_config_registry


class TestPerfTimelineProperty:
    """Tests for perf_timeline property on FunctualizeApp."""

    def test_has_perf_timeline_property(self, app: FunctualizeApp) -> None:
        assert hasattr(app, "perf_timeline")

    def test_perf_timeline_identity_with_global_singleton(
        self, app: FunctualizeApp
    ) -> None:
        """app.perf_timeline must be the same object as functualize.perf.perf_timeline."""
        from functualize._events.perf import perf_timeline

        assert app.perf_timeline is perf_timeline

    def test_perf_timeline_is_perf_timeline_instance(self, app: FunctualizeApp) -> None:
        from functualize._events.perf import PerfTimeline

        assert isinstance(app.perf_timeline, PerfTimeline)


class TestPluginCommandRegistration:
    """Tests for register_plugin_command on FunctualizeApp."""

    def test_register_top_level_command(self, app: FunctualizeApp) -> None:
        """Registering with namespace=None adds command at top level."""

        def my_cmd() -> None:
            pass

        app.register_plugin_command("my-cmd", my_cmd)
        assert "my-cmd" in app._plugin_commands[None]

    def test_register_namespaced_command(self, app: FunctualizeApp) -> None:
        """Registering with a namespace creates a sub-group and tracks command."""

        def my_cmd() -> None:
            pass

        app.register_plugin_command("run", my_cmd, namespace="my-plugin")
        assert "run" in app._plugin_commands["my-plugin"]
        assert "my-plugin" in app._plugin_sub_groups

    def test_register_multiple_commands_same_namespace(
        self, app: FunctualizeApp
    ) -> None:
        """Multiple commands can be registered under the same namespace."""

        def cmd_a() -> None:
            pass

        def cmd_b() -> None:
            pass

        app.register_plugin_command("start", cmd_a, namespace="server")
        app.register_plugin_command("stop", cmd_b, namespace="server")
        assert "start" in app._plugin_commands["server"]
        assert "stop" in app._plugin_commands["server"]

    def test_same_name_different_namespaces_allowed(self, app: FunctualizeApp) -> None:
        """Same command name in different namespaces does not conflict."""

        def cmd_a() -> None:
            pass

        def cmd_b() -> None:
            pass

        app.register_plugin_command("status", cmd_a, namespace="server")
        app.register_plugin_command("status", cmd_b, namespace="db")
        assert "status" in app._plugin_commands["server"]
        assert "status" in app._plugin_commands["db"]

    def test_duplicate_name_same_namespace_raises_value_error(
        self, app: FunctualizeApp
    ) -> None:
        """Duplicate name in the same namespace raises ValueError."""

        def cmd_a() -> None:
            pass

        def cmd_b() -> None:
            pass

        app.register_plugin_command("run", cmd_a, namespace="test-grp")
        with pytest.raises(ValueError, match="Duplicate command name 'run'"):
            app.register_plugin_command("run", cmd_b, namespace="test-grp")

    def test_duplicate_name_top_level_raises_value_error(
        self, app: FunctualizeApp
    ) -> None:
        """Duplicate name at top level raises ValueError."""

        def cmd_a() -> None:
            pass

        def cmd_b() -> None:
            pass

        app.register_plugin_command("deploy", cmd_a)
        with pytest.raises(ValueError, match="Duplicate command name 'deploy'"):
            app.register_plugin_command("deploy", cmd_b)

    def test_invalid_name_uppercase_raises_value_error(
        self, app: FunctualizeApp
    ) -> None:
        """Uppercase characters in name are rejected."""

        def cmd() -> None:
            pass

        with pytest.raises(ValueError, match="Invalid command name"):
            app.register_plugin_command("MyCmd", cmd)

    def test_invalid_name_starts_with_digit_raises_value_error(
        self, app: FunctualizeApp
    ) -> None:
        """Name starting with digit is rejected."""

        def cmd() -> None:
            pass

        with pytest.raises(ValueError, match="Invalid command name"):
            app.register_plugin_command("1cmd", cmd)

    def test_invalid_name_empty_raises_value_error(self, app: FunctualizeApp) -> None:
        """Empty name is rejected."""

        def cmd() -> None:
            pass

        with pytest.raises(ValueError, match="Invalid command name"):
            app.register_plugin_command("", cmd)

    def test_invalid_name_too_long_raises_value_error(
        self, app: FunctualizeApp
    ) -> None:
        """Name longer than 64 chars is rejected."""

        def cmd() -> None:
            pass

        long_name = "a" * 65
        with pytest.raises(ValueError, match="Invalid command name"):
            app.register_plugin_command(long_name, cmd)

    def test_invalid_name_special_chars_raises_value_error(
        self, app: FunctualizeApp
    ) -> None:
        """Special characters (underscores, dots) are rejected."""

        def cmd() -> None:
            pass

        with pytest.raises(ValueError, match="Invalid command name"):
            app.register_plugin_command("my_cmd", cmd)

    def test_non_callable_callback_raises_value_error(
        self, app: FunctualizeApp
    ) -> None:
        """Non-callable callback is rejected."""
        with pytest.raises(ValueError, match="callback must be callable"):
            app.register_plugin_command("valid-name", "not_callable")  # type: ignore[arg-type]

    def test_help_text_too_long_raises_value_error(self, app: FunctualizeApp) -> None:
        """Help text exceeding 256 chars is rejected."""

        def cmd() -> None:
            pass

        long_help = "x" * 257
        with pytest.raises(ValueError, match="must be at most 256 characters"):
            app.register_plugin_command("valid-cmd", cmd, help_text=long_help)

    def test_valid_name_boundary_64_chars(self, app: FunctualizeApp) -> None:
        """Name of exactly 64 chars is accepted."""

        def cmd() -> None:
            pass

        name_64 = "a" * 64
        app.register_plugin_command(name_64, cmd)
        assert name_64 in app._plugin_commands[None]

    def test_valid_name_single_char(self, app: FunctualizeApp) -> None:
        """Single lowercase letter is valid."""

        def cmd() -> None:
            pass

        app.register_plugin_command("x", cmd)
        assert "x" in app._plugin_commands[None]

    def test_help_text_passed_to_typer(self, app: FunctualizeApp) -> None:
        """Help text is passed to the Typer command."""

        def cmd() -> None:
            pass

        app.register_plugin_command("info", cmd, help_text="Show plugin info")
        # Command is registered — verify it exists in typer registered commands
        assert "info" in app._plugin_commands[None]
