"""Unit tests for config_diff module — compute_config_diff and ConfigDiffEntry."""

from __future__ import annotations

from functualize._cli.data.config_snapshot_store import ConfigSnapshot
from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.tui.config_diff import ConfigDiffEntry, compute_config_diff
from functualize._config.chain import ResolvedValue


def _rv(value: object, source_type: str = "file") -> ResolvedValue:
    """Helper to create a ResolvedValue for testing."""
    return ResolvedValue(
        value=value,
        source_type=source_type,
        source_id="test",
        key="test_key",
    )


def _pending(fields: dict[str, object]) -> PendingExecution:
    """Helper to create a PendingExecution with given field values."""
    resolved = {name: _rv(val) for name, val in fields.items()}
    return PendingExecution(job_name="test_job", resolved_values=resolved)


def _snapshot(fields: dict[str, object]) -> ConfigSnapshot:
    """Helper to create a ConfigSnapshot with given field values."""
    return ConfigSnapshot(
        job_name="test_job",
        timestamp=1000.0,
        values=fields,
        outcome="success",
    )


class TestComputeConfigDiff:
    """Tests for compute_config_diff function."""

    def test_all_unchanged(self) -> None:
        """All fields present in both with equal values → all 'unchanged'."""
        pending = _pending({"alpha": 1, "beta": "hello"})
        previous = _snapshot({"alpha": 1, "beta": "hello"})

        result = compute_config_diff(pending, previous)

        assert len(result) == 2
        assert all(e.status == "unchanged" for e in result)
        assert result[0].field_name == "alpha"
        assert result[1].field_name == "beta"

    def test_one_field_changed(self) -> None:
        """One field changed → status 'changed' with both values populated."""
        pending = _pending({"port": 8080})
        previous = _snapshot({"port": 3000})

        result = compute_config_diff(pending, previous)

        assert len(result) == 1
        entry = result[0]
        assert entry.status == "changed"
        assert entry.current_value == 8080
        assert entry.previous_value == 3000

    def test_field_new(self) -> None:
        """Field in current but not previous → status 'new'."""
        pending = _pending({"alpha": 1, "beta": 2})
        previous = _snapshot({"alpha": 1})

        result = compute_config_diff(pending, previous)

        beta_entry = next(e for e in result if e.field_name == "beta")
        assert beta_entry.status == "new"
        assert beta_entry.current_value == 2
        assert beta_entry.previous_value is None

    def test_field_removed(self) -> None:
        """Field in previous but not current → status 'removed'."""
        pending = _pending({"alpha": 1})
        previous = _snapshot({"alpha": 1, "beta": 2})

        result = compute_config_diff(pending, previous)

        beta_entry = next(e for e in result if e.field_name == "beta")
        assert beta_entry.status == "removed"
        assert beta_entry.current_value is None
        assert beta_entry.previous_value == 2

    def test_previous_none_all_new(self) -> None:
        """previous=None → all fields 'new'."""
        pending = _pending({"alpha": 1, "beta": 2, "gamma": 3})

        result = compute_config_diff(pending, None)

        assert len(result) == 3
        assert all(e.status == "new" for e in result)
        assert all(e.previous_value is None for e in result)

    def test_empty_resolved_values_with_previous_none(self) -> None:
        """Empty resolved_values with previous=None → empty list."""
        pending = _pending({})

        result = compute_config_diff(pending, None)

        assert result == []

    def test_result_sorted_alphabetically(self) -> None:
        """Result is sorted alphabetically by field_name."""
        pending = _pending({"zebra": 1, "apple": 2, "mango": 3})

        result = compute_config_diff(pending, None)

        field_names = [e.field_name for e in result]
        assert field_names == ["apple", "mango", "zebra"]

    def test_override_value_used_for_comparison(self) -> None:
        """Overridden values are used for current comparison."""
        pending = _pending({"port": 3000})
        pending.overrides["port"] = 8080
        previous = _snapshot({"port": 3000})

        result = compute_config_diff(pending, previous)

        entry = result[0]
        assert entry.status == "changed"
        assert entry.current_value == 8080
        assert entry.current_source == "cli"

    def test_override_source_reflected(self) -> None:
        """Source is 'cli' when field has an active override (SmartBar-as-CLI)."""
        pending = _pending({"port": 3000})
        pending.overrides["port"] = 9090

        result = compute_config_diff(pending, None)

        entry = result[0]
        assert entry.current_source == "cli"


class TestConfigDiffEntry:
    """Tests for ConfigDiffEntry dataclass."""

    def test_frozen(self) -> None:
        """ConfigDiffEntry is immutable."""
        entry = ConfigDiffEntry(
            field_name="test",
            status="new",
            current_value=42,
            current_source="file",
            previous_value=None,
            previous_source=None,
        )
        try:
            entry.field_name = "other"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass  # Expected for frozen dataclass
