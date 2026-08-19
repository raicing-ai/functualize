"""Tests for the Run Status State Machine.

Property 14: Run Status State Machine
Validates: Requirements 8.2, 8.3

Tests that:
- set_run_status updates run_status property to the new value
- From RUNNING state, transitioning to any terminal state succeeds
- From any terminal state, transitioning to any other state raises InvalidStateTransitionError
- track_run_status (backward compat) behaves identically to set_run_status for state machine rules

This file used to be `test_runcontext_status_props.py` and drove every case with
Hypothesis. Its entire input space is `RunStatus`, a six-member enum, so `@given`
was drawing 200 examples from a domain of at most 24 combinations — repetition,
not exploration, and only *probably* complete. `parametrize` covers the same
domain exhaustively and deterministically in 80 cases, and because the file is no
longer named `*_props.py` these now run in the fast tier on every PR rather than
only under `--run-slow`.

Three tests were dropped as strict subsets of tests that remain:

- ``test_terminal_to_terminal_raises`` (terminal x terminal) and
  ``test_terminal_to_non_terminal_raises`` (terminal x non-terminal) had bodies
  identical to ``test_terminal_to_any_status_raises`` (terminal x all), and
  ``all_statuses`` is exactly the union of the other two.
- ``test_track_run_status_from_terminal_raises`` asserted the track_run_status
  half of what ``test_both_methods_agree_from_terminal_state`` already asserts
  over the same domain.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from functualize._config.job_config import JobConfigView
from functualize.job.context import (
    InvalidStateTransitionError,
    RunContext,
    RunStatus,
)

# --- The state space, enumerated ---

ALL_STATUSES = list(RunStatus)

# Terminal states: cannot be transitioned from. Written out rather than imported
# so this file states the contract independently of the implementation; the guard
# test below asserts the two agree.
TERMINAL_STATUSES = [
    RunStatus.SUCCESS,
    RunStatus.FAILURE,
    RunStatus.CANCELLED,
    RunStatus.TIMEOUT,
]

# Everything else is non-terminal, derived so that a new RunStatus member is
# covered automatically instead of being silently skipped. The previous version
# of this file hard-coded this list as [RUNNING, UNKNOWN] and thereby never
# exercised BLOCKED or SKIPPED at all — neither as a target nor as a starting
# state — even though `_TERMINAL_STATES` in
# `_engine/capabilities/runcontext.py` classifies both as non-terminal.
NON_TERMINAL_STATUSES = [s for s in ALL_STATUSES if s not in TERMINAL_STATUSES]

# Representative messages: empty, plain, and non-ASCII. The message is stored
# verbatim and never parsed, so these three cover what random text did.
MESSAGES = ["", "finished cleanly", "terminé ✓"]


def test_terminal_statuses_match_the_engine_definition() -> None:
    """This file's terminal set is the one the engine actually enforces.

    Without this, the parametrized cases below could drift from the
    implementation and keep passing while covering the wrong states.
    """
    from functualize._engine.capabilities.runcontext import _TERMINAL_STATES

    assert set(TERMINAL_STATUSES) == set(_TERMINAL_STATES)


def test_status_partition_covers_every_run_status() -> None:
    """Every RunStatus member is classified as terminal or non-terminal."""
    assert set(TERMINAL_STATUSES) | set(NON_TERMINAL_STATUSES) == set(ALL_STATUSES)
    assert not set(TERMINAL_STATUSES) & set(NON_TERMINAL_STATUSES)


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

    @pytest.mark.parametrize("target_status", TERMINAL_STATUSES)
    def test_set_run_status_updates_to_terminal(self, target_status: RunStatus) -> None:
        """set_run_status sets run_status property to the target terminal value.

        **Validates: Requirements 8.2**
        """
        rc = make_run_context()
        rc.set_run_status(target_status)
        assert rc.run_status == target_status

    @pytest.mark.parametrize("target_status", NON_TERMINAL_STATUSES)
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

    @pytest.mark.parametrize("terminal", TERMINAL_STATUSES)
    def test_running_to_terminal_does_not_raise(self, terminal: RunStatus) -> None:
        """From RUNNING, transitioning to any terminal state succeeds without error.

        **Validates: Requirements 8.2**
        """
        rc = make_run_context()
        assert rc.run_status == RunStatus.RUNNING
        # Should not raise
        rc.set_run_status(terminal)
        assert rc.run_status == terminal

    @pytest.mark.parametrize("terminal", TERMINAL_STATUSES)
    @pytest.mark.parametrize("message", MESSAGES)
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
    """From any terminal state, transitioning to any other state raises."""

    @pytest.mark.parametrize("first_terminal", TERMINAL_STATUSES)
    @pytest.mark.parametrize("second_status", ALL_STATUSES)
    def test_terminal_to_any_status_raises(
        self, first_terminal: RunStatus, second_status: RunStatus
    ) -> None:
        """From a terminal state, any transition raises InvalidStateTransitionError.

        Covers terminal->terminal and terminal->non-terminal alike, since
        ``ALL_STATUSES`` is the union of the two.

        **Validates: Requirements 8.2, 8.3**
        """
        rc = make_run_context()
        rc.set_run_status(first_terminal)
        with pytest.raises(InvalidStateTransitionError):
            rc.set_run_status(second_status)


class TestTrackRunStatusBackwardCompat:
    """track_run_status behaves identically to set_run_status."""

    @pytest.mark.parametrize("terminal", TERMINAL_STATUSES)
    def test_track_run_status_from_running_succeeds(self, terminal: RunStatus) -> None:
        """track_run_status from RUNNING to terminal succeeds like set_run_status.

        **Validates: Requirements 8.3**
        """
        rc = make_run_context()
        rc.track_run_status(run_status=terminal)
        assert rc.run_status == terminal

    @pytest.mark.parametrize("target_status", ALL_STATUSES)
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

    @pytest.mark.parametrize("first_terminal", TERMINAL_STATUSES)
    @pytest.mark.parametrize("second_status", ALL_STATUSES)
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
