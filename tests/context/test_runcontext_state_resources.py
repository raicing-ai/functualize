"""Unit tests for RunContext state store, resources, run status getters, and workflow step access.

Tests task 6.5 additions:
- state property (lazy StateStore creation)
- resources property (lazy MappingProxyType)
- get_resource(name, type_) with type checking
- inject_resource(rc, name, resource) utility function
- run_status read-only property
- set_run_status(status, message) with callback invocation
- get_phase(step_name)
- current_phase property
- run_duration property
"""

import logging
import time
from types import MappingProxyType
from unittest.mock import MagicMock

import pytest

from functualize._config.job_config import JobConfigView
from functualize.job._state_store import StateStore
from functualize.job.context import (
    InvalidStateTransitionError,
    RunContext,
    RunStatus,
    inject_resource,
)


@pytest.fixture
def mock_config():
    """Create a mock JobConfigView instance."""
    config = MagicMock(spec=JobConfigView)
    return config


@pytest.fixture
def mock_logger():
    """Create a mock Logger instance."""
    logger = MagicMock(spec=logging.Logger)
    return logger


@pytest.fixture
def rc(mock_config, mock_logger):
    """Create a RunContext instance for testing."""
    return RunContext(name="test-job", config=mock_config, logger=mock_logger)


class TestStateProperty:
    """Tests for RunContext.state property."""

    def test_state_returns_state_store(self, rc):
        """Accessing .state returns a StateStore instance."""
        assert isinstance(rc.state, StateStore)

    def test_state_lazily_created(self, mock_config, mock_logger):
        """StateStore is not allocated until first access."""
        run_ctx = RunContext(name="test", config=mock_config, logger=mock_logger)
        # Before access, _state_store is None
        assert run_ctx._state_store is None
        # After access, it's created
        _ = run_ctx.state
        assert run_ctx._state_store is not None

    def test_state_same_instance_on_repeated_access(self, rc):
        """Repeated access returns the same StateStore instance."""
        s1 = rc.state
        s2 = rc.state
        assert s1 is s2

    def test_state_with_provided_store(self, mock_config, mock_logger):
        """If state_store is provided in constructor, it is used."""
        store = StateStore()
        store.set("key", "value")
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            state_store=store,
        )
        assert run_ctx.state is store
        assert run_ctx.state.get("key", str) == "value"

    def test_state_is_functional(self, rc):
        """StateStore operations work through the property."""
        rc.state.set("counter", 42)
        assert rc.state.get("counter", int) == 42


class TestResourcesProperty:
    """Tests for RunContext.resources property."""

    def test_resources_returns_mapping_proxy(self, rc):
        """resources property returns a MappingProxyType."""
        assert isinstance(rc.resources, MappingProxyType)

    def test_resources_empty_by_default(self, rc):
        """resources is empty when no resources injected."""
        assert len(rc.resources) == 0
        assert dict(rc.resources) == {}

    def test_resources_lazily_initialized(self, mock_config, mock_logger):
        """resources dict not allocated until first access."""
        run_ctx = RunContext(name="test", config=mock_config, logger=mock_logger)
        assert run_ctx._resources is None
        _ = run_ctx.resources
        assert run_ctx._resources is not None

    def test_resources_immutable_from_outside(self, rc):
        """Resources mapping cannot be mutated via the property."""
        with pytest.raises(TypeError):
            rc.resources["key"] = "value"  # type: ignore[index]

    def test_resources_with_provided_dict(self, mock_config, mock_logger):
        """If resources dict provided in constructor, it is used."""
        resources = {"db": object()}
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            resources=resources,
        )
        assert "db" in run_ctx.resources


class TestGetResource:
    """Tests for RunContext.get_resource() method."""

    def test_get_resource_returns_typed_resource(self, mock_config, mock_logger):
        """get_resource returns resource when name and type match."""

        class DBClient:
            pass

        client = DBClient()
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            resources={"db": client},
        )
        result = run_ctx.get_resource("db", DBClient)
        assert result is client

    def test_get_resource_raises_key_error_missing(self, rc):
        """get_resource raises KeyError for unknown resource name."""
        with pytest.raises(KeyError, match="not found"):
            rc.get_resource("missing", str)

    def test_get_resource_key_error_lists_available(self, mock_config, mock_logger):
        """KeyError message lists available resources."""
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            resources={"db": "client", "cache": "redis"},
        )
        with pytest.raises(KeyError, match="Available"):
            run_ctx.get_resource("missing", str)

    def test_get_resource_raises_type_error_mismatch(self, mock_config, mock_logger):
        """get_resource raises TypeError when type doesn't match."""
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            resources={"db": "not-a-dict"},
        )
        with pytest.raises(TypeError, match="expected dict"):
            run_ctx.get_resource("db", dict)

    def test_get_resource_type_error_message(self, mock_config, mock_logger):
        """TypeError message identifies resource name, expected and actual type."""
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            resources={"counter": "hello"},
        )
        with pytest.raises(TypeError, match="counter.*expected int.*got str"):
            run_ctx.get_resource("counter", int)


class TestInjectResource:
    """Tests for inject_resource() utility function."""

    def test_inject_resource_adds_to_resources(self, rc):
        """inject_resource makes resource accessible via get_resource."""
        inject_resource(rc, "db", {"host": "localhost"})
        result = rc.get_resource("db", dict)
        assert result == {"host": "localhost"}

    def test_inject_resource_creates_resources_dict_if_none(
        self, mock_config, mock_logger
    ):
        """inject_resource creates _resources dict if None."""
        run_ctx = RunContext(name="test", config=mock_config, logger=mock_logger)
        assert run_ctx._resources is None
        inject_resource(run_ctx, "svc", "service_obj")
        assert run_ctx._resources is not None
        assert run_ctx._resources["svc"] == "service_obj"

    def test_inject_resource_visible_in_resources_property(self, rc):
        """Injected resources appear in the resources mapping proxy."""
        inject_resource(rc, "cache", [1, 2, 3])
        assert "cache" in rc.resources
        assert rc.resources["cache"] == [1, 2, 3]

    def test_inject_resource_overwrites_existing(self, rc):
        """inject_resource can overwrite an existing resource."""
        inject_resource(rc, "db", "old")
        inject_resource(rc, "db", "new")
        assert rc.get_resource("db", str) == "new"


class TestRunStatusProperty:
    """Tests for RunContext.run_status read-only property."""

    def test_initial_run_status_is_running(self, rc):
        """run_status is RUNNING on fresh RunContext."""
        assert rc.run_status == RunStatus.RUNNING

    def test_run_status_reflects_track_run_status(self, rc):
        """run_status property reflects changes made via track_run_status."""
        rc.track_run_status(RunStatus.SUCCESS)
        assert rc.run_status == RunStatus.SUCCESS

    def test_run_status_is_enum_type(self, rc):
        """run_status returns a RunStatus enum value."""
        assert isinstance(rc.run_status, RunStatus)


class TestSetRunStatus:
    """Tests for RunContext.set_run_status() method."""

    def test_set_run_status_updates_status(self, rc):
        """set_run_status updates the run_status property."""
        rc.set_run_status(RunStatus.SUCCESS)
        assert rc.run_status == RunStatus.SUCCESS

    def test_set_run_status_raises_on_terminal(self, rc):
        """set_run_status raises InvalidStateTransitionError from terminal state."""
        rc.set_run_status(RunStatus.SUCCESS)
        with pytest.raises(InvalidStateTransitionError):
            rc.set_run_status(RunStatus.FAILURE)

    def test_set_run_status_invokes_callbacks(self, rc):
        """set_run_status invokes registered status callbacks."""
        callback = MagicMock()
        rc._status_callbacks = [callback]
        rc.set_run_status(RunStatus.SUCCESS, "done")
        callback.assert_called_once_with(RunStatus.RUNNING, RunStatus.SUCCESS, "done")

    def test_set_run_status_callback_error_does_not_prevent_transition(
        self, rc, mock_logger
    ):
        """Callback exceptions don't prevent the status transition."""

        def bad_callback(old, new, msg):
            raise ValueError("callback error")

        rc._status_callbacks = [bad_callback]
        rc.set_run_status(RunStatus.SUCCESS)
        assert rc.run_status == RunStatus.SUCCESS
        mock_logger.warning.assert_called()

    def test_set_run_status_backward_compat_with_track_run_status(self, rc):
        """set_run_status calls track_run_status internally."""
        rc.set_run_status(RunStatus.FAILURE, "oops")
        assert rc.metadata["run_status"] == RunStatus.FAILURE
        assert rc.metadata["end_time"] is not None
        assert rc.metadata["duration"] is not None

    def test_track_run_status_still_works_independently(self, rc):
        """track_run_status remains functional (backward compat)."""
        rc.track_run_status(run_status=RunStatus.SUCCESS, failure_message="")
        assert rc.run_status == RunStatus.SUCCESS


class TestGetPhase:
    """Tests for RunContext.get_phase() method."""

    def test_returns_none_for_untracked_step(self, rc):
        """get_phase returns None for unknown step name."""
        assert rc.get_phase("nonexistent") is None

    def test_returns_step_dict_for_tracked_step(self, rc):
        """get_phase returns the step dict for a tracked step."""
        rc.track_phase("deploy", "deploying", RunStatus.RUNNING)
        step = rc.get_phase("deploy")
        assert step is not None
        assert step["name"] == "deploy"
        assert step["status"] == RunStatus.RUNNING
        assert step["message"] == "deploying"

    def test_returns_updated_step(self, rc):
        """get_phase returns updated step after re-tracking."""
        rc.track_phase("build", "building")
        rc.track_phase("build", "done", RunStatus.SUCCESS)
        step = rc.get_phase("build")
        assert step is not None
        assert step["status"] == RunStatus.SUCCESS
        assert step["message"] == "done"

    def test_finds_correct_step_among_multiple(self, rc):
        """get_phase finds the correct step among many."""
        rc.track_phase("step1", "msg1")
        rc.track_phase("step2", "msg2")
        rc.track_phase("step3", "msg3")
        step = rc.get_phase("step2")
        assert step is not None
        assert step["name"] == "step2"


class TestCurrentPhase:
    """Tests for RunContext.current_phase property."""

    def test_returns_none_when_no_steps(self, rc):
        """current_phase is None when no steps tracked."""
        assert rc.current_phase is None

    def test_returns_last_added_step(self, rc):
        """current_phase returns the most recently added step."""
        rc.track_phase("step1", "first")
        rc.track_phase("step2", "second")
        assert rc.current_phase is not None
        assert rc.current_phase["name"] == "step2"

    def test_returns_same_as_last_in_workflow_steps(self, rc):
        """current_phase is the same object as workflow_steps[-1]."""
        rc.track_phase("s1", "m1")
        rc.track_phase("s2", "m2")
        assert rc.current_phase is rc.phases[-1]


class TestRunDuration:
    """Tests for RunContext.run_duration property."""

    def test_run_duration_is_positive_while_running(self, rc):
        """run_duration returns positive elapsed time while running."""
        # Small sleep to ensure measurable duration
        time.sleep(0.01)
        assert rc.run_duration > 0.0

    def test_run_duration_returns_final_duration_when_terminal(self, rc):
        """run_duration returns the final computed duration after terminal."""
        rc.track_run_status(RunStatus.SUCCESS)
        duration = rc.run_duration
        assert duration == rc.metadata["duration"]

    def test_run_duration_stable_after_terminal(self, rc):
        """run_duration doesn't change after reaching terminal state."""
        rc.track_run_status(RunStatus.SUCCESS)
        d1 = rc.run_duration
        time.sleep(0.01)
        d2 = rc.run_duration
        assert d1 == d2

    def test_run_duration_zero_if_no_start_time(self, mock_config, mock_logger):
        """run_duration returns 0.0 if start_time is None."""
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            metadata={"start_time": None},
        )
        assert run_ctx.run_duration == 0.0

    def test_run_duration_is_float(self, rc):
        """run_duration returns a float."""
        assert isinstance(rc.run_duration, float)
