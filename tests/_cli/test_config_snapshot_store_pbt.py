"""Property-based tests for ConfigSnapshotStore.

# Feature: tui-config-inspector, Properties 7-9: ConfigSnapshotStore invariants

Tests validate the core correctness properties of ConfigSnapshotStore:
record ordering, retention limits, and serialization round-trips.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.data.config_snapshot_store import ConfigSnapshotStore

# =============================================================================
# Strategies
# =============================================================================

# Job names: non-empty alphanumeric strings with hyphens/underscores
_job_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=20,
)

# Field names for values dicts
_field_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=15,
)

# Field values: JSON-serializable primitives
_field_value = st.one_of(
    st.text(max_size=30),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.none(),
)

# A non-empty values dict (field_name -> value)
_values_dict = st.dictionaries(
    keys=_field_name,
    values=_field_value,
    min_size=1,
    max_size=10,
)

# Valid outcomes
_outcome = st.sampled_from(["success", "failure", "cancelled"])

# A record operation: (job_name, values, outcome)
_record_op = st.tuples(_job_name, _values_dict, _outcome)

# Small max_retention for testing enforcement
_max_retention = st.integers(min_value=1, max_value=10)


# =============================================================================
# Property 7: Record ordering
# =============================================================================


@pytest.mark.slow
class TestRecordOrdering:
    """Property 7: Record ordering.

    get_snapshots returns reverse chronological order,
    get_last_snapshot returns the most recently recorded.

    **Validates: Requirements 3.1, 3.2, 3.4**
    """

    @given(
        job_name=_job_name,
        records=st.lists(_record_op, min_size=1, max_size=20).map(
            lambda ops: [(v, o) for _, v, o in ops]
        ),
    )
    def test_get_snapshots_reverse_chronological(
        self, job_name: str, records: list[tuple[dict, str]]
    ):
        """get_snapshots returns snapshots in reverse chronological order.

        **Validates: Requirements 3.4**
        """
        store = ConfigSnapshotStore(max_retention=50)

        for values, outcome in records:
            store.record(job_name, values, outcome)

        snapshots = store.get_snapshots(job_name, limit=50)

        # Verify reverse chronological: timestamps should be non-increasing
        for i in range(len(snapshots) - 1):
            assert snapshots[i].timestamp >= snapshots[i + 1].timestamp, (
                f"Snapshots not in reverse chronological order at index {i}: "
                f"{snapshots[i].timestamp} < {snapshots[i + 1].timestamp}"
            )

    @given(
        job_name=_job_name,
        records=st.lists(_record_op, min_size=1, max_size=20).map(
            lambda ops: [(v, o) for _, v, o in ops]
        ),
    )
    def test_get_last_snapshot_is_most_recent(
        self, job_name: str, records: list[tuple[dict, str]]
    ):
        """get_last_snapshot returns the most recently recorded snapshot.

        **Validates: Requirements 3.1, 3.2**
        """
        store = ConfigSnapshotStore(max_retention=50)

        for values, outcome in records:
            store.record(job_name, values, outcome)

        last = store.get_last_snapshot(job_name)
        all_snapshots = store.get_snapshots(job_name, limit=50)

        assert last is not None
        # last_snapshot should be the first in reverse-chronological list
        assert last == all_snapshots[0], (
            f"get_last_snapshot returned {last}, but first in "
            f"get_snapshots is {all_snapshots[0]}"
        )

    @given(
        job_name=_job_name,
        records=st.lists(_record_op, min_size=2, max_size=20).map(
            lambda ops: [(v, o) for _, v, o in ops]
        ),
    )
    def test_last_snapshot_matches_last_record(
        self, job_name: str, records: list[tuple[dict, str]]
    ):
        """get_last_snapshot values and outcome match the last record call.

        **Validates: Requirements 3.1, 3.2**
        """
        store = ConfigSnapshotStore(max_retention=50)

        for values, outcome in records:
            store.record(job_name, values, outcome)

        last_values, last_outcome = records[-1]
        last = store.get_last_snapshot(job_name)

        assert last is not None
        assert last.values == last_values
        assert last.outcome == last_outcome
        assert last.job_name == job_name


# =============================================================================
# Property 8: Retention limit
# =============================================================================


@pytest.mark.slow
class TestRetentionLimit:
    """Property 8: Retention limit.

    After any number of records, stored snapshots per job never exceeds
    max_retention.

    **Validates: Requirements 3.5**
    """

    @given(
        job_name=_job_name,
        records=st.lists(_record_op, min_size=1, max_size=30).map(
            lambda ops: [(v, o) for _, v, o in ops]
        ),
        max_retention=_max_retention,
    )
    def test_snapshots_never_exceed_max_retention(
        self,
        job_name: str,
        records: list[tuple[dict, str]],
        max_retention: int,
    ):
        """The number of stored snapshots per job never exceeds max_retention.

        **Validates: Requirements 3.5**
        """
        store = ConfigSnapshotStore(max_retention=max_retention)

        for values, outcome in records:
            store.record(job_name, values, outcome)

        snapshots = store.get_snapshots(job_name, limit=max_retention + 10)
        assert len(snapshots) <= max_retention, (
            f"Store has {len(snapshots)} snapshots for job {job_name!r}, "
            f"exceeding max_retention={max_retention}"
        )

    @given(
        job_name=_job_name,
        records=st.lists(_record_op, min_size=1, max_size=30).map(
            lambda ops: [(v, o) for _, v, o in ops]
        ),
        max_retention=_max_retention,
    )
    def test_retention_preserves_most_recent(
        self,
        job_name: str,
        records: list[tuple[dict, str]],
        max_retention: int,
    ):
        """When retention limit is enforced, the most recent snapshots are kept.

        **Validates: Requirements 3.5**
        """
        store = ConfigSnapshotStore(max_retention=max_retention)

        for values, outcome in records:
            store.record(job_name, values, outcome)

        # The last snapshot should always be the most recently recorded
        last = store.get_last_snapshot(job_name)
        last_values, last_outcome = records[-1]

        assert last is not None
        assert last.values == last_values
        assert last.outcome == last_outcome

    @given(
        records_per_job=st.lists(
            st.tuples(
                _job_name,
                st.lists(_record_op, min_size=1, max_size=15).map(
                    lambda ops: [(v, o) for _, v, o in ops]
                ),
            ),
            min_size=1,
            max_size=5,
        ),
        max_retention=_max_retention,
    )
    def test_retention_enforced_per_job_independently(
        self,
        records_per_job: list[tuple[str, list[tuple[dict, str]]]],
        max_retention: int,
    ):
        """Retention limit is enforced independently for each job.

        **Validates: Requirements 3.5**
        """
        store = ConfigSnapshotStore(max_retention=max_retention)

        for job_name, records in records_per_job:
            for values, outcome in records:
                store.record(job_name, values, outcome)

        for job_name, _ in records_per_job:
            snapshots = store.get_snapshots(job_name, limit=max_retention + 10)
            assert len(snapshots) <= max_retention, (
                f"Job {job_name!r} has {len(snapshots)} snapshots, "
                f"exceeding max_retention={max_retention}"
            )


# =============================================================================
# Property 9: Serialization round-trip
# =============================================================================


@pytest.mark.slow
class TestSerializationRoundTrip:
    """Property 9: Serialization round-trip.

    from_dict(store.to_dict()) produces identical snapshots.

    **Validates: Requirements 3.6**
    """

    @given(
        ops=st.lists(_record_op, min_size=1, max_size=30),
    )
    def test_to_dict_from_dict_preserves_all_snapshots(
        self, ops: list[tuple[str, dict, str]]
    ):
        """Serializing and deserializing preserves all stored snapshots.

        **Validates: Requirements 3.6**
        """
        store = ConfigSnapshotStore(max_retention=50)

        for job_name, values, outcome in ops:
            store.record(job_name, values, outcome)

        # Serialize then deserialize
        data = store.to_dict()
        restored = ConfigSnapshotStore.from_dict(data)

        # Collect all unique job names
        job_names = {job_name for job_name, _, _ in ops}

        for job_name in job_names:
            original_snapshots = store.get_snapshots(job_name, limit=50)
            restored_snapshots = restored.get_snapshots(job_name, limit=50)

            assert len(original_snapshots) == len(restored_snapshots), (
                f"Snapshot count mismatch for job {job_name!r}: "
                f"original={len(original_snapshots)}, "
                f"restored={len(restored_snapshots)}"
            )

            for orig, rest in zip(original_snapshots, restored_snapshots, strict=False):
                assert orig.job_name == rest.job_name
                assert orig.timestamp == rest.timestamp
                assert orig.values == rest.values
                assert orig.outcome == rest.outcome

    @given(
        ops=st.lists(_record_op, min_size=1, max_size=20),
        max_retention=_max_retention,
    )
    def test_round_trip_preserves_after_retention_eviction(
        self, ops: list[tuple[str, dict, str]], max_retention: int
    ):
        """Round-trip preserves state even after retention eviction occurs.

        **Validates: Requirements 3.6**
        """
        store = ConfigSnapshotStore(max_retention=max_retention)

        for job_name, values, outcome in ops:
            store.record(job_name, values, outcome)

        data = store.to_dict()
        restored = ConfigSnapshotStore.from_dict(data)

        job_names = {job_name for job_name, _, _ in ops}

        for job_name in job_names:
            original_snapshots = store.get_snapshots(job_name, limit=max_retention)
            restored_snapshots = restored.get_snapshots(job_name, limit=max_retention)

            assert len(original_snapshots) == len(restored_snapshots), (
                f"Post-eviction round-trip mismatch for job {job_name!r}: "
                f"original={len(original_snapshots)}, "
                f"restored={len(restored_snapshots)}"
            )

            for orig, rest in zip(original_snapshots, restored_snapshots, strict=False):
                assert orig.job_name == rest.job_name
                assert orig.timestamp == rest.timestamp
                assert orig.values == rest.values
                assert orig.outcome == rest.outcome

    @given(
        ops=st.lists(_record_op, min_size=1, max_size=20),
    )
    def test_round_trip_preserves_get_last_snapshot(
        self, ops: list[tuple[str, dict, str]]
    ):
        """get_last_snapshot returns same result after round-trip.

        **Validates: Requirements 3.6**
        """
        store = ConfigSnapshotStore(max_retention=50)

        for job_name, values, outcome in ops:
            store.record(job_name, values, outcome)

        data = store.to_dict()
        restored = ConfigSnapshotStore.from_dict(data)

        job_names = {job_name for job_name, _, _ in ops}

        for job_name in job_names:
            original_last = store.get_last_snapshot(job_name)
            restored_last = restored.get_last_snapshot(job_name)

            if original_last is None:
                assert restored_last is None
            else:
                assert restored_last is not None
                assert original_last.job_name == restored_last.job_name
                assert original_last.timestamp == restored_last.timestamp
                assert original_last.values == restored_last.values
                assert original_last.outcome == restored_last.outcome
