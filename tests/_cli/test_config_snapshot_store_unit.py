"""Unit tests for ConfigSnapshotStore edge cases.

# Feature: tui-config-inspector, Task 3.3

Deterministic unit tests covering edge cases, error paths, and boundary
conditions for ConfigSnapshotStore and ConfigSnapshot.

**Validates: Requirements 3.3, 3.4, 3.5, 3.7, 3.8, 3.9, 3.10**
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.data.config_snapshot_store import ConfigSnapshotStore


class TestGetLastSnapshotNoHistory:
    """Test get_last_snapshot for job with no history returns None.

    **Validates: Requirements 3.3**
    """

    def test_returns_none_for_unknown_job(self):
        store = ConfigSnapshotStore()
        assert store.get_last_snapshot("nonexistent-job") is None

    def test_returns_none_for_empty_store(self):
        store = ConfigSnapshotStore()
        assert store.get_last_snapshot("any-job") is None


class TestGetSnapshotsLimitZero:
    """Test get_snapshots with limit=0 returns empty list.

    **Validates: Requirements 3.4**
    """

    def test_limit_zero_returns_empty(self):
        store = ConfigSnapshotStore()
        store.record("my-job", {"field": "value"}, "success")
        assert store.get_snapshots("my-job", limit=0) == []

    def test_negative_limit_returns_empty(self):
        store = ConfigSnapshotStore()
        store.record("my-job", {"field": "value"}, "success")
        assert store.get_snapshots("my-job", limit=-1) == []
        assert store.get_snapshots("my-job", limit=-100) == []


class TestRecordInvalidOutcome:
    """Test record with invalid outcome raises ValueError.

    **Validates: Requirements 3.9, 3.10**
    """

    def test_invalid_outcome_raises_value_error(self):
        store = ConfigSnapshotStore()
        with pytest.raises(ValueError, match="Invalid outcome"):
            store.record("my-job", {"field": "value"}, "invalid")

    def test_empty_outcome_raises_value_error(self):
        store = ConfigSnapshotStore()
        with pytest.raises(ValueError, match="Invalid outcome"):
            store.record("my-job", {"field": "value"}, "")

    def test_typo_outcome_raises_value_error(self):
        store = ConfigSnapshotStore()
        with pytest.raises(ValueError, match="Invalid outcome"):
            store.record("my-job", {"field": "value"}, "sucess")


class TestLoadNonExistentFile:
    """Test load from non-existent file returns empty store.

    **Validates: Requirements 3.7**
    """

    def test_load_nonexistent_path_returns_empty(self, tmp_path: Path):
        nonexistent = tmp_path / "does_not_exist.json"
        store = ConfigSnapshotStore.load(nonexistent)
        assert store.get_last_snapshot("any-job") is None
        assert store.get_snapshots("any-job") == []


class TestLoadCorruptedJSON:
    """Test load from corrupted JSON renames to .bak and returns empty store.

    **Validates: Requirements 3.7**
    """

    def test_corrupted_json_renames_to_bak(self, tmp_path: Path):
        corrupt_file = tmp_path / "snapshots.json"
        corrupt_file.write_text("{ this is not valid JSON !!!", encoding="utf-8")

        store = ConfigSnapshotStore.load(corrupt_file)

        # Store should be empty
        assert store.get_last_snapshot("any-job") is None

        # Original file should be renamed to .bak
        bak_file = tmp_path / "snapshots.json.bak"
        assert bak_file.exists()
        assert not corrupt_file.exists()

    def test_corrupted_json_bak_content_preserved(self, tmp_path: Path):
        corrupt_file = tmp_path / "snapshots.json"
        bad_content = "{ not valid json"
        corrupt_file.write_text(bad_content, encoding="utf-8")

        ConfigSnapshotStore.load(corrupt_file)

        bak_file = tmp_path / "snapshots.json.bak"
        assert bak_file.read_text(encoding="utf-8") == bad_content


class TestFlushWithPathNone:
    """Test flush with path=None is a no-op (no error).

    **Validates: Requirements 3.8**
    """

    def test_flush_none_path_no_error(self):
        store = ConfigSnapshotStore(path=None)
        store.record("my-job", {"field": "value"}, "success")
        # Should not raise
        store.flush()

    def test_flush_none_path_does_not_create_files(self, tmp_path: Path):
        store = ConfigSnapshotStore(path=None)
        store.record("my-job", {"field": "value"}, "success")
        store.flush()
        # No files should be created anywhere in tmp_path
        assert list(tmp_path.iterdir()) == []


class TestRetentionEviction:
    """Test retention eviction: record 55 items with max_retention=50, verify only 50 remain.

    **Validates: Requirements 3.5**
    """

    def test_eviction_keeps_max_retention(self):
        store = ConfigSnapshotStore(max_retention=50)

        for i in range(55):
            store.record("my-job", {"iteration": i}, "success")

        snapshots = store.get_snapshots("my-job", limit=100)
        assert len(snapshots) == 50

    def test_eviction_keeps_most_recent(self):
        store = ConfigSnapshotStore(max_retention=50)

        for i in range(55):
            store.record("my-job", {"iteration": i}, "success")

        # The most recent should be iteration 54
        last = store.get_last_snapshot("my-job")
        assert last is not None
        assert last.values == {"iteration": 54}

    def test_eviction_removes_oldest(self):
        store = ConfigSnapshotStore(max_retention=50)

        for i in range(55):
            store.record("my-job", {"iteration": i}, "success")

        snapshots = store.get_snapshots("my-job", limit=100)
        # Oldest remaining should be iteration 5 (0-4 were evicted)
        oldest = snapshots[-1]
        assert oldest.values == {"iteration": 5}
