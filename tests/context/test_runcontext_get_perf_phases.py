"""Unit tests for RunContext.get_perf_phases method."""

import logging
from unittest.mock import MagicMock

import pytest

from functualize._config.job_config import JobConfigView
from functualize._events.perf import PerfTimeline, Phase
from functualize.job.context import RunContext


@pytest.fixture
def mock_config():
    """Create a mock JobConfigView instance."""
    config = MagicMock(spec=JobConfigView)
    return config


@pytest.fixture
def mock_logger():
    """Create a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def timeline():
    """Create a fresh PerfTimeline for testing."""
    return PerfTimeline(enabled=True)


def _make_rc(
    name: str, config: MagicMock, logger: MagicMock, timeline: PerfTimeline
) -> RunContext:
    """Helper to create a RunContext with an injected PerfTimeline."""
    return RunContext(
        name=name,
        config=config,
        logger=logger,
        perf_timeline=timeline,
    )


class TestGetPerfPhasesScoping:
    """Tests for phase scoping to current job prefix."""

    def test_returns_only_phases_for_current_job(
        self, mock_config, mock_logger, timeline
    ):
        """Phases from other jobs are excluded."""
        # Record phases for two different jobs
        timeline.mark("my_job.upload.start")
        timeline.mark("my_job.upload.end")
        timeline.mark("other_job.download.start")
        timeline.mark("other_job.download.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases()

        assert len(phases) == 1
        assert phases[0].name == "my_job.upload"

    def test_returns_empty_list_when_no_phases_for_job(
        self, mock_config, mock_logger, timeline
    ):
        """Returns empty list when no phases match the job prefix."""
        timeline.mark("other_job.upload.start")
        timeline.mark("other_job.upload.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases()

        assert phases == []

    def test_returns_empty_list_when_timeline_empty(
        self, mock_config, mock_logger, timeline
    ):
        """Returns empty list when timeline has no marks."""
        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases()

        assert phases == []

    def test_returns_multiple_phases_for_job(self, mock_config, mock_logger, timeline):
        """Multiple phases from same job are all returned."""
        timeline.mark("my_job.step_a.start")
        timeline.mark("my_job.step_a.end")
        timeline.mark("my_job.step_b.start")
        timeline.mark("my_job.step_b.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases()

        assert len(phases) == 2
        names = {p.name for p in phases}
        assert names == {"my_job.step_a", "my_job.step_b"}


class TestGetPerfPhasesFiltering:
    """Tests for include/exclude filtering on unprefixed names."""

    def test_include_prefix_match(self, mock_config, mock_logger, timeline):
        """Include with no wildcard does prefix matching on unprefixed names."""
        timeline.mark("my_job.phase.upload.start")
        timeline.mark("my_job.phase.upload.end")
        timeline.mark("my_job.phase.download.start")
        timeline.mark("my_job.phase.download.end")
        timeline.mark("my_job.custom.step.start")
        timeline.mark("my_job.custom.step.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases(include="phase")

        assert len(phases) == 2
        names = {p.name for p in phases}
        assert names == {"my_job.phase.upload", "my_job.phase.download"}

    def test_exclude_removes_matching_phases(self, mock_config, mock_logger, timeline):
        """Exclude removes phases whose unprefixed name matches."""
        timeline.mark("my_job.phase.upload.start")
        timeline.mark("my_job.phase.upload.end")
        timeline.mark("my_job.phase.download.start")
        timeline.mark("my_job.phase.download.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases(exclude="phase.upload")

        assert len(phases) == 1
        assert phases[0].name == "my_job.phase.download"

    def test_include_and_exclude_combined(self, mock_config, mock_logger, timeline):
        """Include narrows first, then exclude removes from the narrowed set."""
        timeline.mark("my_job.phase.upload.start")
        timeline.mark("my_job.phase.upload.end")
        timeline.mark("my_job.phase.download.start")
        timeline.mark("my_job.phase.download.end")
        timeline.mark("my_job.custom.step.start")
        timeline.mark("my_job.custom.step.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases(include="phase", exclude="phase.download")

        assert len(phases) == 1
        assert phases[0].name == "my_job.phase.upload"

    def test_glob_pattern_matching(self, mock_config, mock_logger, timeline):
        """Glob patterns with * match on unprefixed names."""
        timeline.mark("my_job.phase.upload.start")
        timeline.mark("my_job.phase.upload.end")
        timeline.mark("my_job.phase.download.start")
        timeline.mark("my_job.phase.download.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases(include="phase.*load")

        # "phase.*load" → * matches chars except '.', so "up" and "down"
        assert len(phases) == 2

    def test_double_star_glob(self, mock_config, mock_logger, timeline):
        """Double-star glob matches any chars including dots."""
        timeline.mark("my_job.phase.upload.start")
        timeline.mark("my_job.phase.upload.end")
        timeline.mark("my_job.deep.nested.phase.start")
        timeline.mark("my_job.deep.nested.phase.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases(include="**")

        assert len(phases) == 2

    def test_comma_separated_include(self, mock_config, mock_logger, timeline):
        """Comma-separated patterns use OR semantics."""
        timeline.mark("my_job.phase.upload.start")
        timeline.mark("my_job.phase.upload.end")
        timeline.mark("my_job.phase.download.start")
        timeline.mark("my_job.phase.download.end")
        timeline.mark("my_job.custom.step.start")
        timeline.mark("my_job.custom.step.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases(include="phase.upload,custom.step")

        assert len(phases) == 2
        names = {p.name for p in phases}
        assert names == {"my_job.phase.upload", "my_job.custom.step"}

    def test_no_phases_match_returns_empty(self, mock_config, mock_logger, timeline):
        """Returns empty list when filter matches nothing."""
        timeline.mark("my_job.phase.upload.start")
        timeline.mark("my_job.phase.upload.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases(include="nonexistent")

        assert phases == []

    def test_returned_phases_have_original_prefixed_names(
        self, mock_config, mock_logger, timeline
    ):
        """Returned Phase objects retain their original prefixed names."""
        timeline.mark("my_job.phase.upload.start")
        timeline.mark("my_job.phase.upload.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases(include="phase")

        assert phases[0].name == "my_job.phase.upload"
        assert isinstance(phases[0], Phase)

    def test_phase_objects_have_duration_properties(
        self, mock_config, mock_logger, timeline
    ):
        """Returned Phase objects provide duration_ms, duration_ns, duration_us."""
        timeline.mark("my_job.work.start")
        timeline.mark("my_job.work.end")

        rc = _make_rc("my_job", mock_config, mock_logger, timeline)
        phases = rc.get_perf_phases()

        assert len(phases) == 1
        phase = phases[0]
        assert phase.duration_ns >= 0
        assert phase.duration_ms >= 0.0
        assert phase.duration_us >= 0.0
