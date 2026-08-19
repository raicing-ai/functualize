# Feature: perf-timeline-mark, Property 8: Phase duration consistency
"""Property-based tests for Phase duration consistency.

Validates: Requirements 3.7

For arbitrary start_ns/end_ns pairs (with end_ns >= start_ns), verify:
- duration_ns == end_ns - start_ns
- duration_ms == duration_ns / 1_000_000
- duration_us == duration_ns / 1_000
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from functualize._events.perf import Phase


@given(
    name=st.text(min_size=1, max_size=50),
    start_ns=st.integers(min_value=0, max_value=10**18),
    end_ns=st.integers(min_value=0, max_value=10**18),
)
def test_phase_duration_consistency(name: str, start_ns: int, end_ns: int) -> None:
    """**Validates: Requirements 3.7**

    For any Phase with start_ns and end_ns (end_ns >= start_ns):
    - duration_ns == end_ns - start_ns
    - duration_ms == duration_ns / 1_000_000
    - duration_us == duration_ns / 1_000
    """
    # Ensure end_ns >= start_ns
    if end_ns < start_ns:
        start_ns, end_ns = end_ns, start_ns

    phase = Phase(name=name, start_ns=start_ns, end_ns=end_ns)

    expected_duration_ns = end_ns - start_ns

    assert phase.duration_ns == expected_duration_ns
    assert phase.duration_ms == expected_duration_ns / 1_000_000
    assert phase.duration_us == expected_duration_ns / 1_000
