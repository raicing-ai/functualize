# Feature: perf-timeline-mark, Property 5: Workflow step auto-marking
"""Property-based tests for RunContext workflow step auto-marking.

Validates: Requirements 4.1, 4.2, 4.3, 4.4

Property 5: For any RunContext with an enabled timeline and any valid step name,
calling track_phase with a new step name SHALL record a mark matching
"{job_name}.phase.{step_name}.start", and transitioning that step to a terminal
status SHALL additionally record a mark matching "{job_name}.phase.{step_name}.end".
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._events.perf import PerfTimeline
from functualize.job.context import RunContext, RunStatus

# --- Strategies ---

# Job names: alphanumeric + hyphens, 1-20 chars
job_name_strategy = st.from_regex(r"[a-zA-Z0-9\-]{1,20}", fullmatch=True)

# Step names: alphanumeric + hyphens, 1-30 chars
step_name_strategy = st.from_regex(r"[a-zA-Z0-9\-]{1,30}", fullmatch=True)

# All RunStatus values
run_status_strategy = st.sampled_from(list(RunStatus))

# Terminal statuses only
terminal_status_strategy = st.sampled_from(
    [RunStatus.SUCCESS, RunStatus.FAILURE, RunStatus.CANCELLED, RunStatus.TIMEOUT]
)

# Non-terminal statuses only
non_terminal_status_strategy = st.sampled_from([RunStatus.RUNNING, RunStatus.UNKNOWN])


def _make_run_context(job_name: str, timeline: PerfTimeline) -> RunContext:
    """Create a RunContext with injected PerfTimeline and the given job name."""
    mock_config = MagicMock()
    mock_logger = MagicMock()
    return RunContext(
        name=job_name,
        config=mock_config,
        logger=mock_logger,
        perf_timeline=timeline,
    )


class TestJobPhaseAutoMarking:
    """Property 5: Workflow step auto-marking.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """

    @given(job_name=job_name_strategy, step_name=step_name_strategy)
    @settings(max_examples=100)
    def test_new_step_records_start_mark(self, job_name: str, step_name: str) -> None:
        """A new workflow step records a start mark '{job_name}.phase.{step_name}.start'.

        **Validates: Requirements 4.1**
        """
        timeline = PerfTimeline(enabled=True)
        rc = _make_run_context(job_name, timeline)

        rc.track_phase(step_name, "starting step", RunStatus.RUNNING)

        report = timeline.report()
        recorded_names = [name for name, _ in report.marks]
        expected_start = f"{job_name}.phase.{step_name}.start"
        assert expected_start in recorded_names, (
            f"Expected start mark '{expected_start}' not found in {recorded_names}"
        )

    @given(
        job_name=job_name_strategy,
        step_name=step_name_strategy,
        terminal_status=terminal_status_strategy,
    )
    @settings(max_examples=100)
    def test_new_step_with_terminal_status_records_both_marks(
        self, job_name: str, step_name: str, terminal_status: RunStatus
    ) -> None:
        """A new step with immediately terminal status records BOTH start and end marks.

        **Validates: Requirements 4.3**
        """
        timeline = PerfTimeline(enabled=True)
        rc = _make_run_context(job_name, timeline)

        rc.track_phase(step_name, "immediate terminal", terminal_status)

        report = timeline.report()
        recorded_names = [name for name, _ in report.marks]
        expected_start = f"{job_name}.phase.{step_name}.start"
        expected_end = f"{job_name}.phase.{step_name}.end"
        assert expected_start in recorded_names, (
            f"Expected start mark '{expected_start}' not found in {recorded_names}"
        )
        assert expected_end in recorded_names, (
            f"Expected end mark '{expected_end}' not found in {recorded_names}"
        )

    @given(
        job_name=job_name_strategy,
        step_name=step_name_strategy,
        terminal_status=terminal_status_strategy,
    )
    @settings(max_examples=100)
    def test_existing_step_transitioning_to_terminal_records_end_mark(
        self, job_name: str, step_name: str, terminal_status: RunStatus
    ) -> None:
        """An existing step transitioning to terminal records an end mark.

        **Validates: Requirements 4.2**
        """
        timeline = PerfTimeline(enabled=True)
        rc = _make_run_context(job_name, timeline)

        # First call: create the step with non-terminal status
        rc.track_phase(step_name, "step running", RunStatus.RUNNING)

        # Clear marks to isolate the transition effect
        marks_before = len(timeline.report().marks)

        # Second call: transition to terminal
        rc.track_phase(step_name, "step done", terminal_status)

        report = timeline.report()
        recorded_names = [name for name, _ in report.marks]
        expected_end = f"{job_name}.phase.{step_name}.end"
        assert expected_end in recorded_names, (
            f"Expected end mark '{expected_end}' not found in {recorded_names}"
        )
        # The end mark should have been added after the initial start mark
        assert len(report.marks) > marks_before, (
            "Expected new marks to be recorded on terminal transition"
        )

    @given(
        job_name=job_name_strategy,
        step_name=step_name_strategy,
        non_terminal_status=non_terminal_status_strategy,
    )
    @settings(max_examples=100)
    def test_new_step_with_non_terminal_status_records_only_start(
        self, job_name: str, step_name: str, non_terminal_status: RunStatus
    ) -> None:
        """A new step with non-terminal status records only a start mark, no end mark.

        **Validates: Requirements 4.1, 4.4**
        """
        timeline = PerfTimeline(enabled=True)
        rc = _make_run_context(job_name, timeline)

        rc.track_phase(step_name, "step in progress", non_terminal_status)

        report = timeline.report()
        recorded_names = [name for name, _ in report.marks]
        expected_start = f"{job_name}.phase.{step_name}.start"
        expected_end = f"{job_name}.phase.{step_name}.end"
        assert expected_start in recorded_names, (
            f"Expected start mark '{expected_start}' not found in {recorded_names}"
        )
        assert expected_end not in recorded_names, (
            f"End mark '{expected_end}' should NOT be recorded for non-terminal status"
        )
