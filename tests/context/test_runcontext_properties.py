"""Property-based tests for RunContext class.

Tests Properties 9, 11, and 12 from the design document.
Validates: Requirements 5.1, 5.4, 5.5, 5.6, 5.7
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize.job.context import (
    InvalidStateTransitionError,
    RunContext,
    RunStatus,
    RunType,
)

# --- Strategies ---

# Strategy for valid job names
job_names = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd")),
    min_size=1,
    max_size=30,
)

# Strategy for RunType values
run_types = st.sampled_from(list(RunType))

# Strategy for terminal statuses
terminal_statuses = st.sampled_from(
    [RunStatus.SUCCESS, RunStatus.FAILURE, RunStatus.CANCELLED, RunStatus.TIMEOUT]
)

# Strategy for distinct step names
step_names = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd")),
    min_size=1,
    max_size=50,
)

# Strategy for step messages (including ones that exceed 1000 chars)
step_messages = st.text(min_size=0, max_size=2000)

# Strategy for step statuses
step_statuses = st.sampled_from(list(RunStatus))

# Strategy for optional metadata dicts
metadata_values = st.fixed_dictionaries(
    {},
    optional={
        "custom_key": st.text(min_size=1, max_size=20),
    },
)


# --- Helpers ---


def make_run_context(
    name: str = "test-job",
    run_type: RunType | None = None,
    metadata: dict | None = None,
) -> RunContext:
    """Create a RunContext with mocked dependencies."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock()
    meta = metadata.copy() if metadata else {}
    if run_type is not None:
        meta["run_type"] = run_type
    return RunContext(name=name, config=mock_config, logger=mock_logger, metadata=meta)


# Feature: functualize, Property 9: RunContext Initial State
# For any job invocation, the constructed RunContext SHALL have run_status set
# to RUNNING, start_time set to the current UTC time (within 1 second tolerance),
# run_type matching the invocation context, and end_time and duration set to None.
# Validates: Requirements 5.1, 5.4
class TestRunContextInitialState:
    """Property 9: RunContext Initial State."""

    @given(name=job_names, run_type=run_types)
    def test_initial_run_status_is_running(self, name: str, run_type: RunType):
        """For any job invocation, run_status is RUNNING."""
        # Feature: functualize, Property 9: RunContext Initial State
        # **Validates: Requirements 5.1, 5.4**
        rc = make_run_context(name=name, run_type=run_type)
        assert rc.metadata["run_status"] == RunStatus.RUNNING

    @given(name=job_names, run_type=run_types)
    def test_initial_start_time_within_tolerance(self, name: str, run_type: RunType):
        """For any job invocation, start_time is current UTC time within 1 second."""
        # Feature: functualize, Property 9: RunContext Initial State
        # **Validates: Requirements 5.1, 5.4**
        before = datetime.now(UTC)
        rc = make_run_context(name=name, run_type=run_type)
        after = datetime.now(UTC)

        start_time = rc.metadata["start_time"]
        assert start_time is not None
        assert start_time.tzinfo == UTC
        # start_time should be between before and after (within tolerance)
        assert (start_time - before).total_seconds() >= -1.0
        assert (after - start_time).total_seconds() >= -1.0
        assert abs((after - start_time).total_seconds()) < 1.0

    @given(name=job_names, run_type=run_types)
    def test_initial_run_type_matches_invocation(self, name: str, run_type: RunType):
        """For any job invocation, run_type matches the provided invocation context."""
        # Feature: functualize, Property 9: RunContext Initial State
        # **Validates: Requirements 5.1, 5.4**
        rc = make_run_context(name=name, run_type=run_type)
        assert rc.metadata["run_type"] == run_type

    @given(name=job_names, run_type=run_types)
    def test_initial_end_time_is_none(self, name: str, run_type: RunType):
        """For any job invocation, end_time is None."""
        # Feature: functualize, Property 9: RunContext Initial State
        # **Validates: Requirements 5.1, 5.4**
        rc = make_run_context(name=name, run_type=run_type)
        assert rc.metadata["end_time"] is None

    @given(name=job_names, run_type=run_types)
    def test_initial_duration_is_none(self, name: str, run_type: RunType):
        """For any job invocation, duration is None."""
        # Feature: functualize, Property 9: RunContext Initial State
        # **Validates: Requirements 5.1, 5.4**
        rc = make_run_context(name=name, run_type=run_type)
        assert rc.metadata["duration"] is None


# Feature: functualize, Property 11: Workflow Step Tracking
# For any sequence of track_phase calls with distinct step names, the
# workflow_steps property SHALL return steps in the order they were first tracked,
# each containing the correct name, latest status, message (truncated to 1000 chars),
# and timing information.
# Validates: Requirements 5.5
class TestJobPhaseTracking:
    """Property 11: Workflow Step Tracking."""

    @given(
        steps=st.lists(
            st.tuples(step_names, step_messages, step_statuses),
            min_size=1,
            max_size=10,
            unique_by=lambda x: x[0],  # distinct step names
        ),
    )
    def test_steps_returned_in_first_tracked_order(
        self, steps: list[tuple[str, str, RunStatus]]
    ):
        """Steps are returned in the order they were first tracked."""
        # Feature: functualize, Property 11: Workflow Step Tracking
        # **Validates: Requirements 5.5**
        rc = make_run_context()
        for step_name, step_message, step_status in steps:
            rc.track_phase(step_name, step_message, step_status)

        tracked_names = [s["name"] for s in rc.phases]
        expected_names = [s[0] for s in steps]
        assert tracked_names == expected_names

    @given(
        steps=st.lists(
            st.tuples(step_names, step_messages, step_statuses),
            min_size=1,
            max_size=10,
            unique_by=lambda x: x[0],
        ),
    )
    def test_steps_contain_correct_name_and_status(
        self, steps: list[tuple[str, str, RunStatus]]
    ):
        """Each step contains the correct name and latest status."""
        # Feature: functualize, Property 11: Workflow Step Tracking
        # **Validates: Requirements 5.5**
        rc = make_run_context()
        for step_name, step_message, step_status in steps:
            rc.track_phase(step_name, step_message, step_status)

        for i, (step_name, _step_message, step_status) in enumerate(steps):
            tracked = rc.phases[i]
            assert tracked["name"] == step_name
            assert tracked["status"] == step_status

    @given(
        step_name=step_names,
        message=st.text(min_size=1001, max_size=2000),
        status=step_statuses,
    )
    def test_message_truncated_to_1000_chars(
        self, step_name: str, message: str, status: RunStatus
    ):
        """Messages longer than 1000 chars are truncated to exactly 1000."""
        # Feature: functualize, Property 11: Workflow Step Tracking
        # **Validates: Requirements 5.5**
        rc = make_run_context()
        rc.track_phase(step_name, message, status)

        tracked = rc.phases[0]
        assert len(tracked["message"]) == 1000
        assert tracked["message"] == message[:1000]

    @given(
        step_name=step_names,
        message=st.text(min_size=0, max_size=1000),
        status=step_statuses,
    )
    def test_message_within_limit_preserved(
        self, step_name: str, message: str, status: RunStatus
    ):
        """Messages within 1000 chars are preserved exactly."""
        # Feature: functualize, Property 11: Workflow Step Tracking
        # **Validates: Requirements 5.5**
        rc = make_run_context()
        rc.track_phase(step_name, message, status)

        tracked = rc.phases[0]
        assert tracked["message"] == message

    @given(
        steps=st.lists(
            st.tuples(step_names, step_messages, step_statuses),
            min_size=1,
            max_size=10,
            unique_by=lambda x: x[0],
        ),
    )
    def test_steps_have_timing_information(
        self, steps: list[tuple[str, str, RunStatus]]
    ):
        """Each tracked step has start_time set to a UTC datetime."""
        # Feature: functualize, Property 11: Workflow Step Tracking
        # **Validates: Requirements 5.5**
        rc = make_run_context()
        for step_name, step_message, step_status in steps:
            rc.track_phase(step_name, step_message, step_status)

        for tracked in rc.phases:
            assert tracked["start_time"] is not None
            assert tracked["start_time"].tzinfo == UTC

    @given(
        step_name=step_names,
        initial_message=step_messages,
        updated_message=step_messages,
        updated_status=step_statuses,
    )
    def test_update_existing_step_preserves_order(
        self,
        step_name: str,
        initial_message: str,
        updated_message: str,
        updated_status: RunStatus,
    ):
        """Updating an existing step updates status/message but preserves order."""
        # Feature: functualize, Property 11: Workflow Step Tracking
        # **Validates: Requirements 5.5**
        rc = make_run_context()
        rc.track_phase(step_name, initial_message, RunStatus.RUNNING)
        rc.track_phase(step_name, updated_message, updated_status)

        assert len(rc.phases) == 1
        tracked = rc.phases[0]
        assert tracked["name"] == step_name
        assert tracked["status"] == updated_status
        assert tracked["message"] == updated_message[:1000]


# Feature: functualize, Property 12: Terminal Status Transition
# For any RunContext in RUNNING state, calling track_run_status with a terminal
# status (SUCCESS, FAILURE, CANCELLED, TIMEOUT) SHALL set end_time to current
# UTC time and compute duration as the difference from start_time. Calling
# track_run_status again with any terminal status SHALL raise InvalidStateTransitionError.
# Validates: Requirements 5.6, 5.7
class TestTerminalStatusTransition:
    """Property 12: Terminal Status Transition."""

    @given(name=job_names, terminal_status=terminal_statuses)
    def test_terminal_transition_sets_end_time(
        self, name: str, terminal_status: RunStatus
    ):
        """Transitioning to terminal status sets end_time to current UTC time."""
        # Feature: functualize, Property 12: Terminal Status Transition
        # **Validates: Requirements 5.6, 5.7**
        rc = make_run_context(name=name)
        before = datetime.now(UTC)
        rc.track_run_status(terminal_status)
        after = datetime.now(UTC)

        end_time = rc.metadata["end_time"]
        assert end_time is not None
        assert end_time.tzinfo == UTC
        assert (end_time - before).total_seconds() >= -0.01
        assert (after - end_time).total_seconds() >= -0.01

    @given(name=job_names, terminal_status=terminal_statuses)
    def test_terminal_transition_computes_duration(
        self, name: str, terminal_status: RunStatus
    ):
        """Transitioning to terminal status computes duration from start_time."""
        # Feature: functualize, Property 12: Terminal Status Transition
        # **Validates: Requirements 5.6, 5.7**
        rc = make_run_context(name=name)
        rc.track_run_status(terminal_status)

        duration = rc.metadata["duration"]
        assert duration is not None
        assert isinstance(duration, float)
        assert duration >= 0.0

        # Duration should equal end_time - start_time
        expected_duration = (
            rc.metadata["end_time"] - rc.metadata["start_time"]
        ).total_seconds()
        assert abs(duration - expected_duration) < 0.001

    @given(
        name=job_names,
        first_terminal=terminal_statuses,
        second_terminal=terminal_statuses,
    )
    def test_second_terminal_transition_raises(
        self, name: str, first_terminal: RunStatus, second_terminal: RunStatus
    ):
        """Calling track_run_status again after terminal raises InvalidStateTransitionError."""
        # Feature: functualize, Property 12: Terminal Status Transition
        # **Validates: Requirements 5.6, 5.7**
        rc = make_run_context(name=name)
        rc.track_run_status(first_terminal)

        with pytest.raises(InvalidStateTransitionError):
            rc.track_run_status(second_terminal)

    @given(name=job_names, terminal_status=terminal_statuses)
    def test_terminal_transition_updates_run_status(
        self, name: str, terminal_status: RunStatus
    ):
        """Transitioning to terminal status updates run_status in metadata."""
        # Feature: functualize, Property 12: Terminal Status Transition
        # **Validates: Requirements 5.6, 5.7**
        rc = make_run_context(name=name)
        rc.track_run_status(terminal_status)

        assert rc.metadata["run_status"] == terminal_status

    @given(
        name=job_names,
        first_terminal=terminal_statuses,
        non_terminal=st.sampled_from([RunStatus.RUNNING, RunStatus.UNKNOWN]),
    )
    def test_any_transition_from_terminal_raises(
        self, name: str, first_terminal: RunStatus, non_terminal: RunStatus
    ):
        """Any transition from a terminal state raises InvalidStateTransitionError."""
        # Feature: functualize, Property 12: Terminal Status Transition
        # **Validates: Requirements 5.6, 5.7**
        rc = make_run_context(name=name)
        rc.track_run_status(first_terminal)

        with pytest.raises(InvalidStateTransitionError):
            rc.track_run_status(non_terminal)
