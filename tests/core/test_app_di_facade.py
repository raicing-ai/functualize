"""Unit tests for FunctualizeApp DI facade methods and registry freeze lifecycle.

Tests cover:
- app.provide() delegates to internal DIRegistry
- app.provide_factory() delegates to internal DIRegistry
- app.provide_named() delegates to internal DIRegistry
- Registry freeze triggered after APP_READY hooks complete
- REGISTRY_FROZEN event emitted after freeze, before adapter run()
- APP_READY hooks can still call provide() (registry unfrozen during hooks)
- Post-boot provide() raises RegistryFrozenError
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from functualize._app.state import AppState
from functualize._events.hooks import HookEvent
from functualize._primitives.di import RegistryFrozenError
from functualize.app.core import FunctualizeApp


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


class TestDIFacadeMethods:
    """Tests for app.provide(), app.provide_factory(), app.provide_named()."""

    def test_provide_delegates_to_registry(self) -> None:
        """app.provide() stores a singleton in the internal DIRegistry."""
        app = FunctualizeApp(name="testapp")

        # Registry is frozen after boot — manually reset for facade testing
        app._di_registry._frozen = False

        class MyService:
            pass

        instance = MyService()
        app.provide(MyService, instance)

        resolved = app._di_registry.resolve(MyService)
        assert resolved is instance

    def test_provide_with_qualifier(self) -> None:
        """app.provide() with qualifier stores qualified registration."""
        app = FunctualizeApp(name="testapp")
        app._di_registry._frozen = False

        class Cache:
            pass

        redis_cache = Cache()
        app.provide(Cache, redis_cache, qualifier="redis")

        resolved = app._di_registry.resolve(Cache, qualifier="redis")
        assert resolved is redis_cache

    def test_provide_factory_delegates_to_registry(self) -> None:
        """app.provide_factory() registers a factory in the internal DIRegistry."""
        app = FunctualizeApp(name="testapp")
        app._di_registry._frozen = False

        class Service:
            pass

        call_count = 0

        def factory() -> Service:
            nonlocal call_count
            call_count += 1
            return Service()

        app.provide_factory(Service, factory, "singleton")

        result1 = app._di_registry.resolve(Service)
        result2 = app._di_registry.resolve(Service)
        assert result1 is result2
        assert call_count == 1

    def test_provide_factory_invocation_scope(self) -> None:
        """app.provide_factory() with 'invocation' scope creates new instances each time."""
        app = FunctualizeApp(name="testapp")
        app._di_registry._frozen = False

        class Service:
            pass

        def factory(caps: dict[type, Any] = None) -> Service:
            if caps is None:
                caps = {}
            return Service()

        app.provide_factory(Service, factory, "invocation")

        result1 = app._di_registry.resolve(Service)
        result2 = app._di_registry.resolve(Service)
        assert result1 is not result2

    def test_provide_factory_with_qualifier(self) -> None:
        """app.provide_factory() with qualifier stores qualified factory."""
        app = FunctualizeApp(name="testapp")
        app._di_registry._frozen = False

        class DB:
            pass

        def factory() -> DB:
            return DB()

        app.provide_factory(DB, factory, "singleton", qualifier="primary")

        resolved = app._di_registry.resolve(DB, qualifier="primary")
        assert isinstance(resolved, DB)

    def test_provide_named_delegates_to_registry(self) -> None:
        """app.provide_named() registers a string-keyed value."""
        app = FunctualizeApp(name="testapp")
        app._di_registry._frozen = False

        app.provide_named("api_key", "secret-123")

        resolved = app._di_registry.resolve_named("api_key")
        assert resolved == "secret-123"

    def test_provide_raises_after_freeze(self) -> None:
        """app.provide() raises RegistryFrozenError after boot (registry frozen)."""
        app = FunctualizeApp(name="testapp")

        # Registry should be frozen after __init__ completes
        assert app._di_registry.is_frozen

        class Service:
            pass

        with pytest.raises(RegistryFrozenError):
            app.provide(Service, Service())

    def test_provide_factory_raises_after_freeze(self) -> None:
        """app.provide_factory() raises RegistryFrozenError after boot."""
        app = FunctualizeApp(name="testapp")

        class Service:
            pass

        with pytest.raises(RegistryFrozenError):
            app.provide_factory(Service, lambda: Service(), "singleton")

    def test_provide_named_raises_after_freeze(self) -> None:
        """app.provide_named() raises RegistryFrozenError after boot."""
        app = FunctualizeApp(name="testapp")

        with pytest.raises(RegistryFrozenError):
            app.provide_named("key", "value")


class TestRegistryFreezeLifecycle:
    """Tests for DI registry freeze timing and REGISTRY_FROZEN event."""

    def test_registry_frozen_after_init(self) -> None:
        """DIRegistry is frozen after FunctualizeApp.__init__() completes."""
        app = FunctualizeApp(name="testapp")
        assert app._di_registry.is_frozen is True

    def test_registry_unfrozen_during_app_ready_hooks(self) -> None:
        """DIRegistry remains unfrozen while APP_READY hooks execute."""
        registry_frozen_during_hook: list[bool] = []

        class TestPlugin:
            name = "freeze-check-plugin"
            version = "1.0.0"
            description = "Test"

            def __call__(self, app_instance: Any) -> None:
                def check_frozen(a: Any) -> None:
                    registry_frozen_during_hook.append(a._di_registry.is_frozen)

                app_instance._hook_registry.register_global(
                    HookEvent.APP_READY, check_frozen
                )

        mock_ep = MagicMock()
        mock_ep.name = "freeze-check-plugin"
        mock_ep.load.return_value = TestPlugin()

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            app = FunctualizeApp(name="testapp")

        # During APP_READY, registry should have been unfrozen
        assert registry_frozen_during_hook == [False]
        # After init, it should be frozen
        assert app._di_registry.is_frozen is True

    def test_app_ready_hooks_can_provide(self) -> None:
        """APP_READY hooks can call app.provide() since registry is unfrozen."""
        provided_successfully: list[bool] = []

        class MyService:
            pass

        class TestPlugin:
            name = "provide-in-ready-plugin"
            version = "1.0.0"
            description = "Test"

            def __call__(self, app_instance: Any) -> None:
                def register_service(a: Any) -> None:
                    try:
                        a.provide(MyService, MyService())
                        provided_successfully.append(True)
                    except RegistryFrozenError:
                        provided_successfully.append(False)

                app_instance._hook_registry.register_global(
                    HookEvent.APP_READY, register_service
                )

        mock_ep = MagicMock()
        mock_ep.name = "provide-in-ready-plugin"
        mock_ep.load.return_value = TestPlugin()

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            app = FunctualizeApp(name="testapp")

        assert provided_successfully == [True]
        # Verify it was actually registered
        assert app._di_registry.has(MyService)

    def test_registry_frozen_event_emitted(self) -> None:
        """REGISTRY_FROZEN event is emitted after freeze."""
        events_received: list[Any] = []

        class TestPlugin:
            name = "event-listener-plugin"
            version = "1.0.0"
            description = "Test"

            def __call__(self, app_instance: Any) -> None:
                app_instance.event_bus.subscribe(
                    "lifecycle.registry.frozen",
                    lambda event: events_received.append(event),
                )

        mock_ep = MagicMock()
        mock_ep.name = "event-listener-plugin"
        mock_ep.load.return_value = TestPlugin()

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            app = FunctualizeApp(name="testapp")

        # Event should have been emitted once
        assert len(events_received) == 1
        # The event payload should contain the app reference
        event = events_received[0]
        assert event.payload["app"] is app

    def test_registry_frozen_event_emitted_after_app_ready(self) -> None:
        """REGISTRY_FROZEN event fires after APP_READY hooks, not before."""
        order: list[str] = []

        class TestPlugin:
            name = "order-check-plugin"
            version = "1.0.0"
            description = "Test"

            def __call__(self, app_instance: Any) -> None:
                # Register APP_READY hook
                app_instance._hook_registry.register_global(
                    HookEvent.APP_READY, lambda a: order.append("app_ready")
                )
                # Subscribe to REGISTRY_FROZEN event
                app_instance.event_bus.subscribe(
                    "lifecycle.registry.frozen",
                    lambda event: order.append("registry_frozen"),
                )

        mock_ep = MagicMock()
        mock_ep.name = "order-check-plugin"
        mock_ep.load.return_value = TestPlugin()

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            FunctualizeApp(name="testapp")

        assert order == ["app_ready", "registry_frozen"]

    def test_registry_frozen_before_run(self) -> None:
        """Registry is frozen before run() is called (by design, it freezes during __init__)."""
        app = FunctualizeApp(name="testapp")

        # By the time we can call run(), the registry is already frozen
        assert app._di_registry.is_frozen is True
