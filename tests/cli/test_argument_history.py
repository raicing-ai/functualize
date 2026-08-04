"""Property-based tests for ArgumentHistory data model.

# Feature: tui-foundation, Properties 1-4: ArgumentHistory invariants

Tests validate the core correctness properties of the ArgumentHistory class:
record/retrieve consistency, deduplication, max length enforcement, and
JSON serialization round-trips.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.data.argument_history import ArgumentHistory

# =============================================================================
# Strategies
# =============================================================================

# Job names and field names: printable, non-empty strings
_name_str = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=20,
)

# Values: printable, non-empty strings (argument values are always non-empty strings)
_value_str = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=30,
)

# A record operation: (job_name, field_name, value)
_record_op = st.tuples(_name_str, _name_str, _value_str)

# A sequence of record operations
_record_ops = st.lists(_record_op, min_size=1, max_size=50)

# max_entries: small positive integers for testing enforcement
_max_entries = st.integers(min_value=1, max_value=20)


# =============================================================================
# Helper
# =============================================================================


def _expected_history(values: list[str], max_entries: int) -> list[str]:
    """Compute expected history given a sequence of recorded values.

    Applies consecutive duplicate collapse, then max_entries truncation
    (keeping most recent), then reverses to get reverse-chronological order.
    """
    # Collapse consecutive duplicates
    collapsed: list[str] = []
    for v in values:
        if not collapsed or collapsed[-1] != v:
            collapsed.append(v)
    # Enforce max_entries (keep most recent N)
    if len(collapsed) > max_entries:
        collapsed = collapsed[-max_entries:]
    # Return in reverse chronological order
    return list(reversed(collapsed))


# =============================================================================
# Property 1: Record-then-retrieve consistency
# =============================================================================


@pytest.mark.slow
class TestRecordThenRetrieveConsistency:
    """Property 1: Record-then-retrieve consistency.

    For any sequence of (job_name, field_name, value) tuples recorded into
    an ArgumentHistory, calling get_history(job_name, field_name) SHALL return
    exactly those values (with consecutive duplicates collapsed) in reverse
    chronological order.

    **Validates: Requirements 1.1, 1.3**
    """

    @given(ops=_record_ops)
    @settings(max_examples=200)
    def test_single_field_record_retrieve(self, ops: list[tuple[str, str, str]]):
        """Recording values for a single field returns them in reverse order
        with consecutive duplicates collapsed.

        **Validates: Requirements 1.1, 1.3**
        """
        ah = ArgumentHistory(_max_entries=50)

        # Group operations by (job_name, field_name) to verify each pair
        from collections import defaultdict

        expected_per_pair: dict[tuple[str, str], list[str]] = defaultdict(list)

        for job_name, field_name, value in ops:
            ah.record(job_name, field_name, value)
            expected_per_pair[(job_name, field_name)].append(value)

        # Verify each (job_name, field_name) pair
        for (job_name, field_name), values in expected_per_pair.items():
            expected = _expected_history(values, 50)
            actual = ah.get_history(job_name, field_name)
            assert actual == expected, (
                f"For ({job_name!r}, {field_name!r}): expected {expected}, got {actual}"
            )

    @given(
        job_name=_name_str,
        field_name=_name_str,
        values=st.lists(_value_str, min_size=1, max_size=30),
    )
    @settings(max_examples=200)
    def test_dedicated_field_record_retrieve(
        self, job_name: str, field_name: str, values: list[str]
    ):
        """Recording a sequence of values for one specific field returns them
        correctly.

        **Validates: Requirements 1.1, 1.3**
        """
        ah = ArgumentHistory(_max_entries=50)

        for v in values:
            ah.record(job_name, field_name, v)

        expected = _expected_history(values, 50)
        actual = ah.get_history(job_name, field_name)
        assert actual == expected


# =============================================================================
# Property 2: No consecutive duplicates
# =============================================================================


@pytest.mark.slow
class TestNoConsecutiveDuplicates:
    """Property 2: No consecutive duplicates.

    For any sequence of values recorded for a given (job_name, field_name)
    pair, the resulting history list SHALL never contain two adjacent identical
    values, regardless of how many times the same value was recorded
    consecutively.

    **Validates: Requirements 1.2**
    """

    @given(
        job_name=_name_str,
        field_name=_name_str,
        values=st.lists(_value_str, min_size=1, max_size=50),
    )
    @settings(max_examples=200)
    def test_no_adjacent_duplicates_in_history(
        self, job_name: str, field_name: str, values: list[str]
    ):
        """The history list never contains two adjacent identical values.

        **Validates: Requirements 1.2**
        """
        ah = ArgumentHistory(_max_entries=50)

        for v in values:
            ah.record(job_name, field_name, v)

        history = ah.get_history(job_name, field_name)

        # Check no two adjacent entries are identical
        for i in range(len(history) - 1):
            assert history[i] != history[i + 1], (
                f"Adjacent duplicate found at indices {i} and {i + 1}: "
                f"{history[i]!r} in history {history}"
            )

    @given(
        job_name=_name_str,
        field_name=_name_str,
        value=_value_str,
        repeat_count=st.integers(min_value=2, max_value=100),
    )
    @settings(max_examples=200)
    def test_repeated_same_value_collapses_to_one(
        self, job_name: str, field_name: str, value: str, repeat_count: int
    ):
        """Recording the same value N times results in a single entry.

        **Validates: Requirements 1.2**
        """
        ah = ArgumentHistory(_max_entries=50)

        for _ in range(repeat_count):
            ah.record(job_name, field_name, value)

        history = ah.get_history(job_name, field_name)
        assert history == [value], (
            f"Expected single entry [{value!r}] after {repeat_count} "
            f"identical records, got {history}"
        )


# =============================================================================
# Property 3: Max length invariant
# =============================================================================


@pytest.mark.slow
class TestMaxLengthInvariant:
    """Property 3: Max length invariant.

    For any ArgumentHistory instance with max_entries=N, and for any number
    of recorded values, the length of get_history(job_name, field_name) SHALL
    never exceed N, and the retained entries SHALL be the N most recent
    distinct values.

    **Validates: Requirements 1.8**
    """

    @given(
        job_name=_name_str,
        field_name=_name_str,
        values=st.lists(_value_str, min_size=1, max_size=50),
        max_entries=_max_entries,
    )
    @settings(max_examples=200)
    def test_history_length_never_exceeds_max(
        self,
        job_name: str,
        field_name: str,
        values: list[str],
        max_entries: int,
    ):
        """The history length never exceeds max_entries.

        **Validates: Requirements 1.8**
        """
        ah = ArgumentHistory(_max_entries=max_entries)

        for v in values:
            ah.record(job_name, field_name, v)

        history = ah.get_history(job_name, field_name)
        assert len(history) <= max_entries, (
            f"History length {len(history)} exceeds max_entries={max_entries}"
        )

    @given(
        job_name=_name_str,
        field_name=_name_str,
        values=st.lists(_value_str, min_size=1, max_size=50),
        max_entries=_max_entries,
    )
    @settings(max_examples=200)
    def test_retained_entries_are_most_recent(
        self,
        job_name: str,
        field_name: str,
        values: list[str],
        max_entries: int,
    ):
        """Retained entries are the N most recent distinct values.

        **Validates: Requirements 1.8**
        """
        ah = ArgumentHistory(_max_entries=max_entries)

        for v in values:
            ah.record(job_name, field_name, v)

        actual = ah.get_history(job_name, field_name)
        expected = _expected_history(values, max_entries)
        assert actual == expected, (
            f"Expected most recent {max_entries} entries: {expected}, got {actual}"
        )


# =============================================================================
# Property 4: JSON serialization round-trip
# =============================================================================


@pytest.mark.slow
class TestJsonSerializationRoundTrip:
    """Property 4: JSON serialization round-trip.

    For any valid ArgumentHistory state, serializing to a JSON dict via
    to_dict() and then reconstructing via from_dict() SHALL produce an
    ArgumentHistory with identical state.

    **Validates: Requirements 1.9**
    """

    @given(
        ops=_record_ops,
        max_entries=_max_entries,
    )
    @settings(max_examples=200)
    def test_to_dict_from_dict_preserves_state(
        self, ops: list[tuple[str, str, str]], max_entries: int
    ):
        """Serializing and deserializing preserves all state.

        **Validates: Requirements 1.9**
        """
        ah = ArgumentHistory(_max_entries=max_entries)

        for job_name, field_name, value in ops:
            ah.record(job_name, field_name, value)

        # Serialize then deserialize
        data = ah.to_dict()
        restored = ArgumentHistory.from_dict(data, max_entries=max_entries)

        # Compare state: all (job_name, field_name) pairs should have
        # identical histories

        pairs: set[tuple[str, str]] = set()
        for job_name, field_name, _ in ops:
            pairs.add((job_name, field_name))

        for job_name, field_name in pairs:
            original_history = ah.get_history(job_name, field_name)
            restored_history = restored.get_history(job_name, field_name)
            assert original_history == restored_history, (
                f"Round-trip mismatch for ({job_name!r}, {field_name!r}): "
                f"original={original_history}, restored={restored_history}"
            )

    @given(
        ops=_record_ops,
        max_entries=_max_entries,
    )
    @settings(max_examples=200)
    def test_round_trip_preserves_has_history(
        self, ops: list[tuple[str, str, str]], max_entries: int
    ):
        """has_history() returns the same result after round-trip.

        **Validates: Requirements 1.9**
        """
        ah = ArgumentHistory(_max_entries=max_entries)

        for job_name, field_name, value in ops:
            ah.record(job_name, field_name, value)

        data = ah.to_dict()
        restored = ArgumentHistory.from_dict(data, max_entries=max_entries)

        # Check all job names present in ops
        job_names = {job_name for job_name, _, _ in ops}
        for job_name in job_names:
            assert ah.has_history(job_name) == restored.has_history(job_name), (
                f"has_history({job_name!r}) mismatch after round-trip"
            )
