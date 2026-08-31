"""Unit tests for RunContext, RunStatus, RunType, and related types."""

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from functualize._config.job_config import JobConfigView
from functualize.job.context import (
    _TERMINAL_STATES,
    InvalidStateTransitionError,
    RunContext,
    RunStatus,
    RunType,
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
def run_context(mock_config, mock_logger):
    """Create a RunContext instance for testing."""
    return RunContext(name="test-job", config=mock_config, logger=mock_logger)


class TestRunStatus:
    """Tests for RunStatus enum."""

    def test_values(self):
        assert RunStatus.SUCCESS.value == "Success"
        assert RunStatus.FAILURE.value == "Failure"
        assert RunStatus.BLOCKED.value == "Blocked"
        assert RunStatus.SKIPPED.value == "Skipped"
        assert RunStatus.RUNNING.value == "Running"
        assert RunStatus.CANCELLED.value == "Cancelled"
        assert RunStatus.TIMEOUT.value == "Timeout"
        assert RunStatus.UNKNOWN.value == "Unknown"

    def test_all_members(self):
        assert len(RunStatus) == 9
        assert RunStatus.REFUSED.value == "Refused"

    def test_only_success_counts_as_having_run(self):
        """SKIPPED is not a failure — a guard or a fresh fingerprint answered
        "no work to do". It is not SUCCESS either: a caller that conflates them
        cannot tell a build that ran from one already current."""
        assert [s for s in RunStatus if s.ran] == [RunStatus.SUCCESS]

    def test_only_blocked_is_resumable(self):
        """BLOCKED is a declared pause, not an error — the distinction CI and
        the TUI need so a gate-paused workflow does not read as a crash."""
        assert [s for s in RunStatus if s.resumable] == [RunStatus.BLOCKED]

    def test_terminal_states(self):
        assert RunStatus.SUCCESS in _TERMINAL_STATES
        assert RunStatus.FAILURE in _TERMINAL_STATES
        assert RunStatus.CANCELLED in _TERMINAL_STATES
        assert RunStatus.TIMEOUT in _TERMINAL_STATES
        assert RunStatus.RUNNING not in _TERMINAL_STATES
        assert RunStatus.UNKNOWN not in _TERMINAL_STATES


class TestRunType:
    """Tests for RunType enum."""

    def test_values(self):
        assert RunType.JOB.value == "job"
        assert RunType.COMMAND.value == "command"
        assert RunType.RUN.value == "run"

    def test_all_members(self):
        assert len(RunType) == 3


class TestInvalidStateTransitionError:
    """Tests for InvalidStateTransitionError exception."""

    def test_is_exception(self):
        assert issubclass(InvalidStateTransitionError, Exception)

    def test_can_be_raised_with_message(self):
        with pytest.raises(InvalidStateTransitionError, match="cannot transition"):
            raise InvalidStateTransitionError("cannot transition")


class TestRunContextInit:
    """Tests for RunContext initialization."""

    def test_initial_status_is_running(self, run_context):
        assert run_context.metadata["run_status"] == RunStatus.RUNNING

    def test_initial_run_type_is_job(self, run_context):
        assert run_context.metadata["run_type"] == RunType.JOB

    def test_initial_start_time_is_utc(self, run_context):
        start_time = run_context.metadata["start_time"]
        assert start_time is not None
        assert start_time.tzinfo == UTC
        # Should be within 1 second of now
        now = datetime.now(UTC)
        assert abs((now - start_time).total_seconds()) < 1.0

    def test_initial_end_time_is_none(self, run_context):
        assert run_context.metadata["end_time"] is None

    def test_initial_duration_is_none(self, run_context):
        assert run_context.metadata["duration"] is None

    def test_initial_workflow_steps_empty(self, run_context):
        assert run_context.phases == []

    def test_initial_job_config_is_none(self, run_context):
        assert run_context.job_config is None

    def test_name_property(self, run_context):
        assert run_context.name == "test-job"

    def test_config_property(self, run_context, mock_config):
        assert run_context.config is mock_config

    def test_config_set_prefix_called(self, mock_config, mock_logger):
        RunContext(name="my-job", config=mock_config, logger=mock_logger)
        mock_config.set_prefix.assert_called_once_with("my-job")

    def test_custom_metadata_preserved(self, mock_config, mock_logger):
        rc = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            metadata={"custom_key": "custom_value"},
        )
        assert rc.metadata["custom_key"] == "custom_value"
        # Defaults still set
        assert rc.metadata["run_status"] == RunStatus.RUNNING

    def test_metadata_does_not_override_provided_values(self, mock_config, mock_logger):
        rc = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            metadata={"run_type": RunType.COMMAND},
        )
        assert rc.metadata["run_type"] == RunType.COMMAND


class TestRunContextLog:
    """Tests for RunContext.log() method."""

    def test_log_info(self, run_context, mock_logger):
        run_context.log("hello")
        mock_logger.info.assert_called_once_with("hello")

    def test_log_debug(self, run_context, mock_logger):
        run_context.log("debug msg", level="debug")
        mock_logger.debug.assert_called_once_with("debug msg")

    def test_log_warning(self, run_context, mock_logger):
        run_context.log("warn msg", level="warning")
        mock_logger.warning.assert_called_once_with("warn msg")

    def test_log_error(self, run_context, mock_logger):
        run_context.log("error msg", level="error")
        mock_logger.error.assert_called_once_with("error msg")

    def test_log_critical(self, run_context, mock_logger):
        run_context.log("critical msg", level="critical")
        mock_logger.critical.assert_called_once_with("critical msg")

    def test_log_invalid_level_raises(self, run_context):
        with pytest.raises(ValueError, match="Invalid log level"):
            run_context.log("msg", level="nonexistent")

    def test_log_invalid_level_raises_before_emitting(self, run_context, mock_logger):
        """The level is rejected before anything reaches the sink."""
        with pytest.raises(ValueError, match="Invalid log level"):
            run_context.log("msg", level="exception")
        mock_logger.exception.assert_not_called()


class TestTrackRunStatus:
    """Tests for RunContext.track_run_status() method."""

    def test_transition_to_success(self, run_context):
        run_context.track_run_status(RunStatus.SUCCESS)
        assert run_context.metadata["run_status"] == RunStatus.SUCCESS
        assert run_context.metadata["end_time"] is not None
        assert run_context.metadata["duration"] is not None
        assert run_context.metadata["duration"] >= 0.0

    def test_transition_to_failure(self, run_context):
        run_context.track_run_status(RunStatus.FAILURE, failure_message="oops")
        assert run_context.metadata["run_status"] == RunStatus.FAILURE
        assert run_context.metadata["end_time"] is not None

    def test_transition_to_cancelled(self, run_context):
        run_context.track_run_status(RunStatus.CANCELLED)
        assert run_context.metadata["run_status"] == RunStatus.CANCELLED
        assert run_context.metadata["end_time"] is not None

    def test_transition_to_timeout(self, run_context):
        run_context.track_run_status(RunStatus.TIMEOUT)
        assert run_context.metadata["run_status"] == RunStatus.TIMEOUT
        assert run_context.metadata["end_time"] is not None

    def test_raises_on_terminal_to_terminal(self, run_context):
        run_context.track_run_status(RunStatus.SUCCESS)
        with pytest.raises(InvalidStateTransitionError):
            run_context.track_run_status(RunStatus.FAILURE)

    def test_raises_on_terminal_to_running(self, run_context):
        run_context.track_run_status(RunStatus.FAILURE)
        with pytest.raises(InvalidStateTransitionError):
            run_context.track_run_status(RunStatus.RUNNING)

    def test_running_to_running_allowed(self, run_context):
        # Should not raise
        run_context.track_run_status(RunStatus.RUNNING)
        assert run_context.metadata["run_status"] == RunStatus.RUNNING
        assert run_context.metadata["end_time"] is None

    def test_end_time_is_utc(self, run_context):
        run_context.track_run_status(RunStatus.SUCCESS)
        end_time = run_context.metadata["end_time"]
        assert end_time.tzinfo == UTC

    def test_duration_is_positive(self, run_context):
        run_context.track_run_status(RunStatus.SUCCESS)
        assert run_context.metadata["duration"] >= 0.0


class TestTrackPhase:
    """Tests for RunContext.track_phase() method."""

    def test_add_new_step(self, run_context):
        run_context.track_phase("step1", "Starting step 1")
        assert len(run_context.phases) == 1
        step = run_context.phases[0]
        assert step["name"] == "step1"
        assert step["status"] == RunStatus.RUNNING
        assert step["message"] == "Starting step 1"
        assert step["start_time"] is not None
        assert step["end_time"] is None
        assert step["duration"] is None

    def test_update_existing_step(self, run_context):
        run_context.track_phase("step1", "Starting")
        run_context.track_phase("step1", "Done", RunStatus.SUCCESS)
        assert len(run_context.phases) == 1
        step = run_context.phases[0]
        assert step["status"] == RunStatus.SUCCESS
        assert step["message"] == "Done"
        assert step["end_time"] is not None
        assert step["duration"] is not None
        assert step["duration"] >= 0.0

    def test_steps_ordered_by_first_appearance(self, run_context):
        run_context.track_phase("step1", "First")
        run_context.track_phase("step2", "Second")
        run_context.track_phase("step3", "Third")
        names = [s["name"] for s in run_context.phases]
        assert names == ["step1", "step2", "step3"]

    def test_message_truncated_to_1000_chars(self, run_context):
        long_message = "x" * 2000
        run_context.track_phase("step1", long_message)
        step = run_context.phases[0]
        assert len(step["message"]) == 1000

    def test_message_exactly_1000_not_truncated(self, run_context):
        message = "a" * 1000
        run_context.track_phase("step1", message)
        step = run_context.phases[0]
        assert step["message"] == message

    def test_multiple_steps_independent(self, run_context):
        run_context.track_phase("step1", "msg1")
        run_context.track_phase("step2", "msg2")
        run_context.track_phase("step1", "updated", RunStatus.SUCCESS)
        assert run_context.phases[0]["status"] == RunStatus.SUCCESS
        assert run_context.phases[1]["status"] == RunStatus.RUNNING

    def test_step_start_time_is_utc(self, run_context):
        run_context.track_phase("step1", "msg")
        step = run_context.phases[0]
        assert step["start_time"].tzinfo == UTC


class TestRunContextJobConfig:
    """Tests for RunContext.job_config property."""

    def test_set_and_get_job_config(self, run_context):
        config_obj = {"key": "value"}
        run_context.job_config = config_obj
        assert run_context.job_config is config_obj
