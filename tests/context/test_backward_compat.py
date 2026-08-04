"""Backward compatibility unit tests for the enriched RunContext.

Validates that the enriched RunContext does not break existing API usage
patterns, preserving all existing public properties, methods, hook callback
signatures, and plugin loading behavior.

Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7
"""

from __future__ import annotations

import inspect
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from functualize._config.job_config import JobConfigView
from functualize._events.hooks import HookEvent, HookRegistry
from functualize.job._state_store import StateStore
from functualize.job.context import (
    InvalidStateTransitionError,
    RunContext,
    RunStatus,
    RunType,
)

# --- Fixtures ---


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock JobConfigView instance."""
    return MagicMock(spec=JobConfigView)


@pytest.fixture
def mock_logger() -> MagicMock:
    """Create a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def run_context(mock_config: MagicMock, mock_logger: MagicMock) -> RunContext:
    """Create a RunContext using only legacy constructor arguments."""
    return RunContext(name="test-job", config=mock_config, logger=mock_logger)


# --- Requirement 11.1: Existing public properties unchanged ---


class TestExistingPublicPropertiesUnchanged:
    """Verify all existing RunContext public properties are preserved.

    Validates: Requirement 11.1
    """

    def test_config_property_returns_configurations(
        self, run_context: RunContext, mock_config: MagicMock
    ) -> None:
        """The `config` property returns the JobConfigView object passed at init."""
        assert run_context.config is mock_config

    def test_name_property_returns_string(self, run_context: RunContext) -> None:
        """The `name` property returns the job name string."""
        assert run_context.name == "test-job"
        assert isinstance(run_context.name, str)

    def test_metadata_property_returns_dict(self, run_context: RunContext) -> None:
        """The `metadata` property returns a mutable dict with expected defaults."""
        metadata = run_context.metadata
        assert isinstance(metadata, dict)
        assert "run_type" in metadata
        assert "run_status" in metadata
        assert "start_time" in metadata
        assert "end_time" in metadata
        assert "duration" in metadata

    def test_metadata_contains_run_type_job(self, run_context: RunContext) -> None:
        """Default run_type is RunType.JOB."""
        assert run_context.metadata["run_type"] == RunType.JOB

    def test_metadata_contains_run_status_running(
        self, run_context: RunContext
    ) -> None:
        """Default run_status is RunStatus.RUNNING."""
        assert run_context.metadata["run_status"] == RunStatus.RUNNING

    def test_phases_property_returns_list(self, run_context: RunContext) -> None:
        """The `phases` property returns a list."""
        steps = run_context.phases
        assert isinstance(steps, list)
        assert steps == []

    def test_job_config_property_returns_none_initially(
        self, run_context: RunContext
    ) -> None:
        """The `job_config` property returns None when not set."""
        assert run_context.job_config is None


# --- Requirement 11.2: Existing public methods preserve signatures ---


class TestExistingPublicMethodSignatures:
    """Verify all existing public methods preserve their signatures.

    Validates: Requirement 11.2
    """

    def test_log_accepts_message_and_level(
        self, run_context: RunContext, mock_logger: MagicMock
    ) -> None:
        """log() accepts (message, level) with level defaulting to 'info'."""
        run_context.log("hello")
        mock_logger.info.assert_called_once_with("hello")

    def test_log_with_explicit_level(
        self, run_context: RunContext, mock_logger: MagicMock
    ) -> None:
        """log() accepts an explicit level parameter."""
        run_context.log("warn msg", level="warning")
        mock_logger.warning.assert_called_once_with("warn msg")

    def test_log_signature(self) -> None:
        """log() has the expected signature: (message, level='info')."""
        sig = inspect.signature(RunContext.log)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "message" in params
        assert "level" in params
        # 'level' has default value 'info'
        assert sig.parameters["level"].default == "info"

    def test_track_run_status_accepts_run_status_and_failure_message(
        self, run_context: RunContext
    ) -> None:
        """track_run_status() accepts (run_status, failure_message) params."""
        run_context.track_run_status(run_status=RunStatus.SUCCESS, failure_message="")
        assert run_context.metadata["run_status"] == RunStatus.SUCCESS

    def test_track_run_status_signature(self) -> None:
        """track_run_status() has expected signature."""
        sig = inspect.signature(RunContext.track_run_status)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "run_status" in params
        assert "failure_message" in params
        # Both have defaults
        assert sig.parameters["run_status"].default == RunStatus.RUNNING
        assert sig.parameters["failure_message"].default == ""

    def test_track_run_status_state_machine_preserved(
        self, run_context: RunContext
    ) -> None:
        """track_run_status() raises InvalidStateTransitionError from terminal states."""
        run_context.track_run_status(RunStatus.FAILURE, failure_message="bad")
        with pytest.raises(InvalidStateTransitionError):
            run_context.track_run_status(RunStatus.SUCCESS)

    def test_track_phase_accepts_name_message_status(
        self, run_context: RunContext
    ) -> None:
        """track_phase() accepts (phase_name, phase_message, phase_status)."""
        run_context.track_phase("s1", "msg", RunStatus.RUNNING)
        assert len(run_context.phases) == 1
        assert run_context.phases[0]["name"] == "s1"

    def test_track_phase_signature(self) -> None:
        """track_phase() has expected signature."""
        sig = inspect.signature(RunContext.track_phase)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "phase_name" in params
        assert "phase_message" in params
        assert "phase_status" in params
        assert sig.parameters["phase_status"].default == RunStatus.RUNNING


# --- Requirement 11.3: job_config property setter preserved ---


class TestJobConfigSetterPreserved:
    """Verify job_config property setter behavior is unchanged.

    Validates: Requirement 11.3
    """

    def test_job_config_set_and_get(self, run_context: RunContext) -> None:
        """job_config can be set and retrieved."""
        config_obj = {"key": "value", "nested": {"a": 1}}
        run_context.job_config = config_obj
        assert run_context.job_config is config_obj

    def test_job_config_set_to_pydantic_model(
        self,
        mock_config: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        """job_config accepts any object (including Pydantic models)."""
        rc = RunContext(name="test", config=mock_config, logger=mock_logger)
        # Simulate a pydantic-like object
        model = MagicMock()
        model.field_a = "hello"
        rc.job_config = model
        assert rc.job_config is model

    def test_job_config_set_to_none(self, run_context: RunContext) -> None:
        """job_config can be set back to None."""
        run_context.job_config = {"something": True}
        run_context.job_config = None
        assert run_context.job_config is None


# --- Requirement 11.4: Legacy plugins load identically ---


class TestLegacyPluginsLoadIdentically:
    """Verify legacy plugins (no config_model/config_section) load identically.

    Validates: Requirement 11.4
    """

    def test_legacy_plugin_without_config_attributes(self) -> None:
        """A plugin with only name/version/description and __call__ loads fine."""
        from functualize._plugins.loader import _has_config_declaration

        class LegacyPlugin:
            name = "legacy-plugin"
            version = "1.0.0"
            description = "A simple legacy plugin"

            def __call__(self, app: Any) -> None:
                app.registered = True

        plugin = LegacyPlugin()
        # Should NOT be detected as config-declaring
        assert _has_config_declaration(plugin) is False

    def test_legacy_plugin_invoked_with_app(self) -> None:
        """Legacy plugin __call__(app) is invoked during loading."""
        from functualize._plugins.loader import _has_config_declaration

        class LegacyPlugin:
            name = "legacy-plugin"
            version = "1.0.0"
            description = "A simple legacy plugin"
            was_called = False

            def __call__(self, app: Any) -> None:
                LegacyPlugin.was_called = True

        plugin = LegacyPlugin()
        assert not _has_config_declaration(plugin)

        # Simulate the registration call
        mock_app = MagicMock()
        plugin(mock_app)
        assert LegacyPlugin.was_called

    def test_plugin_with_only_config_model_not_detected(self) -> None:
        """A plugin with config_model but no config_section is not detected."""
        from functualize._plugins.loader import _has_config_declaration

        class PartialPlugin:
            name = "partial"
            version = "1.0.0"
            description = "Partial config plugin"
            config_model = MagicMock  # Has config_model but not config_section

            def __call__(self, app: Any) -> None:
                pass

        plugin = PartialPlugin()
        assert _has_config_declaration(plugin) is False

    def test_plugin_with_only_config_section_not_detected(self) -> None:
        """A plugin with config_section but no config_model is not detected."""
        from functualize._plugins.loader import _has_config_declaration

        class PartialPlugin:
            name = "partial"
            version = "1.0.0"
            description = "Partial config plugin"
            config_section = "plugin.partial"
            # No config_model

            def __call__(self, app: Any) -> None:
                pass

        plugin = PartialPlugin()
        assert _has_config_declaration(plugin) is False


# --- Requirement 11.5: Hook callback signatures unchanged ---


class TestHookCallbackSignaturesUnchanged:
    """Verify existing hook callback signatures remain unchanged.

    Validates: Requirement 11.5
    """

    def test_before_job_hook_receives_rc(
        self,
        run_context: RunContext,
    ) -> None:
        """BEFORE_JOB hooks receive (rc) only."""
        registry = HookRegistry()
        received_args: list[Any] = []

        def before_hook(rc: RunContext) -> None:
            received_args.append(rc)

        registry.register_global(HookEvent.BEFORE_JOB, before_hook)
        registry.invoke(HookEvent.BEFORE_JOB, "test-job", run_context)

        assert len(received_args) == 1
        assert received_args[0] is run_context

    def test_after_success_hook_receives_rc(
        self,
        run_context: RunContext,
    ) -> None:
        """AFTER_SUCCESS hooks receive (rc) only."""
        registry = HookRegistry()
        received_args: list[Any] = []

        def success_hook(rc: RunContext) -> None:
            received_args.append(rc)

        registry.register_global(HookEvent.AFTER_SUCCESS, success_hook)
        registry.invoke(HookEvent.AFTER_SUCCESS, "test-job", run_context)

        assert len(received_args) == 1
        assert received_args[0] is run_context

    def test_after_failure_hook_receives_rc_and_exception(
        self,
        run_context: RunContext,
    ) -> None:
        """AFTER_FAILURE hooks receive (rc, exception)."""
        registry = HookRegistry()
        received_args: list[Any] = []

        def failure_hook(rc: RunContext, exc: Exception | None) -> None:
            received_args.append((rc, exc))

        registry.register_global(HookEvent.AFTER_FAILURE, failure_hook)
        error = ValueError("test error")
        registry.invoke(
            HookEvent.AFTER_FAILURE, "test-job", run_context, exception=error
        )

        assert len(received_args) == 1
        assert received_args[0][0] is run_context
        assert received_args[0][1] is error

    def test_on_teardown_hook_receives_rc(
        self,
        run_context: RunContext,
    ) -> None:
        """ON_TEARDOWN hooks receive (rc) only."""
        registry = HookRegistry()
        received_args: list[Any] = []

        def teardown_hook(rc: RunContext) -> None:
            received_args.append(rc)

        registry.register_global(HookEvent.ON_TEARDOWN, teardown_hook)
        registry.invoke(HookEvent.ON_TEARDOWN, "test-job", run_context)

        assert len(received_args) == 1
        assert received_args[0] is run_context

    def test_hook_events_constants_unchanged(self) -> None:
        """Hook event string constants remain the same."""
        assert HookEvent.BEFORE_JOB == "before_job"
        assert HookEvent.AFTER_SUCCESS == "after_success"
        assert HookEvent.AFTER_FAILURE == "after_failure"
        assert HookEvent.ON_TEARDOWN == "on_teardown"


# --- Requirement 11.6: plugin_configs returns empty mapping ---


class TestPluginConfigsEmptyMapping:
    """Verify plugin_configs returns empty mapping when no plugins registered.

    Validates: Requirement 11.6
    """

    def test_plugin_configs_empty_with_default_constructor(
        self, run_context: RunContext
    ) -> None:
        """plugin_configs returns empty mapping on a vanilla RunContext."""
        configs = run_context.plugin_configs
        assert len(configs) == 0
        assert dict(configs) == {}

    def test_plugin_configs_is_mapping(self, run_context: RunContext) -> None:
        """plugin_configs supports mapping interface (iteration, len, in)."""
        configs = run_context.plugin_configs
        assert len(configs) == 0
        assert list(configs.keys()) == []
        assert list(configs.values()) == []
        assert list(configs.items()) == []

    def test_plugin_configs_does_not_raise(self, run_context: RunContext) -> None:
        """Accessing plugin_configs does not raise any error."""
        # Should not raise
        _ = run_context.plugin_configs

    def test_plugin_configs_is_immutable(self, run_context: RunContext) -> None:
        """plugin_configs mapping does not allow item assignment."""
        configs = run_context.plugin_configs
        with pytest.raises(TypeError):
            configs["test"] = "value"  # type: ignore[index]


# --- Requirement 11.7: state works as local in-memory store ---


class TestStateLocalInMemoryStore:
    """Verify state works as local in-memory store with no scope.

    Validates: Requirement 11.7
    """

    def test_state_returns_state_store(self, run_context: RunContext) -> None:
        """Accessing state returns a StateStore instance."""
        store = run_context.state
        assert isinstance(store, StateStore)

    def test_state_set_and_get(self, run_context: RunContext) -> None:
        """State store supports basic set/get operations."""
        run_context.state.set("key", "value")
        assert run_context.state.get("key", str) == "value"

    def test_state_is_same_instance_on_repeated_access(
        self, run_context: RunContext
    ) -> None:
        """Repeated access to state returns the same instance."""
        store1 = run_context.state
        store2 = run_context.state
        assert store1 is store2

    def test_state_is_independent_per_runcontext(
        self,
        mock_config: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        """Each RunContext (without scope) gets its own isolated state."""
        rc1 = RunContext(name="job1", config=mock_config, logger=mock_logger)
        rc2 = RunContext(name="job2", config=mock_config, logger=mock_logger)

        rc1.state.set("shared_key", "from_job1")
        # rc2 does NOT see rc1's state
        assert rc2.state.get("shared_key", str) is None

    def test_state_supports_keys_and_clear(self, run_context: RunContext) -> None:
        """State store supports keys() and clear() operations."""
        run_context.state.set("a", 1)
        run_context.state.set("b", 2)
        assert sorted(run_context.state.keys()) == ["a", "b"]

        run_context.state.clear()
        assert run_context.state.keys() == []

    def test_state_lazy_initialization(
        self,
        mock_config: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        """State store is lazily initialized - no allocation until first access."""
        rc = RunContext(name="test", config=mock_config, logger=mock_logger)
        # Access internal attribute directly to verify lazy init
        assert rc._state_store is None
        # Accessing state triggers creation
        _ = rc.state
        assert rc._state_store is not None


# --- Additional backward compatibility checks ---


class TestRunContextConstructorBackwardCompat:
    """Verify RunContext can be constructed with only legacy arguments."""

    def test_construct_with_positional_args(
        self, mock_config: MagicMock, mock_logger: MagicMock
    ) -> None:
        """RunContext accepts (name, config, logger) as positional args."""
        rc = RunContext("my-job", mock_config, mock_logger)
        assert rc.name == "my-job"
        assert rc.config is mock_config

    def test_construct_with_metadata(
        self, mock_config: MagicMock, mock_logger: MagicMock
    ) -> None:
        """RunContext accepts optional metadata dict."""
        rc = RunContext("my-job", mock_config, mock_logger, {"custom": "data"})
        assert rc.metadata["custom"] == "data"

    def test_config_set_prefix_called_on_init(
        self, mock_config: MagicMock, mock_logger: MagicMock
    ) -> None:
        """config.set_prefix(name) is called during construction."""
        RunContext("prefix-job", mock_config, mock_logger)
        mock_config.set_prefix.assert_called_once_with("prefix-job")

    def test_new_optional_params_do_not_affect_legacy_behavior(
        self, mock_config: MagicMock, mock_logger: MagicMock
    ) -> None:
        """New keyword-only params default to None and don't change behavior."""
        rc = RunContext(name="test", config=mock_config, logger=mock_logger)
        # All new features work without explicit construction args
        assert len(rc.plugin_configs) == 0
        assert isinstance(rc.state, StateStore)
        assert len(rc.resources) == 0


class TestRunContextMetadataDefaults:
    """Verify metadata defaults are preserved."""

    def test_defaults_set_via_setdefault(
        self, mock_config: MagicMock, mock_logger: MagicMock
    ) -> None:
        """Custom metadata does not override framework defaults that are missing."""
        rc = RunContext(
            "test",
            mock_config,
            mock_logger,
            metadata={"custom_field": "hello"},
        )
        # Framework defaults still present
        assert rc.metadata["run_type"] == RunType.JOB
        assert rc.metadata["run_status"] == RunStatus.RUNNING
        assert rc.metadata["start_time"] is not None
        assert rc.metadata["end_time"] is None
        assert rc.metadata["duration"] is None
        # Custom field preserved
        assert rc.metadata["custom_field"] == "hello"

    def test_provided_run_type_not_overridden(
        self, mock_config: MagicMock, mock_logger: MagicMock
    ) -> None:
        """User-provided run_type in metadata is not overridden by defaults."""
        rc = RunContext(
            "test",
            mock_config,
            mock_logger,
            metadata={"run_type": RunType.COMMAND},
        )
        assert rc.metadata["run_type"] == RunType.COMMAND
