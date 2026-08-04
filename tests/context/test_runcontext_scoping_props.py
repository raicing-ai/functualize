# Feature: perf-timeline-mark, Property 9: get_perf_phases scoping
"""Property-based tests for get_perf_phases scoping.

Property 9: get_perf_phases scoping
Validates: Requirements 3.1, 3.2, 3.8

Verifies:
- With multi-job phase data, only phases prefixed with current job name are returned
- No phases from other jobs are included
- Filter patterns match against the unprefixed portion of phase names
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize._events.perf import PerfTimeline
from functualize.job.context import RunContext

# --- Strategies ---

# Strategy for valid job names: alphanumeric + hyphens/underscores, non-empty
_job_name_chars = st.characters(
    categories=("L", "N"),
    include_characters="_-",
)
job_names = st.text(alphabet=_job_name_chars, min_size=1, max_size=20)

# Strategy for valid phase names: alphanumeric + hyphens/underscores/dots, non-empty
_phase_name_chars = st.characters(
    categories=("L", "N"),
    include_characters="_-.",
)
phase_names = st.text(alphabet=_phase_name_chars, min_size=1, max_size=30).filter(
    lambda s: not s.startswith(".") and not s.endswith(".") and ".." not in s
)


# --- Helpers ---


def make_run_context(name: str, timeline: PerfTimeline) -> RunContext:
    """Create a RunContext with mocked dependencies and injected timeline."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock()
    return RunContext(
        name=name,
        config=mock_config,
        logger=mock_logger,
        perf_timeline=timeline,
    )


def record_phase(timeline: PerfTimeline, job_name: str, phase_name: str) -> None:
    """Record a complete phase (start + end) on the timeline for a given job."""
    timeline.mark(f"{job_name}.{phase_name}.start")
    timeline.mark(f"{job_name}.{phase_name}.end")


# **Validates: Requirements 3.1, 3.2, 3.8**
class TestGetPerfPhasesScoping:
    """Property 9: get_perf_phases scoping."""

    @given(
        target_job=job_names,
        other_jobs=st.lists(job_names, min_size=1, max_size=3),
        target_phases=st.lists(phase_names, min_size=1, max_size=5, unique=True),
        other_phases=st.lists(phase_names, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_only_target_job_phases_returned(
        self,
        target_job: str,
        other_jobs: list[str],
        target_phases: list[str],
        other_phases: list[str],
    ) -> None:
        """get_perf_phases returns only phases prefixed with the target job name.

        **Validates: Requirements 3.1, 3.2**
        """
        # Ensure other jobs are distinct from target
        other_jobs = [j for j in other_jobs if j != target_job]
        if not other_jobs:
            return  # Skip if we can't get distinct other jobs

        timeline = PerfTimeline(enabled=True)

        # Record phases for the target job
        for phase in target_phases:
            record_phase(timeline, target_job, phase)

        # Record phases for other jobs
        for other_job in other_jobs:
            for phase in other_phases:
                record_phase(timeline, other_job, phase)

        # Create RunContext for target job
        rc = make_run_context(target_job, timeline)
        result = rc.get_perf_phases()

        # All returned phases must start with "{target_job}."
        prefix = f"{target_job}."
        for phase in result:
            assert phase.name.startswith(prefix), (
                f"Phase '{phase.name}' does not start with expected prefix '{prefix}'"
            )

        # No phases from other jobs should be present
        other_prefixes = [f"{j}." for j in other_jobs]
        for phase in result:
            for other_prefix in other_prefixes:
                assert not phase.name.startswith(other_prefix), (
                    f"Phase '{phase.name}' from another job found in results"
                )

    @given(
        target_job=job_names,
        other_jobs=st.lists(job_names, min_size=1, max_size=3),
        target_phases=st.lists(phase_names, min_size=1, max_size=5, unique=True),
        other_phases=st.lists(phase_names, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_no_other_job_phases_included(
        self,
        target_job: str,
        other_jobs: list[str],
        target_phases: list[str],
        other_phases: list[str],
    ) -> None:
        """No phases from other jobs are included in get_perf_phases results.

        **Validates: Requirements 3.1, 3.2**
        """
        # Ensure other jobs are distinct from target
        other_jobs = [j for j in other_jobs if j != target_job]
        if not other_jobs:
            return

        timeline = PerfTimeline(enabled=True)

        # Record phases for target and other jobs
        for phase in target_phases:
            record_phase(timeline, target_job, phase)
        for other_job in other_jobs:
            for phase in other_phases:
                record_phase(timeline, other_job, phase)

        rc = make_run_context(target_job, timeline)
        result = rc.get_perf_phases()

        # Count: we should get exactly len(target_phases) phases
        # (only target job's phases)
        result_names = {p.name for p in result}
        expected_names = {f"{target_job}.{phase}" for phase in target_phases}
        assert result_names == expected_names

    @given(
        target_job=job_names,
        other_jobs=st.lists(job_names, min_size=1, max_size=3),
        target_phases=st.lists(phase_names, min_size=2, max_size=5, unique=True),
        other_phases=st.lists(phase_names, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_filter_matches_against_unprefixed_names(
        self,
        target_job: str,
        other_jobs: list[str],
        target_phases: list[str],
        other_phases: list[str],
    ) -> None:
        """Filter patterns match against the unprefixed portion of phase names.

        **Validates: Requirements 3.8**
        """
        other_jobs = [j for j in other_jobs if j != target_job]
        if not other_jobs:
            return

        timeline = PerfTimeline(enabled=True)

        # Record phases for target job
        for phase in target_phases:
            record_phase(timeline, target_job, phase)

        # Record phases for other jobs
        for other_job in other_jobs:
            for phase in other_phases:
                record_phase(timeline, other_job, phase)

        rc = make_run_context(target_job, timeline)

        # Use the first target phase name as an include filter (prefix match)
        # This should match against the unprefixed name, not the full name
        filter_phase = target_phases[0]
        result = rc.get_perf_phases(include=filter_phase)

        # All results should still be prefixed with target job
        prefix = f"{target_job}."
        for phase in result:
            assert phase.name.startswith(prefix)

        # The unprefixed portion of each result should match the filter
        for phase in result:
            unprefixed = phase.name[len(prefix) :]
            assert unprefixed.startswith(filter_phase), (
                f"Unprefixed name '{unprefixed}' does not match "
                f"include filter '{filter_phase}'"
            )

        # The first target phase should definitely be in results
        expected_name = f"{target_job}.{filter_phase}"
        result_names = {p.name for p in result}
        assert expected_name in result_names, (
            f"Expected '{expected_name}' in results when filtering "
            f"by unprefixed name '{filter_phase}'"
        )

    @given(
        target_job=job_names,
        other_jobs=st.lists(job_names, min_size=1, max_size=3),
        target_phases=st.lists(phase_names, min_size=2, max_size=5, unique=True),
        other_phases=st.lists(phase_names, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_exclude_filter_on_unprefixed_names(
        self,
        target_job: str,
        other_jobs: list[str],
        target_phases: list[str],
        other_phases: list[str],
    ) -> None:
        """Exclude filter works against unprefixed phase names.

        **Validates: Requirements 3.8**
        """
        other_jobs = [j for j in other_jobs if j != target_job]
        if not other_jobs:
            return

        timeline = PerfTimeline(enabled=True)

        for phase in target_phases:
            record_phase(timeline, target_job, phase)
        for other_job in other_jobs:
            for phase in other_phases:
                record_phase(timeline, other_job, phase)

        rc = make_run_context(target_job, timeline)

        # Exclude the first target phase by its unprefixed name
        excluded_phase = target_phases[0]
        result = rc.get_perf_phases(exclude=excluded_phase)

        # The excluded phase should NOT be in results
        excluded_full_name = f"{target_job}.{excluded_phase}"
        result_names = {p.name for p in result}
        assert excluded_full_name not in result_names, (
            f"Excluded phase '{excluded_full_name}' should not be in results"
        )

        # All results should still belong to target job
        prefix = f"{target_job}."
        for phase in result:
            assert phase.name.startswith(prefix)
