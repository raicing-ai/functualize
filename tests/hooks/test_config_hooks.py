"""Unit tests for ConfigHookEvent and invoke_config_event."""

import logging

import pytest

from functualize._events.hooks import ConfigHookEvent, HookRegistry


@pytest.fixture
def registry() -> HookRegistry:
    """Create a fresh HookRegistry instance."""
    return HookRegistry()


class TestConfigHookEvent:
    """Tests for ConfigHookEvent constants."""

    def test_after_config_init_value(self) -> None:
        assert ConfigHookEvent.AFTER_CONFIG_INIT == "after_config_init"

    def test_before_config_resolve_value(self) -> None:
        assert ConfigHookEvent.BEFORE_CONFIG_RESOLVE == "before_config_resolve"

    def test_after_config_resolve_value(self) -> None:
        assert ConfigHookEvent.AFTER_CONFIG_RESOLVE == "after_config_resolve"


class TestInvokeConfigEvent:
    """Tests for invoke_config_event method."""

    def test_after_config_init_invokes_hook_with_resolution_chain(
        self, registry: HookRegistry
    ) -> None:
        received: list[object] = []
        registry.register_global(
            ConfigHookEvent.AFTER_CONFIG_INIT, lambda chain: received.append(chain)
        )
        fake_chain = object()
        registry.invoke_config_event(ConfigHookEvent.AFTER_CONFIG_INIT, fake_chain)
        assert received == [fake_chain]

    def test_before_config_resolve_invokes_hook_with_section_and_model_class(
        self, registry: HookRegistry
    ) -> None:
        received: list[tuple[str, type]] = []
        registry.register_global(
            ConfigHookEvent.BEFORE_CONFIG_RESOLVE,
            lambda section, model_class: received.append((section, model_class)),
        )

        class FakeModel:
            pass

        registry.invoke_config_event(
            ConfigHookEvent.BEFORE_CONFIG_RESOLVE, "database", FakeModel
        )
        assert received == [("database", FakeModel)]

    def test_after_config_resolve_invokes_hook_with_section_and_model(
        self, registry: HookRegistry
    ) -> None:
        received: list[tuple[str, object]] = []
        registry.register_global(
            ConfigHookEvent.AFTER_CONFIG_RESOLVE,
            lambda section, model: received.append((section, model)),
        )
        fake_model = object()
        registry.invoke_config_event(
            ConfigHookEvent.AFTER_CONFIG_RESOLVE, "database", fake_model
        )
        assert received == [("database", fake_model)]

    def test_multiple_hooks_invoked_in_registration_order(
        self, registry: HookRegistry
    ) -> None:
        called: list[str] = []
        registry.register_global(
            ConfigHookEvent.AFTER_CONFIG_INIT, lambda chain: called.append("first")
        )
        registry.register_global(
            ConfigHookEvent.AFTER_CONFIG_INIT, lambda chain: called.append("second")
        )
        registry.register_global(
            ConfigHookEvent.AFTER_CONFIG_INIT, lambda chain: called.append("third")
        )
        registry.invoke_config_event(ConfigHookEvent.AFTER_CONFIG_INIT, object())
        assert called == ["first", "second", "third"]

    def test_hook_failure_logged_at_warning_level(
        self, registry: HookRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        def bad_hook(chain: object) -> None:
            raise RuntimeError("hook exploded")

        registry.register_global(ConfigHookEvent.AFTER_CONFIG_INIT, bad_hook)

        with caplog.at_level(logging.WARNING, logger="functualize._events.hooks"):
            registry.invoke_config_event(ConfigHookEvent.AFTER_CONFIG_INIT, object())

        assert "bad_hook" in caplog.text
        assert "hook exploded" in caplog.text
        assert caplog.records[0].levelno == logging.WARNING

    def test_hook_failure_does_not_prevent_subsequent_hooks(
        self, registry: HookRegistry
    ) -> None:
        called: list[str] = []

        def bad_hook(chain: object) -> None:
            raise RuntimeError("failure")

        def good_hook(chain: object) -> None:
            called.append("good")

        registry.register_global(ConfigHookEvent.AFTER_CONFIG_INIT, bad_hook)
        registry.register_global(ConfigHookEvent.AFTER_CONFIG_INIT, good_hook)

        registry.invoke_config_event(ConfigHookEvent.AFTER_CONFIG_INIT, object())
        assert called == ["good"]

    def test_multiple_failing_hooks_all_logged_and_good_hooks_still_run(
        self, registry: HookRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        called: list[str] = []

        def bad1(chain: object) -> None:
            raise RuntimeError("error1")

        def bad2(chain: object) -> None:
            raise ValueError("error2")

        def good(chain: object) -> None:
            called.append("good")

        registry.register_global(ConfigHookEvent.AFTER_CONFIG_INIT, bad1)
        registry.register_global(ConfigHookEvent.AFTER_CONFIG_INIT, bad2)
        registry.register_global(ConfigHookEvent.AFTER_CONFIG_INIT, good)

        with caplog.at_level(logging.WARNING, logger="functualize._events.hooks"):
            registry.invoke_config_event(ConfigHookEvent.AFTER_CONFIG_INIT, object())

        assert called == ["good"]
        assert "error1" in caplog.text
        assert "error2" in caplog.text

    def test_no_hooks_registered_does_nothing(self, registry: HookRegistry) -> None:
        # Should not raise
        registry.invoke_config_event(ConfigHookEvent.AFTER_CONFIG_INIT, object())

    def test_kwargs_passed_to_hooks(self, registry: HookRegistry) -> None:
        received_kwargs: list[dict[str, object]] = []

        def hook(**kwargs: object) -> None:
            received_kwargs.append(kwargs)

        registry.register_global(ConfigHookEvent.AFTER_CONFIG_INIT, hook)
        registry.invoke_config_event(
            ConfigHookEvent.AFTER_CONFIG_INIT, extra_info="test"
        )
        assert received_kwargs == [{"extra_info": "test"}]

    def test_config_hook_does_not_interfere_with_job_hooks(
        self, registry: HookRegistry
    ) -> None:
        """Config hooks and job hooks are registered via the same register_global
        but invoked through different methods."""
        config_called: list[str] = []
        job_called: list[str] = []

        registry.register_global(
            ConfigHookEvent.AFTER_CONFIG_INIT,
            lambda chain: config_called.append("config"),
        )
        from unittest.mock import MagicMock

        from functualize.job.context import RunContext

        mock_rc = MagicMock(spec=RunContext)
        from functualize._events.hooks import HookEvent

        registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: job_called.append("job")
        )

        # Invoke config event - should not trigger job hooks
        registry.invoke_config_event(ConfigHookEvent.AFTER_CONFIG_INIT, object())
        assert config_called == ["config"]
        assert job_called == []

        # Invoke job event - should not trigger config hooks
        registry.invoke(HookEvent.BEFORE_JOB, "test_job", mock_rc)
        assert job_called == ["job"]
        # config_called should still only have one entry
        assert config_called == ["config"]

    def test_hook_without_name_uses_repr(
        self, registry: HookRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Hooks without __name__ (e.g., lambdas with deleted name) should
        fall back to repr."""

        class CallableWithoutName:
            def __call__(self, chain: object) -> None:
                raise RuntimeError("no name hook failed")

        hook = CallableWithoutName()
        # Remove __name__ if it exists
        if hasattr(hook, "__name__"):
            del hook.__name__

        registry.register_global(ConfigHookEvent.AFTER_CONFIG_INIT, hook)

        with caplog.at_level(logging.WARNING, logger="functualize._events.hooks"):
            registry.invoke_config_event(ConfigHookEvent.AFTER_CONFIG_INIT, object())

        assert "no name hook failed" in caplog.text
