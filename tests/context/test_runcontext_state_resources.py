"""Unit tests for RunContext state store, resources, run status getters, and workflow step access.

Tests task 6.5 additions:
- state property (lazy ScopeStore creation)
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
from functualize.job.context import (
    InvalidStateTransitionError,
    RunContext,
    RunStatus,
    inject_resource,
)
from tests.context.conftest import new_state_store


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
    """`rc.state` — the run's durable store.

    Rewritten when the in-memory tier was removed. The old contract was "a
    lazily-allocated per-context `ScopeStore`", which is precisely the
    behaviour that made a resumed run come back empty. The new one is: `State`,
    backed by the run's scope, and the *same object* a `state: State` parameter
    receives (ADR-021).
    """

    def test_state_returns_the_state_capability(self, rc):
        from functualize._engine.capabilities.state import State

        assert isinstance(rc.state, State)

    def test_state_same_instance_on_repeated_access(self, rc):
        """Repeated access is one object, not one per call."""
        assert rc.state is rc.state

    def test_state_is_functional_when_the_context_has_a_scope(
        self, mock_config, mock_logger
    ):
        from functualize._engine.capabilities.workflow_scope import WorkflowScope

        scope = WorkflowScope("s", state_store=new_state_store("s"))
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            _workflow_scope=scope,
        )
        run_ctx.state.set("counter", 42)
        assert run_ctx.state.get("counter") == 42

    def test_a_context_with_no_scope_says_so_rather_than_pretending(
        self, mock_config, mock_logger
    ):
        """No silent stand-in.

        A context built outside the engine has no scope and therefore nowhere
        durable to write. It raises on first use rather than accepting writes
        nothing will ever read — the failure this whole change removed.
        """
        from functualize._engine.capabilities.state import StateUnavailableError

        run_ctx = RunContext(name="test", config=mock_config, logger=mock_logger)
        with pytest.raises(StateUnavailableError):
            run_ctx.state.set("k", "v")


class TestResourcesProperty:
    """Tests for RunContext.resources property."""

    def test_resources_returns_mapping_proxy(self, rc):
        """resources property returns a MappingProxyType."""
        assert isinstance(rc.wiring.resources, MappingProxyType)

    def test_resources_empty_by_default(self, rc):
        """resources is empty when no resources injected."""
        assert len(rc.wiring.resources) == 0
        assert dict(rc.wiring.resources) == {}

    def test_resources_lazily_initialized(self, mock_config, mock_logger):
        """resources dict not allocated until first access."""
        run_ctx = RunContext(name="test", config=mock_config, logger=mock_logger)
        assert run_ctx._resources is None
        _ = run_ctx.wiring.resources
        assert run_ctx._resources is not None

    def test_resources_immutable_from_outside(self, rc):
        """Resources mapping cannot be mutated via the property."""
        with pytest.raises(TypeError):
            rc.wiring.resources["key"] = "value"  # type: ignore[index]

    def test_resources_with_provided_dict(self, mock_config, mock_logger):
        """If resources dict provided in constructor, it is used."""
        resources = {"db": object()}
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            resources=resources,
        )
        assert "db" in run_ctx.wiring.resources


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
        result = run_ctx.wiring.get_resource("db", DBClient)
        assert result is client

    def test_get_resource_raises_key_error_missing(self, rc):
        """get_resource raises KeyError for unknown resource name."""
        with pytest.raises(KeyError, match="not found"):
            rc.wiring.get_resource("missing", str)

    def test_get_resource_key_error_lists_available(self, mock_config, mock_logger):
        """KeyError message lists available resources."""
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            resources={"db": "client", "cache": "redis"},
        )
        with pytest.raises(KeyError, match="Available"):
            run_ctx.wiring.get_resource("missing", str)

    def test_get_resource_raises_type_error_mismatch(self, mock_config, mock_logger):
        """get_resource raises TypeError when type doesn't match."""
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            resources={"db": "not-a-dict"},
        )
        with pytest.raises(TypeError, match="expected dict"):
            run_ctx.wiring.get_resource("db", dict)

    def test_get_resource_type_error_message(self, mock_config, mock_logger):
        """TypeError message identifies resource name, expected and actual type."""
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            resources={"counter": "hello"},
        )
        with pytest.raises(TypeError, match="counter.*expected int.*got str"):
            run_ctx.wiring.get_resource("counter", int)


class TestInjectResource:
    """Tests for inject_resource() utility function."""

    def test_inject_resource_adds_to_resources(self, rc):
        """inject_resource makes resource accessible via get_resource."""
        inject_resource(rc, "db", {"host": "localhost"})
        result = rc.wiring.get_resource("db", dict)
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
        assert "cache" in rc.wiring.resources
        assert rc.wiring.resources["cache"] == [1, 2, 3]

    def test_inject_resource_overwrites_existing(self, rc):
        """inject_resource can overwrite an existing resource."""
        inject_resource(rc, "db", "old")
        inject_resource(rc, "db", "new")
        assert rc.wiring.get_resource("db", str) == "new"


class TestRunStatusProperty:
    """Tests for RunContext.run_status read-only property."""

    def test_initial_run_status_is_running(self, rc):
        """run_status is RUNNING on fresh RunContext."""
        assert rc.events.run_status == RunStatus.RUNNING

    def test_run_status_reflects_track_run_status(self, rc):
        """run_status property reflects changes made via track_run_status."""
        rc.events.track_run_status(RunStatus.SUCCESS)
        assert rc.events.run_status == RunStatus.SUCCESS

    def test_run_status_is_enum_type(self, rc):
        """run_status returns a RunStatus enum value."""
        assert isinstance(rc.events.run_status, RunStatus)


class TestSetRunStatus:
    """Tests for RunContext.set_run_status() method."""

    def test_set_run_status_updates_status(self, rc):
        """set_run_status updates the run_status property."""
        rc.events.set_run_status(RunStatus.SUCCESS)
        assert rc.events.run_status == RunStatus.SUCCESS

    def test_set_run_status_raises_on_terminal(self, rc):
        """set_run_status raises InvalidStateTransitionError from terminal state."""
        rc.events.set_run_status(RunStatus.SUCCESS)
        with pytest.raises(InvalidStateTransitionError):
            rc.events.set_run_status(RunStatus.FAILURE)

    def test_set_run_status_invokes_callbacks(self, rc):
        """set_run_status invokes registered status callbacks."""
        callback = MagicMock()
        rc._status_callbacks = [callback]
        rc.events.set_run_status(RunStatus.SUCCESS, "done")
        callback.assert_called_once_with(RunStatus.RUNNING, RunStatus.SUCCESS, "done")

    def test_set_run_status_callback_error_does_not_prevent_transition(
        self, rc, mock_logger
    ):
        """Callback exceptions don't prevent the status transition."""

        def bad_callback(old, new, msg):
            raise ValueError("callback error")

        rc._status_callbacks = [bad_callback]
        rc.events.set_run_status(RunStatus.SUCCESS)
        assert rc.events.run_status == RunStatus.SUCCESS
        mock_logger.warning.assert_called()

    def test_set_run_status_backward_compat_with_track_run_status(self, rc):
        """set_run_status calls track_run_status internally."""
        rc.events.set_run_status(RunStatus.FAILURE, "oops")
        assert rc.metadata["run_status"] == RunStatus.FAILURE
        assert rc.metadata["end_time"] is not None
        assert rc.metadata["duration"] is not None

    def test_track_run_status_still_works_independently(self, rc):
        """track_run_status remains functional (backward compat)."""
        rc.events.track_run_status(run_status=RunStatus.SUCCESS, failure_message="")
        assert rc.events.run_status == RunStatus.SUCCESS


class TestGetPhase:
    """Tests for RunContext.get_phase() method."""

    def test_returns_none_for_untracked_step(self, rc):
        """get_phase returns None for unknown step name."""
        assert rc.events.get_phase("nonexistent") is None

    def test_returns_step_dict_for_tracked_step(self, rc):
        """get_phase returns the step dict for a tracked step."""
        rc.events.track_phase("deploy", "deploying", RunStatus.RUNNING)
        step = rc.events.get_phase("deploy")
        assert step is not None
        assert step["name"] == "deploy"
        assert step["status"] == RunStatus.RUNNING
        assert step["message"] == "deploying"

    def test_returns_updated_step(self, rc):
        """get_phase returns updated step after re-tracking."""
        rc.events.track_phase("build", "building")
        rc.events.track_phase("build", "done", RunStatus.SUCCESS)
        step = rc.events.get_phase("build")
        assert step is not None
        assert step["status"] == RunStatus.SUCCESS
        assert step["message"] == "done"

    def test_finds_correct_step_among_multiple(self, rc):
        """get_phase finds the correct step among many."""
        rc.events.track_phase("step1", "msg1")
        rc.events.track_phase("step2", "msg2")
        rc.events.track_phase("step3", "msg3")
        step = rc.events.get_phase("step2")
        assert step is not None
        assert step["name"] == "step2"


class TestCurrentPhase:
    """Tests for RunContext.current_phase property."""

    def test_returns_none_when_no_steps(self, rc):
        """current_phase is None when no steps tracked."""
        assert rc.events.current_phase is None

    def test_returns_last_added_step(self, rc):
        """current_phase returns the most recently added step."""
        rc.events.track_phase("step1", "first")
        rc.events.track_phase("step2", "second")
        assert rc.events.current_phase is not None
        assert rc.events.current_phase["name"] == "step2"

    def test_returns_same_as_last_in_workflow_steps(self, rc):
        """current_phase is the same object as workflow_steps[-1]."""
        rc.events.track_phase("s1", "m1")
        rc.events.track_phase("s2", "m2")
        assert rc.events.current_phase is rc.events.phases[-1]


class TestRunDuration:
    """Tests for RunContext.run_duration property."""

    def test_run_duration_is_positive_while_running(self, rc):
        """run_duration returns positive elapsed time while running."""
        # Small sleep to ensure measurable duration
        time.sleep(0.01)
        assert rc.events.run_duration > 0.0

    def test_run_duration_returns_final_duration_when_terminal(self, rc):
        """run_duration returns the final computed duration after terminal."""
        rc.events.track_run_status(RunStatus.SUCCESS)
        duration = rc.events.run_duration
        assert duration == rc.metadata["duration"]

    def test_run_duration_stable_after_terminal(self, rc):
        """run_duration doesn't change after reaching terminal state."""
        rc.events.track_run_status(RunStatus.SUCCESS)
        d1 = rc.events.run_duration
        time.sleep(0.01)
        d2 = rc.events.run_duration
        assert d1 == d2

    def test_run_duration_zero_if_no_start_time(self, mock_config, mock_logger):
        """run_duration returns 0.0 if start_time is None."""
        run_ctx = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            metadata={"start_time": None},
        )
        assert run_ctx.events.run_duration == 0.0

    def test_run_duration_is_float(self, rc):
        """run_duration returns a float."""
        assert isinstance(rc.events.run_duration, float)
