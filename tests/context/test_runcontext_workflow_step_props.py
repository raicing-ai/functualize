"""Property-based tests for workflow step retrieval consistency.

Property 15: Workflow Step Retrieval Consistency
Validates: Requirements 8.4, 8.5

Verifies:
- get_phase(name) returns None for untracked steps (for any generated name)
- After track_phase(name, msg, status), get_phase(name) returns that step
  with correct fields
- current_phase always returns the most recently tracked/updated step
- get_phase is consistent with workflow_steps list (the step returned by name
  matches the one in the list)
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize.job.context import (
    RunContext,
    RunStatus,
)

# --- Strategies ---

# Strategy for valid step names
step_names = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd")),
    min_size=1,
    max_size=50,
)

# Strategy for step messages (including edge cases)
step_messages = st.text(min_size=0, max_size=2000)

# Strategy for step statuses
step_statuses = st.sampled_from(list(RunStatus))


# --- Helpers ---


def make_run_context(name: str = "test-job") -> RunContext:
    """Create a RunContext with mocked dependencies."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock()
    return RunContext(name=name, config=mock_config, logger=mock_logger)


# Feature: functualize, Property 15: Workflow Step Retrieval Consistency
# **Validates: Requirements 8.4, 8.5**
class TestJobPhaseRetrievalConsistency:
    """Property 15: Workflow Step Retrieval Consistency."""

    @given(name=step_names)
    def test_get_phase_returns_none_for_untracked(self, name: str) -> None:
        """get_phase(name) returns None for any untracked step name."""
        # **Validates: Requirements 8.4, 8.5**
        rc = make_run_context()
        assert rc.get_phase(name) is None

    @given(name=step_names, message=step_messages, status=step_statuses)
    def test_get_phase_returns_tracked_step(
        self, name: str, message: str, status: RunStatus
    ) -> None:
        """After track_phase(name, msg, status), get_phase(name) returns
        that step with correct fields."""
        # **Validates: Requirements 8.4, 8.5**
        rc = make_run_context()
        rc.track_phase(name, message, status)

        step = rc.get_phase(name)
        assert step is not None
        assert step["name"] == name
        assert step["status"] == status
        assert step["message"] == message[:1000]
        assert step["start_time"] is not None

    @given(
        steps=st.lists(
            st.tuples(step_names, step_messages, step_statuses),
            min_size=1,
            max_size=10,
            unique_by=lambda x: x[0],
        )
    )
    def test_current_phase_is_most_recently_tracked(
        self, steps: list[tuple[str, str, RunStatus]]
    ) -> None:
        """current_phase always returns the most recently tracked step."""
        # **Validates: Requirements 8.4, 8.5**
        rc = make_run_context()
        for step_name, step_message, step_status in steps:
            rc.track_phase(step_name, step_message, step_status)

        # The last step tracked (new step appended at end) is the current step
        last_name = steps[-1][0]
        current = rc.current_phase
        assert current is not None
        assert current["name"] == last_name

    @given(
        step_name=step_names,
        msg1=step_messages,
        msg2=step_messages,
        status1=step_statuses,
        status2=step_statuses,
    )
    def test_current_phase_after_update(
        self,
        step_name: str,
        msg1: str,
        msg2: str,
        status1: RunStatus,
        status2: RunStatus,
    ) -> None:
        """current_phase returns the most recently updated step when an
        existing step is updated (since it stays in its original position, a later
        new step would be current, but if only one step exists it remains current)."""
        # **Validates: Requirements 8.4, 8.5**
        rc = make_run_context()
        rc.track_phase(step_name, msg1, status1)
        rc.track_phase(step_name, msg2, status2)

        # Only one step exists (updated in place), so it's the current step
        current = rc.current_phase
        assert current is not None
        assert current["name"] == step_name
        assert current["status"] == status2
        assert current["message"] == msg2[:1000]

    @given(
        steps=st.lists(
            st.tuples(step_names, step_messages, step_statuses),
            min_size=1,
            max_size=10,
            unique_by=lambda x: x[0],
        )
    )
    def test_get_phase_consistent_with_list(
        self, steps: list[tuple[str, str, RunStatus]]
    ) -> None:
        """get_phase(name) returns the same object as the matching entry
        in the workflow_steps list."""
        # **Validates: Requirements 8.4, 8.5**
        rc = make_run_context()
        for step_name, step_message, step_status in steps:
            rc.track_phase(step_name, step_message, step_status)

        # For each step, get_phase must return the identical object
        # that's found in the workflow_steps list
        for tracked_step in rc.phases:
            retrieved = rc.get_phase(tracked_step["name"])
            assert retrieved is tracked_step
