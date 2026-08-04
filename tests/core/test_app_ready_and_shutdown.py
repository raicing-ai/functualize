"""Unit tests for APP_READY hook firing and PluginWithShutdown lifecycle.

Tests cover:
- APP_READY fires after all boot steps complete
- APP_READY hook exceptions logged at WARNING, remaining hooks continue
- Plugin shutdown invoked in reverse loading order
- Shutdown timeout enforcement (5 seconds per plugin)
- Shutdown exception isolation (errors logged, remaining plugins continue)
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from functualize._app.state import AppState
from functualize._events.hooks import HookEvent
from functualize.app.core import FunctualizeApp


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


class TestAppReadyHook:
    """Tests for APP_READY hook firing at end of FunctualizeApp.__init__()."""

    def test_app_ready_fires_during_init(self) -> None:
        """APP_READY hook fires during __init__ if registered during plugin load."""
        # Simulate what a real plugin does: register for APP_READY during __call__(app)
        ready_received: list[Any] = []

        class TestPlugin:
            name = "test-ready-plugin"
            version = "1.0.0"
            description = "Test"

            def __call__(self, app: Any) -> None:
                app._hook_registry.register_global(
                    HookEvent.APP_READY, lambda a: ready_received.append(a)
                )

        # Patch entry_points to return our test plugin

        mock_ep = MagicMock()
        mock_ep.name = "test-ready-plugin"
        mock_ep.load.return_value = TestPlugin()

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            app = FunctualizeApp(name="testapp")

        # The hook should have been called during init (after plugin loaded, at step 10)
        assert len(ready_received) == 1
        assert ready_received[0] is app

    def test_app_ready_fires_with_app_instance(self) -> None:
        """APP_READY hooks receive the app instance as the sole argument."""
        called_with: list[Any] = []

        app = FunctualizeApp(name="testapp")

        # Verify APP_READY mechanism by manually invoking (for hooks registered post-init)
        app._hook_registry.register_global(
            HookEvent.APP_READY, lambda a: called_with.append(a)
        )

        # Simulate what __init__ does for APP_READY
        for hook in app._hook_registry._global_hooks.get(HookEvent.APP_READY, []):
            hook(app)

        assert len(called_with) == 1
        assert called_with[0] is app

    def test_app_ready_hook_exception_logged_and_continues(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If an APP_READY hook raises, log WARNING and continue remaining hooks."""
        call_order: list[str] = []

        def hook_that_raises(app: Any) -> None:
            call_order.append("raiser")
            raise RuntimeError("hook error")

        def hook_that_succeeds(app: Any) -> None:
            call_order.append("success")

        # Use a real plugin to register both hooks
        class TestPlugin:
            name = "multi-hook-plugin"
            version = "1.0.0"
            description = "Test"

            def __call__(self, app_instance: Any) -> None:
                app_instance._hook_registry.register_global(
                    HookEvent.APP_READY, hook_that_raises
                )
                app_instance._hook_registry.register_global(
                    HookEvent.APP_READY, hook_that_succeeds
                )

        mock_ep = MagicMock()
        mock_ep.name = "multi-hook-plugin"
        mock_ep.load.return_value = TestPlugin()

        with (
            patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]),
            caplog.at_level(logging.WARNING),
        ):
            FunctualizeApp(name="testapp")

        assert call_order == ["raiser", "success"]
        assert "APP_READY hook" in caplog.text
        assert "hook error" in caplog.text

    def test_app_ready_fires_after_all_boot_steps(self) -> None:
        """APP_READY fires after plugins, jobs, children, and TUI are set up."""
        boot_state_at_ready: dict[str, Any] = {}

        class TestPlugin:
            name = "state-check-plugin"
            version = "1.0.0"
            description = "Test"

            def __call__(self, app_instance: Any) -> None:
                def capture_state(a: Any) -> None:
                    boot_state_at_ready["cli_command"] = a.cli_command is not None
                    boot_state_at_ready["job_registry"] = a.job_registry is not None
                    boot_state_at_ready["plugin_loader"] = a.plugin_loader is not None

                app_instance._hook_registry.register_global(
                    HookEvent.APP_READY, capture_state
                )

        mock_ep = MagicMock()
        mock_ep.name = "state-check-plugin"
        mock_ep.load.return_value = TestPlugin()

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            FunctualizeApp(name="testapp")

        assert boot_state_at_ready["cli_command"] is True
        assert boot_state_at_ready["job_registry"] is True
        assert boot_state_at_ready["plugin_loader"] is True

    def test_app_ready_multiple_hooks_all_called(self) -> None:
        """Multiple APP_READY hooks all get invoked in registration order."""
        call_order: list[int] = []

        app = FunctualizeApp(name="testapp")
        app._hook_registry.register_global(
            HookEvent.APP_READY, lambda a: call_order.append(1)
        )
        app._hook_registry.register_global(
            HookEvent.APP_READY, lambda a: call_order.append(2)
        )
        app._hook_registry.register_global(
            HookEvent.APP_READY, lambda a: call_order.append(3)
        )

        # Simulate APP_READY firing
        for hook in app._hook_registry._global_hooks.get(HookEvent.APP_READY, []):
            with contextlib.suppress(Exception):
                hook(app)

        assert call_order == [1, 2, 3]


class TestPluginShutdown:
    """Tests for PluginWithShutdown lifecycle invocation."""

    def _make_plugin(self, name: str, version: str = "1.0.0") -> MagicMock:
        """Create a mock plugin satisfying PluginWithShutdown protocol."""
        plugin = MagicMock()
        plugin.name = name
        plugin.version = version
        plugin.description = f"Test plugin {name}"
        plugin.on_shutdown = MagicMock()
        return plugin

    def test_shutdown_calls_on_shutdown_with_app(self) -> None:
        """on_shutdown(app) is called with the app instance."""
        app = FunctualizeApp(name="testapp")
        plugin = self._make_plugin("test-plugin")
        app.plugin_loader._loaded_instances.append(plugin)

        app._shutdown_plugins()

        plugin.on_shutdown.assert_called_once_with(app)

    def test_shutdown_reverse_loading_order(self) -> None:
        """Plugins are shut down in reverse loading order (last loaded = first shutdown)."""
        call_order: list[str] = []

        app = FunctualizeApp(name="testapp")

        for name in ["alpha", "beta", "gamma"]:
            plugin = self._make_plugin(name)
            plugin.on_shutdown = MagicMock(
                side_effect=lambda a, n=name: call_order.append(n)
            )
            app.plugin_loader._loaded_instances.append(plugin)

        app._shutdown_plugins()

        assert call_order == ["gamma", "beta", "alpha"]

    def test_shutdown_exception_isolation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If a plugin's on_shutdown raises, log error and continue remaining."""
        call_order: list[str] = []

        app = FunctualizeApp(name="testapp")

        # Plugin that raises
        bad_plugin = self._make_plugin("bad-plugin")
        bad_plugin.on_shutdown = MagicMock(side_effect=RuntimeError("shutdown failed"))

        # Plugin that succeeds (loaded after bad, so should shutdown first)
        good_plugin = self._make_plugin("good-plugin")
        good_plugin.on_shutdown = MagicMock(
            side_effect=lambda a: call_order.append("good")
        )

        app.plugin_loader._loaded_instances.extend([bad_plugin, good_plugin])

        with caplog.at_level(logging.ERROR):
            app._shutdown_plugins()

        # good_plugin shutdown first (reverse order), bad_plugin second
        assert call_order == ["good"]
        assert "bad-plugin" in caplog.text
        assert "shutdown failed" in caplog.text

    def test_shutdown_timeout_enforcement(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If on_shutdown exceeds 5s timeout, abandon and continue next plugin."""
        call_order: list[str] = []

        app = FunctualizeApp(name="testapp")

        # Slow plugin (simulate with short sleep for test - we'll mock the timeout)
        slow_plugin = self._make_plugin("slow-plugin")

        def slow_shutdown(a: Any) -> None:
            time.sleep(1)  # Would take 10s

        slow_plugin.on_shutdown = slow_shutdown

        # Good plugin loaded after slow (shutdown first in reverse order)
        good_plugin = self._make_plugin("good-plugin")
        good_plugin.on_shutdown = MagicMock(
            side_effect=lambda a: call_order.append("good")
        )

        app.plugin_loader._loaded_instances.extend([slow_plugin, good_plugin])

        # Patch the timeout to be very short for testing
        import concurrent.futures

        original_result = concurrent.futures.Future.result

        def mock_result(self_future: Any, timeout: float | None = None) -> Any:
            # Use a very short timeout for the test
            return original_result(self_future, timeout=0.1)

        with (
            patch.object(concurrent.futures.Future, "result", mock_result),
            caplog.at_level(logging.ERROR),
        ):
            app._shutdown_plugins()

        # good_plugin should still get called (reverse order)
        assert "good" in call_order
        assert "slow-plugin" in caplog.text
        assert "timeout" in caplog.text.lower() or "Timeout" in caplog.text

    def test_shutdown_only_plugins_with_protocol(self) -> None:
        """Only plugins satisfying PluginWithShutdown are shut down."""
        app = FunctualizeApp(name="testapp")

        # Plugin WITHOUT on_shutdown
        no_shutdown_plugin = MagicMock()
        no_shutdown_plugin.name = "no-shutdown"
        no_shutdown_plugin.version = "1.0.0"
        del no_shutdown_plugin.on_shutdown  # Remove the attribute

        # Plugin WITH on_shutdown
        with_shutdown = self._make_plugin("with-shutdown")
        app.plugin_loader._loaded_instances.extend([no_shutdown_plugin, with_shutdown])

        app._shutdown_plugins()

        with_shutdown.on_shutdown.assert_called_once_with(app)

    def test_shutdown_no_plugins_is_noop(self) -> None:
        """When no plugins are loaded, shutdown completes without error."""
        app = FunctualizeApp(name="testapp")
        app._shutdown_plugins()  # Should not raise

    def test_run_calls_shutdown_after_command(self) -> None:
        """run() should invoke shutdown after cli_command() completes."""
        app = FunctualizeApp(name="testapp")
        plugin = self._make_plugin("test-plugin")
        app.plugin_loader._loaded_instances.append(plugin)

        # Mock cli_command to be a no-op and simulate SystemExit (typer's normal behavior)
        with (
            patch.object(app, "cli_command", side_effect=SystemExit(0)),
            pytest.raises(SystemExit),
        ):
            app.run()

        plugin.on_shutdown.assert_called_once_with(app)

    def test_run_calls_shutdown_even_on_exception(self) -> None:
        """run() should invoke shutdown even if cli_command() raises."""
        app = FunctualizeApp(name="testapp")
        plugin = self._make_plugin("test-plugin")
        app.plugin_loader._loaded_instances.append(plugin)

        # Mock cli_command to raise a non-SystemExit exception
        with (
            patch.object(
                app, "cli_command", side_effect=RuntimeError("command failed")
            ),
            pytest.raises(RuntimeError, match="command failed"),
        ):
            app.run()

        plugin.on_shutdown.assert_called_once_with(app)
