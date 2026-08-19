"""Property-based tests for compute_config_diff (Properties 10, 11).

Tests compute_config_diff from functualize._cli.tui.config_diff:
- Property 10: Completeness — result contains exactly one entry per field in the
  union of current and previous field sets
- Property 11: Status correctness — "changed" implies current != previous,
  "unchanged" implies equality, "new" implies previous is None,
  "removed" implies current is None

# Feature: tui-config-inspector, Task 4.2
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.data.config_snapshot_store import ConfigSnapshot
from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.tui.config_diff import compute_config_diff
from functualize._config.chain import ResolvedValue

# =============================================================================
# Strategies
# =============================================================================

# Field names: non-empty text with letters, numbers, and dashes/underscores
_field_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=20,
)

# Arbitrary config values (JSON-serializable primitives)
_value_strategy = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.text(max_size=30),
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False),
)

# Source types for ResolvedValue. "session" is no longer a live source_type
# under the SmartBar-as-CLI model.
_source_type_strategy = st.sampled_from(["cli", "env", "file", "remote", "default"])

# Valid outcomes for ConfigSnapshot
_outcome_strategy = st.sampled_from(["success", "failure", "cancelled"])


@st.composite
def _resolved_value(draw: st.DrawFn, field_name: str | None = None) -> ResolvedValue:
    """Generate a ResolvedValue with an optional field name constraint."""
    key = field_name if field_name else draw(_field_name)
    return ResolvedValue(
        value=draw(_value_strategy),
        source_type=draw(_source_type_strategy),
        source_id=draw(st.text(min_size=1, max_size=15)),
        key=key,
        alternatives=[],
    )


@st.composite
def _pending_execution(draw: st.DrawFn) -> PendingExecution:
    """Generate a PendingExecution with random resolved_values and no overrides."""
    field_names = draw(st.lists(_field_name, min_size=1, max_size=10, unique=True))
    resolved_values: dict[str, ResolvedValue] = {}
    for name in field_names:
        resolved_values[name] = draw(_resolved_value(field_name=name))

    return PendingExecution(
        job_name=draw(st.text(min_size=1, max_size=15)),
        resolved_values=resolved_values,
    )


@st.composite
def _config_snapshot(
    draw: st.DrawFn, field_names: list[str] | None = None
) -> ConfigSnapshot:
    """Generate a ConfigSnapshot with given or random field names."""
    if field_names is None:
        field_names = draw(st.lists(_field_name, min_size=1, max_size=10, unique=True))
    values: dict[str, Any] = {}
    for name in field_names:
        values[name] = draw(_value_strategy)

    return ConfigSnapshot(
        job_name=draw(st.text(min_size=1, max_size=15)),
        timestamp=draw(st.floats(min_value=0.0, max_value=2_000_000_000.0)),
        values=values,
        outcome=draw(_outcome_strategy),
    )


@st.composite
def _pending_and_snapshot_with_overlap(
    draw: st.DrawFn,
) -> tuple[PendingExecution, ConfigSnapshot]:
    """Generate a PendingExecution and ConfigSnapshot with controlled overlap.

    Some fields may appear in both, some only in pending, some only in snapshot.
    """
    # Generate a shared pool of field names
    all_fields = draw(st.lists(_field_name, min_size=1, max_size=12, unique=True))

    # Partition: some in both, some only current, some only previous
    # Each field has a random chance of being in current, previous, or both
    current_fields: list[str] = []
    previous_fields: list[str] = []

    for field in all_fields:
        where = draw(st.sampled_from(["both", "current_only", "previous_only"]))
        if where == "both":
            current_fields.append(field)
            previous_fields.append(field)
        elif where == "current_only":
            current_fields.append(field)
        else:
            previous_fields.append(field)

    # Ensure at least one field exists somewhere
    if not current_fields and not previous_fields:
        current_fields.append(all_fields[0])

    # Build PendingExecution
    resolved_values: dict[str, ResolvedValue] = {}
    for name in current_fields:
        resolved_values[name] = draw(_resolved_value(field_name=name))

    pe = PendingExecution(
        job_name=draw(st.text(min_size=1, max_size=15)),
        resolved_values=resolved_values,
    )

    # Build ConfigSnapshot
    snapshot_values: dict[str, Any] = {}
    for name in previous_fields:
        snapshot_values[name] = draw(_value_strategy)

    snapshot = ConfigSnapshot(
        job_name=pe.job_name,
        timestamp=draw(st.floats(min_value=0.0, max_value=2_000_000_000.0)),
        values=snapshot_values,
        outcome=draw(_outcome_strategy),
    )

    return pe, snapshot


# =============================================================================
# Property 10: Completeness
# =============================================================================


@pytest.mark.slow
class TestCompleteness:
    """Property 10: Completeness.

    Result contains exactly one entry per field in the union of current and
    previous field sets.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**
    """

    @given(data=_pending_and_snapshot_with_overlap())
    def test_entry_count_equals_union_size(
        self,
        data: tuple[PendingExecution, ConfigSnapshot],
    ) -> None:
        """Number of result entries equals the size of the union of field sets.

        **Validates: Requirements 4.1**
        """
        pe, snapshot = data
        result = compute_config_diff(pe, snapshot)

        current_fields = set(pe.resolved_values.keys())
        previous_fields = set(snapshot.values.keys())
        expected_count = len(current_fields | previous_fields)

        assert len(result) == expected_count, (
            f"Expected {expected_count} entries (union of "
            f"{len(current_fields)} current + {len(previous_fields)} previous), "
            f"got {len(result)}"
        )

    @given(data=_pending_and_snapshot_with_overlap())
    def test_every_field_in_union_has_exactly_one_entry(
        self,
        data: tuple[PendingExecution, ConfigSnapshot],
    ) -> None:
        """Each field in the union of current and previous appears exactly once.

        **Validates: Requirements 4.1**
        """
        pe, snapshot = data
        result = compute_config_diff(pe, snapshot)

        current_fields = set(pe.resolved_values.keys())
        previous_fields = set(snapshot.values.keys())
        expected_fields = current_fields | previous_fields

        result_fields = [entry.field_name for entry in result]

        # No duplicates
        assert len(result_fields) == len(set(result_fields)), (
            f"Duplicate field names in result: {result_fields}"
        )

        # Exact match with expected union
        assert set(result_fields) == expected_fields, (
            f"Result fields {set(result_fields)} != expected union {expected_fields}"
        )

    @given(pe=_pending_execution())
    def test_completeness_when_previous_is_none(
        self,
        pe: PendingExecution,
    ) -> None:
        """When previous is None, result has one entry per field in resolved_values.

        **Validates: Requirements 4.1, 4.4**
        """
        result = compute_config_diff(pe, None)

        expected_fields = set(pe.resolved_values.keys())
        result_fields = {entry.field_name for entry in result}

        assert result_fields == expected_fields, (
            f"With previous=None, result fields {result_fields} != "
            f"resolved_values keys {expected_fields}"
        )
        assert len(result) == len(expected_fields)

    @given(data=_pending_and_snapshot_with_overlap())
    def test_result_is_sorted_alphabetically(
        self,
        data: tuple[PendingExecution, ConfigSnapshot],
    ) -> None:
        """Result entries are sorted alphabetically by field_name.

        **Validates: Requirements 4.1**
        """
        pe, snapshot = data
        result = compute_config_diff(pe, snapshot)

        field_names = [entry.field_name for entry in result]
        assert field_names == sorted(field_names), f"Result not sorted: {field_names}"


# =============================================================================
# Property 11: Status correctness
# =============================================================================


@pytest.mark.slow
class TestStatusCorrectness:
    """Property 11: Status correctness.

    "changed" implies current_value != previous_value,
    "unchanged" implies equality,
    "new" implies previous_value is None,
    "removed" implies current_value is None.

    **Validates: Requirements 4.2, 4.3, 4.4, 4.5**
    """

    @given(data=_pending_and_snapshot_with_overlap())
    def test_changed_implies_values_differ(
        self,
        data: tuple[PendingExecution, ConfigSnapshot],
    ) -> None:
        """Every entry with status "changed" has current_value != previous_value.

        **Validates: Requirements 4.2**
        """
        pe, snapshot = data
        result = compute_config_diff(pe, snapshot)

        for entry in result:
            if entry.status == "changed":
                assert entry.current_value != entry.previous_value, (
                    f"Field {entry.field_name!r} has status 'changed' but "
                    f"current_value ({entry.current_value!r}) == "
                    f"previous_value ({entry.previous_value!r})"
                )

    @given(data=_pending_and_snapshot_with_overlap())
    def test_unchanged_implies_values_equal(
        self,
        data: tuple[PendingExecution, ConfigSnapshot],
    ) -> None:
        """Every entry with status "unchanged" has current_value == previous_value.

        **Validates: Requirements 4.3**
        """
        pe, snapshot = data
        result = compute_config_diff(pe, snapshot)

        for entry in result:
            if entry.status == "unchanged":
                assert entry.current_value == entry.previous_value, (
                    f"Field {entry.field_name!r} has status 'unchanged' but "
                    f"current_value ({entry.current_value!r}) != "
                    f"previous_value ({entry.previous_value!r})"
                )

    @given(data=_pending_and_snapshot_with_overlap())
    def test_new_implies_previous_is_none(
        self,
        data: tuple[PendingExecution, ConfigSnapshot],
    ) -> None:
        """Every entry with status "new" has previous_value is None.

        **Validates: Requirements 4.4**
        """
        pe, snapshot = data
        result = compute_config_diff(pe, snapshot)

        for entry in result:
            if entry.status == "new":
                assert entry.previous_value is None, (
                    f"Field {entry.field_name!r} has status 'new' but "
                    f"previous_value is {entry.previous_value!r}, not None"
                )

    @given(data=_pending_and_snapshot_with_overlap())
    def test_removed_implies_current_is_none(
        self,
        data: tuple[PendingExecution, ConfigSnapshot],
    ) -> None:
        """Every entry with status "removed" has current_value is None.

        **Validates: Requirements 4.5**
        """
        pe, snapshot = data
        result = compute_config_diff(pe, snapshot)

        for entry in result:
            if entry.status == "removed":
                assert entry.current_value is None, (
                    f"Field {entry.field_name!r} has status 'removed' but "
                    f"current_value is {entry.current_value!r}, not None"
                )

    @given(pe=_pending_execution())
    def test_all_new_when_previous_is_none(
        self,
        pe: PendingExecution,
    ) -> None:
        """When previous is None, all entries have status "new".

        **Validates: Requirements 4.4**
        """
        result = compute_config_diff(pe, None)

        for entry in result:
            assert entry.status == "new", (
                f"Field {entry.field_name!r} has status {entry.status!r} "
                f"but expected 'new' when previous is None"
            )
            assert entry.previous_value is None

    @given(data=_pending_and_snapshot_with_overlap())
    def test_status_is_always_valid(
        self,
        data: tuple[PendingExecution, ConfigSnapshot],
    ) -> None:
        """Every entry has a status in {"changed", "unchanged", "new", "removed"}.

        **Validates: Requirements 4.2, 4.3, 4.4, 4.5**
        """
        pe, snapshot = data
        result = compute_config_diff(pe, snapshot)
        valid_statuses = {"changed", "unchanged", "new", "removed"}

        for entry in result:
            assert entry.status in valid_statuses, (
                f"Field {entry.field_name!r} has invalid status {entry.status!r}"
            )
