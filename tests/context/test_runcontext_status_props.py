"""Property-based tests for Run Status State Machine.

Property 14: Run Status State Machine
Validates: Requirements 8.2, 8.3

Tests that:
- set_run_status updates run_status property to the new value
- From RUNNING state, transitioning to any terminal state succeeds
- From any terminal state, transitioning to any other state raises InvalidStateTransitionError
- track_run_status (backward compat) behaves identically to set_run_status for state machine rules
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize.job.context import (
    InvalidStateTransitionError,
    RunContext,
    RunStatus,
)

# --- Strategies ---

# All RunStatus values
all_statuses = st.sampled_from(list(RunStatus))

# Terminal states: cannot be transitioned from
terminal_statuses = st.sampled_from(
    [RunStatus.SUCCESS, RunStatus.FAILURE, RunStatus.CANCELLED, RunStatus.TIMEOUT]
)

# Non-terminal states (can still be transitioned from)
non_terminal_statuses = st.sampled_from([RunStatus.RUNNING, RunStatus.UNKNOWN])


# --- Helpers ---


def make_run_context(name: str = "test-job") -> RunContext:
    """Create a RunContext with mocked dependencies in RUNNING state."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock()
    return RunContext(name=name, config=mock_config, logger=mock_logger)


# Feature: enriched-runcontext, Property 14: Run Status State Machine
# **Validates: Requirements 8.2, 8.3**
class TestSetRunStatusUpdatesProperty:
    """set_run_status updates run_status property to the new value."""

    @given(target_status=terminal_statuses)
    @settings(max_examples=50)
    def test_set_run_status_updates_to_terminal(self, target_status: RunStatus) -> None:
        """set_run_status sets run_status property to the target terminal value.

        **Validates: Requirements 8.2**
        """
        rc = make_run_context()
        rc.set_run_status(target_status)
        assert rc.run_status == target_status

    @given(target_status=non_terminal_statuses)
    @settings(max_examples=50)
    def test_set_run_status_updates_to_non_terminal(
        self, target_status: RunStatus
    ) -> None:
        """set_run_status sets run_status property to the target non-terminal value.

        **Validates: Requirements 8.2**
        """
        rc = make_run_context()
        rc.set_run_status(target_status)
        assert rc.run_status == target_status


class TestRunningToTerminalSucceeds:
    """From RUNNING state, transitioning to any terminal state succeeds."""

    @given(terminal=terminal_statuses)
    @settings(max_examples=50)
    def test_running_to_terminal_does_not_raise(self, terminal: RunStatus) -> None:
        """From RUNNING, transitioning to any terminal state succeeds without error.

        **Validates: Requirements 8.2**
        """
        rc = make_run_context()
        assert rc.run_status == RunStatus.RUNNING
        # Should not raise
        rc.set_run_status(terminal)
        assert rc.run_status == terminal

    @given(terminal=terminal_statuses, message=st.text(max_size=100))
    @settings(max_examples=50)
    def test_running_to_terminal_with_message(
        self, terminal: RunStatus, message: str
    ) -> None:
        """From RUNNING, transitioning with a message succeeds and updates status.

        **Validates: Requirements 8.2**
        """
        rc = make_run_context()
        rc.set_run_status(terminal, message)
        assert rc.run_status == terminal


class TestTerminalToAnyRaises:
    """From any terminal state, transitioning to any other state raises InvalidStateTransitionError."""

    @given(
        first_terminal=terminal_statuses,
        second_status=all_statuses,
    )
    @settings(max_examples=100)
    def test_terminal_to_any_status_raises(
        self, first_terminal: RunStatus, second_status: RunStatus
    ) -> None:
        """From a terminal state, any transition raises InvalidStateTransitionError.

        **Validates: Requirements 8.2, 8.3**
        """
        rc = make_run_context()
        rc.set_run_status(first_terminal)
        with pytest.raises(InvalidStateTransitionError):
            rc.set_run_status(second_status)

    @given(
        first_terminal=terminal_statuses,
        second_terminal=terminal_statuses,
    )
    @settings(max_examples=50)
    def test_terminal_to_terminal_raises(
        self, first_terminal: RunStatus, second_terminal: RunStatus
    ) -> None:
        """From terminal, transitioning to another terminal raises.

        **Validates: Requirements 8.2, 8.3**
        """
        rc = make_run_context()
        rc.set_run_status(first_terminal)
        with pytest.raises(InvalidStateTransitionError):
            rc.set_run_status(second_terminal)

    @given(
        first_terminal=terminal_statuses,
        non_terminal=non_terminal_statuses,
    )
    @settings(max_examples=50)
    def test_terminal_to_non_terminal_raises(
        self, first_terminal: RunStatus, non_terminal: RunStatus
    ) -> None:
        """From terminal, transitioning to a non-terminal state also raises.

        **Validates: Requirements 8.2, 8.3**
        """
        rc = make_run_context()
        rc.set_run_status(first_terminal)
        with pytest.raises(InvalidStateTransitionError):
            rc.set_run_status(non_terminal)


class TestTrackRunStatusBackwardCompat:
    """track_run_status (backward compat) behaves identically to set_run_status for state machine rules."""

    @given(terminal=terminal_statuses)
    @settings(max_examples=50)
    def test_track_run_status_from_running_succeeds(self, terminal: RunStatus) -> None:
        """track_run_status from RUNNING to terminal succeeds like set_run_status.

        **Validates: Requirements 8.3**
        """
        rc = make_run_context()
        rc.track_run_status(run_status=terminal)
        assert rc.run_status == terminal

    @given(
        first_terminal=terminal_statuses,
        second_status=all_statuses,
    )
    @settings(max_examples=100)
    def test_track_run_status_from_terminal_raises(
        self, first_terminal: RunStatus, second_status: RunStatus
    ) -> None:
        """track_run_status from terminal raises InvalidStateTransitionError just like set_run_status.

        **Validates: Requirements 8.3**
        """
        rc = make_run_context()
        rc.track_run_status(run_status=first_terminal)
        with pytest.raises(InvalidStateTransitionError):
            rc.track_run_status(run_status=second_status)

    @given(target_status=all_statuses)
    @settings(max_examples=50)
    def test_track_run_status_and_set_run_status_agree_on_state_machine(
        self, target_status: RunStatus
    ) -> None:
        """Both methods enforce the same state machine: from RUNNING, same outcomes.

        **Validates: Requirements 8.2, 8.3**
        """
        # Test with set_run_status
        rc1 = make_run_context()
        exc1: Exception | None = None
        try:
            rc1.set_run_status(target_status)
        except InvalidStateTransitionError as e:
            exc1 = e

        # Test with track_run_status
        rc2 = make_run_context()
        exc2: Exception | None = None
        try:
            rc2.track_run_status(run_status=target_status)
        except InvalidStateTransitionError as e:
            exc2 = e

        # Both should agree on whether the transition is valid
        assert (exc1 is None) == (exc2 is None)

        # If both succeeded, resulting status should match
        if exc1 is None and exc2 is None:
            assert rc1.run_status == rc2.run_status == target_status

    @given(
        first_terminal=terminal_statuses,
        second_status=all_statuses,
    )
    @settings(max_examples=50)
    def test_both_methods_agree_from_terminal_state(
        self, first_terminal: RunStatus, second_status: RunStatus
    ) -> None:
        """Both methods raise InvalidStateTransitionError from a terminal state.

        **Validates: Requirements 8.2, 8.3**
        """
        # set_run_status path
        rc1 = make_run_context()
        rc1.set_run_status(first_terminal)
        with pytest.raises(InvalidStateTransitionError):
            rc1.set_run_status(second_status)

        # track_run_status path
        rc2 = make_run_context()
        rc2.track_run_status(run_status=first_terminal)
        with pytest.raises(InvalidStateTransitionError):
            rc2.track_run_status(run_status=second_status)
