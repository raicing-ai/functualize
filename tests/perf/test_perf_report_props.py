# Feature: perf-timeline-mark, Property 6: JSON round-trip
"""Property-based tests for PerfReport JSON round-trip.

**Validates: Requirements 7.5**

Property 6: JSON round-trip
For any valid PerfReport instance (with arbitrary phases and marks),
parsing the output of to_json() with json.loads() and reconstructing
a PerfReport SHALL produce phases with identical name, start_ns, end_ns,
and duration_ns values, and a total_ms value equal to the original.
"""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._events.perf import PerfReport, Phase

# --- Strategies ---

# Phase name segment: 1-8 lowercase alpha chars
_segment = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    min_size=1,
    max_size=8,
)

# Phase name: 1-4 dot-delimited segments (e.g., "boot.plugins.load")
_phase_name = st.lists(_segment, min_size=1, max_size=4).map(".".join)

# Mark name: reuse phase name strategy
_mark_name = _phase_name

# Timestamps in nanoseconds (realistic range)
_timestamp_ns = st.integers(min_value=0, max_value=10**15)


@st.composite
def _phase_strategy(draw: st.DrawFn) -> Phase:
    """Generate a random Phase with valid start_ns <= end_ns."""
    name = draw(_phase_name)
    start_ns = draw(_timestamp_ns)
    # end_ns must be >= start_ns
    duration = draw(st.integers(min_value=0, max_value=10**9))
    end_ns = start_ns + duration
    return Phase(name=name, start_ns=start_ns, end_ns=end_ns)


# List of phases (0-10)
_phases = st.lists(_phase_strategy(), min_size=0, max_size=10)

# List of marks as (name, timestamp_ns) tuples (0-15)
_marks = st.lists(
    st.tuples(_mark_name, _timestamp_ns),
    min_size=0,
    max_size=15,
)


@st.composite
def _perf_report_strategy(draw: st.DrawFn) -> PerfReport:
    """Generate a random PerfReport with consistent total_ms."""
    phases = draw(_phases)
    marks = draw(_marks)

    # Compute total_ms from phases if non-empty, otherwise from marks
    if phases:
        all_times = [p.start_ns for p in phases] + [p.end_ns for p in phases]
        total_ms = (max(all_times) - min(all_times)) / 1_000_000
    elif marks:
        timestamps = [ts for _, ts in marks]
        total_ms = (max(timestamps) - min(timestamps)) / 1_000_000
    else:
        total_ms = 0.0

    return PerfReport(phases=phases, total_ms=total_ms, marks=marks)


class TestJSONRoundTripProperty:
    """Property 6: JSON round-trip."""

    @given(report=_perf_report_strategy())
    @settings(max_examples=100)
    def test_json_round_trip_phases(self, report: PerfReport) -> None:
        """Parsing to_json() output and reconstructing phases produces
        identical name, start_ns, end_ns, and duration_ns values.
        """
        json_str = report.to_json()
        data = json.loads(json_str)

        # Reconstruct phases from JSON
        json_phases = data["phases"]

        # The JSON phases are sorted by start_ns, so sort original phases the same way
        original_sorted = sorted(report.phases, key=lambda p: p.start_ns)

        assert len(json_phases) == len(original_sorted)

        for json_phase, original_phase in zip(
            json_phases, original_sorted, strict=True
        ):
            assert json_phase["name"] == original_phase.name
            assert json_phase["start_ns"] == original_phase.start_ns
            assert json_phase["end_ns"] == original_phase.end_ns
            assert json_phase["duration_ns"] == original_phase.duration_ns

    @given(report=_perf_report_strategy())
    @settings(max_examples=100)
    def test_json_round_trip_total_ms(self, report: PerfReport) -> None:
        """Parsing to_json() output produces matching total_ms value."""
        json_str = report.to_json()
        data = json.loads(json_str)

        assert data["total_ms"] == report.total_ms


# Feature: perf-timeline-mark, Property 4: Filter produces new immutable report
# **Validates: Requirements 5.1**
#
# Property 4: Filter produces new immutable report
# For any PerfReport and any filter arguments, calling report.filter(include, exclude)
# returns a new PerfReport instance (not identical to the original), and the original
# report's phases list remains unchanged after the call.

# Pattern strategies for filter arguments
_prefix_pattern = _segment
_glob_pattern = st.one_of(
    st.tuples(_segment, st.just(".*")).map("".join),
    st.tuples(_segment, st.just(".**")).map("".join),
    st.just("**"),
)
_single_pattern = st.one_of(_prefix_pattern, _glob_pattern)
_pattern_string = st.lists(_single_pattern, min_size=1, max_size=3).map(", ".join)
_optional_pattern = st.one_of(st.none(), _pattern_string)


class TestFilterImmutabilityProperty:
    """Property 4: Filter produces new immutable report."""

    @given(
        report=_perf_report_strategy(),
        include=_optional_pattern,
        exclude=_optional_pattern,
    )
    @settings(max_examples=100)
    def test_filter_returns_new_instance(
        self,
        report: PerfReport,
        include: str | None,
        exclude: str | None,
    ) -> None:
        """filter() returns a new PerfReport instance, not identical to the original."""
        result = report.filter(include=include, exclude=exclude)

        # Result must be a different object (not the same identity)
        assert result is not report

    @given(
        report=_perf_report_strategy(),
        include=_optional_pattern,
        exclude=_optional_pattern,
    )
    @settings(max_examples=100)
    def test_filter_does_not_mutate_original_phases(
        self,
        report: PerfReport,
        include: str | None,
        exclude: str | None,
    ) -> None:
        """Original report's phases list is unchanged after filter() call."""
        # Snapshot original phases before filter
        original_phases = list(report.phases)

        report.filter(include=include, exclude=exclude)

        # Original phases list must be unchanged
        assert report.phases == original_phases
        assert len(report.phases) == len(original_phases)
