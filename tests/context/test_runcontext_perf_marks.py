"""Unit tests for RunContext perf mark methods."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from functualize._events.perf import PerfTimeline
from functualize.job.context import RunContext


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


class TestValidateMarkName:
    """Tests for _validate_mark_name."""

    def test_empty_name_raises(self, rc: RunContext) -> None:
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="non-empty string"):
            rc._validate_mark_name("")

    def test_name_over_256_chars_raises(self, rc: RunContext) -> None:
        """Name exceeding 256 characters raises ValueError."""
        long_name = "a" * 257
        with pytest.raises(ValueError, match="at most 256 characters"):
            rc._validate_mark_name(long_name)

    def test_name_exactly_256_chars_valid(self, rc: RunContext) -> None:
        """Name of exactly 256 characters is valid."""
        name = "a" * 256
        rc._validate_mark_name(name)  # Should not raise

    def test_normal_name_valid(self, rc: RunContext) -> None:
        """Normal name passes validation."""
        rc._validate_mark_name("my-phase")  # Should not raise


class TestPerfMark:
    """Tests for perf_mark."""

    def test_records_mark_with_prefix(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """perf_mark records mark prefixed with job name."""
        rc.perf_mark("my-event")
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.my-event" in mark_names

    def test_empty_name_raises(self, rc: RunContext) -> None:
        """perf_mark raises ValueError for empty name."""
        with pytest.raises(ValueError):
            rc.perf_mark("")

    def test_long_name_raises(self, rc: RunContext) -> None:
        """perf_mark raises ValueError for name > 256 chars."""
        with pytest.raises(ValueError):
            rc.perf_mark("x" * 257)

    def test_disabled_timeline_no_op(
        self, rc_disabled: RunContext, disabled_timeline: PerfTimeline
    ) -> None:
        """perf_mark is a no-op when timeline is disabled."""
        rc_disabled.perf_mark("something")
        report = disabled_timeline.report()
        assert len(report.marks) == 0

    def test_validation_still_runs_when_disabled(self, rc_disabled: RunContext) -> None:
        """Validation raises even when timeline is disabled."""
        with pytest.raises(ValueError):
            rc_disabled.perf_mark("")


class TestPerfMarkStart:
    """Tests for perf_mark_start."""

    def test_records_start_mark_with_prefix(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """perf_mark_start records mark with .start suffix."""
        rc.perf_mark_start("upload")
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.upload.start" in mark_names

    def test_empty_name_raises(self, rc: RunContext) -> None:
        """perf_mark_start raises ValueError for empty name."""
        with pytest.raises(ValueError):
            rc.perf_mark_start("")

    def test_disabled_timeline_no_op(
        self, rc_disabled: RunContext, disabled_timeline: PerfTimeline
    ) -> None:
        """perf_mark_start is a no-op when timeline is disabled."""
        rc_disabled.perf_mark_start("upload")
        report = disabled_timeline.report()
        assert len(report.marks) == 0


class TestPerfMarkEnd:
    """Tests for perf_mark_end."""

    def test_records_end_mark_with_prefix(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """perf_mark_end records mark with .end suffix."""
        rc.perf_mark_end("upload")
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.upload.end" in mark_names

    def test_end_without_start_records_mark(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """perf_mark_end with no prior start records mark without error."""
        rc.perf_mark_end("orphan")
        report = timeline.report()
        mark_names = [name for name, _ in report.marks]
        assert "test-job.orphan.end" in mark_names
        # No phase should be derived from unpaired end mark
        assert len(report.phases) == 0

    def test_start_end_pair_produces_phase(
        self, rc: RunContext, timeline: PerfTimeline
    ) -> None:
        """Start + end pair produces a completed phase."""
        rc.perf_mark_start("data-load")
        rc.perf_mark_end("data-load")
        report = timeline.report()
        phase = report.phase("test-job.data-load")
        assert phase is not None
        assert phase.duration_ns >= 0

    def test_empty_name_raises(self, rc: RunContext) -> None:
        """perf_mark_end raises ValueError for empty name."""
        with pytest.raises(ValueError):
            rc.perf_mark_end("")

    def test_disabled_timeline_no_op(
        self, rc_disabled: RunContext, disabled_timeline: PerfTimeline
    ) -> None:
        """perf_mark_end is a no-op when timeline is disabled."""
        rc_disabled.perf_mark_end("upload")
        report = disabled_timeline.report()
        assert len(report.marks) == 0
