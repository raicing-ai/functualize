"""Unit tests for automatic perf marking in RunContext.track_phase."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from functualize._events.perf import PerfTimeline
from functualize.job.context import RunContext, RunStatus


@pytest.fixture
def timeline() -> PerfTimeline:
    """Create a fresh PerfTimeline for testing."""
    return PerfTimeline(enabled=True)


@pytest.fixture
def disabled_timeline() -> PerfTimeline:
    """Create a disabled PerfTimeline."""
    return PerfTimeline(enabled=False)


@pytest.fixture
def rc(timeline: PerfTimeline) -> RunContext:
    """Create a RunContext with an injected PerfTimeline."""
    mock_config = MagicMock()
    mock_logger = MagicMock()
    return RunContext(
        name="test-job",
        config=mock_config,
        logger=mock_logger,
        perf_timeline=timeline,
    )


@pytest.fixture
def rc_disabled(disabled_timeline: PerfTimeline) -> RunContext:
    """Create a RunContext with a disabled PerfTimeline."""
    mock_config = MagicMock()
    mock_logger = MagicMock()
    return RunContext(
        name="test-job",
        config=mock_config,
        logger=mock_logger,
        perf_timeline=disabled_timeline,
    )


class TestJobPhasePerfMarkNewPhase:
    """Tests for auto perf marking on new workflow steps."""

    def test_new_step_records_start_mark(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """New step records a start mark with workflow naming convention."""
        rc.track_phase("upload", "Starting upload")
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.phase.upload.start" in mark_names

    def test_new_step_running_does_not_record_end(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """New step with RUNNING status does not record an end mark."""
        rc.track_phase("upload", "Starting upload", RunStatus.RUNNING)
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.phase.upload.end" not in mark_names

    def test_new_step_immediately_terminal_records_both(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """New step with terminal status records both start and end marks."""
        rc.track_phase("quick-check", "Done", RunStatus.SUCCESS)
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.phase.quick-check.start" in mark_names
        assert "test-job.phase.quick-check.end" in mark_names

    def test_new_step_failure_records_both(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """New step with FAILURE status records both start and end marks."""
        rc.track_phase("validate", "Failed", RunStatus.FAILURE)
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.phase.validate.start" in mark_names
        assert "test-job.phase.validate.end" in mark_names

    def test_new_step_cancelled_records_both(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """New step with CANCELLED status records both start and end marks."""
        rc.track_phase("process", "Cancelled", RunStatus.CANCELLED)
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.phase.process.start" in mark_names
        assert "test-job.phase.process.end" in mark_names

    def test_new_step_timeout_records_both(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """New step with TIMEOUT status records both start and end marks."""
        rc.track_phase("fetch", "Timed out", RunStatus.TIMEOUT)
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.phase.fetch.start" in mark_names
        assert "test-job.phase.fetch.end" in mark_names


class TestJobPhasePerfMarkExistingPhase:
    """Tests for auto perf marking on existing workflow step transitions."""

    def test_existing_step_transition_to_success_records_end(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """Existing step transitioning to SUCCESS records end mark."""
        rc.track_phase("upload", "Starting")
        rc.track_phase("upload", "Done", RunStatus.SUCCESS)
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.phase.upload.end" in mark_names

    def test_existing_step_transition_to_failure_records_end(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """Existing step transitioning to FAILURE records end mark."""
        rc.track_phase("upload", "Starting")
        rc.track_phase("upload", "Failed", RunStatus.FAILURE)
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.phase.upload.end" in mark_names

    def test_existing_step_non_terminal_update_no_end(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """Updating an existing step with non-terminal status does not record end."""
        rc.track_phase("upload", "Starting")
        rc.track_phase("upload", "Still running", RunStatus.RUNNING)
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.phase.upload.end" not in mark_names

    def test_full_lifecycle_produces_phase(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """Start + end marks from workflow tracking produce a derived phase."""
        rc.track_phase("upload", "Starting")
        rc.track_phase("upload", "Done", RunStatus.SUCCESS)
        report = timeline.report()
        phase = report.phase("test-job.phase.upload")
        assert phase is not None
        assert phase.duration_ns >= 0


class TestJobPhasePerfMarkDisabled:
    """Tests for perf marking when timeline is disabled."""

    def test_new_step_disabled_no_marks(
        self, rc_disabled: RunContext, disabled_timeline: PerfTimeline
    ) -> None:
        """No marks recorded when timeline is disabled (new step)."""
        rc_disabled.track_phase("upload", "Starting")
        report = disabled_timeline.report()
        assert len(report.marks) == 0

    def test_terminal_step_disabled_no_marks(
        self, rc_disabled: RunContext, disabled_timeline: PerfTimeline
    ) -> None:
        """No marks recorded when timeline is disabled (terminal step)."""
        rc_disabled.track_phase("upload", "Done", RunStatus.SUCCESS)
        report = disabled_timeline.report()
        assert len(report.marks) == 0

    def test_transition_disabled_no_marks(
        self, rc_disabled: RunContext, disabled_timeline: PerfTimeline
    ) -> None:
        """No marks recorded when timeline is disabled (transition)."""
        rc_disabled.track_phase("upload", "Starting")
        rc_disabled.track_phase("upload", "Done", RunStatus.SUCCESS)
        report = disabled_timeline.report()
        assert len(report.marks) == 0

    def test_workflow_step_still_tracked_when_disabled(
        self, rc_disabled: RunContext
    ) -> None:
        """Workflow step tracking still works even when perf is disabled."""
        rc_disabled.track_phase("upload", "Starting")
        assert len(rc_disabled.phases) == 1
        assert rc_disabled.phases[0]["name"] == "upload"
