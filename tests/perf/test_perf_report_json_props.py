# Feature: perf-timeline-mark, Property 7: JSON structural validity
"""Property-based tests for PerfReport.to_json() structural validity.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4**

Property 7: JSON structural validity
For any PerfReport instance, to_json() SHALL return a string that is valid JSON
containing a numeric total_ms field, a phases array ordered by start_ns ascending
where each element has name, start_ns, end_ns, duration_ns, and duration_ms fields,
and a marks array ordered by timestamp_ns ascending where each element has name and
timestamp_ns fields.
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

# Phase name: 1-4 dot-delimited segments
_phase_name = st.lists(_segment, min_size=1, max_size=4).map(".".join)

# Nanosecond timestamps (reasonable range)
_ns_timestamp = st.integers(min_value=0, max_value=10**15)


@st.composite
def _phase_strategy(draw: st.DrawFn) -> Phase:
    """Generate a random Phase with start_ns <= end_ns."""
    name = draw(_phase_name)
    start_ns = draw(_ns_timestamp)
    end_ns = draw(st.integers(min_value=start_ns, max_value=start_ns + 10**12))
    return Phase(name=name, start_ns=start_ns, end_ns=end_ns)


# Mark: tuple of (name, timestamp_ns)
_mark = st.tuples(_phase_name, _ns_timestamp)

# List of phases (0-10)
_phases = st.lists(_phase_strategy(), min_size=0, max_size=10)

# List of marks (0-10)
_marks = st.lists(_mark, min_size=0, max_size=10)


@st.composite
def _perf_report_strategy(draw: st.DrawFn) -> PerfReport:
    """Generate a random PerfReport instance."""
    phases = draw(_phases)
    marks = draw(_marks)
    total_ms = draw(
        st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False)
    )
    return PerfReport(phases=phases, total_ms=total_ms, marks=marks)


class TestJsonStructuralValidity:
    """Property 7: JSON structural validity."""

    @given(report=_perf_report_strategy())
    @settings(max_examples=100)
    def test_to_json_is_valid_json(self, report: PerfReport) -> None:
        """to_json() output must be parseable by json.loads without raising."""
        output = report.to_json()
        data = json.loads(output)  # Must not raise
        assert isinstance(data, dict)

    @given(report=_perf_report_strategy())
    @settings(max_examples=100)
    def test_total_ms_is_numeric(self, report: PerfReport) -> None:
        """The JSON output contains a numeric total_ms field."""
        output = report.to_json()
        data = json.loads(output)

        assert "total_ms" in data
        assert isinstance(data["total_ms"], int | float)

    @given(report=_perf_report_strategy())
    @settings(max_examples=100)
    def test_phases_array_structure(self, report: PerfReport) -> None:
        """The JSON phases array has required fields and is ordered by start_ns."""
        output = report.to_json()
        data = json.loads(output)

        assert "phases" in data
        assert isinstance(data["phases"], list)

        for phase in data["phases"]:
            # All required fields present
            assert "name" in phase
            assert "start_ns" in phase
            assert "end_ns" in phase
            assert "duration_ns" in phase
            assert "duration_ms" in phase

            # Type checks
            assert isinstance(phase["name"], str)
            assert isinstance(phase["start_ns"], int)
            assert isinstance(phase["end_ns"], int)
            assert isinstance(phase["duration_ns"], int)
            assert isinstance(phase["duration_ms"], int | float)

        # Phases ordered by start_ns ascending
        start_values = [p["start_ns"] for p in data["phases"]]
        assert start_values == sorted(start_values)

    @given(report=_perf_report_strategy())
    @settings(max_examples=100)
    def test_marks_array_structure(self, report: PerfReport) -> None:
        """The JSON marks array has required fields and is ordered by timestamp_ns."""
        output = report.to_json()
        data = json.loads(output)

        assert "marks" in data
        assert isinstance(data["marks"], list)

        for mark in data["marks"]:
            # All required fields present
            assert "name" in mark
            assert "timestamp_ns" in mark

            # Type checks
            assert isinstance(mark["name"], str)
            assert isinstance(mark["timestamp_ns"], int)

        # Marks ordered by timestamp_ns ascending
        ts_values = [m["timestamp_ns"] for m in data["marks"]]
        assert ts_values == sorted(ts_values)
