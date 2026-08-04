"""Unit tests for PendingExecution edge cases.

Validates: Requirements 1.8, 1.9, 1.10
"""

from __future__ import annotations

import pytest

from functualize._cli.data.pending_execution import PendingExecution
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


class TestRemovedTargetApi:
    """the override-target bookkeeping API is removed."""

    def test_set_override_method_removed(self) -> None:
        """PendingExecution no longer exposes set_override."""
        pending = _pending({"port": 8080})
        assert not hasattr(pending, "set_override")

    def test_override_targets_field_removed(self) -> None:
        """PendingExecution no longer has an override_targets field."""
        pending = _pending({"port": 8080})
        assert not hasattr(pending, "override_targets")

    def test_valid_targets_constant_removed(self) -> None:
        """The module-level _VALID_TARGETS constant is gone."""
        import functualize._cli.data.pending_execution as mod

        assert not hasattr(mod, "_VALID_TARGETS")


class TestEffectiveValueUnknownField:
    """Requirement 1.10: effective_value raises KeyError for unknown field."""

    def test_raises_key_error_for_unknown_field(self) -> None:
        """effective_value raises KeyError when field is not in resolved_values."""
        pending = _pending({"alpha": 1, "beta": 2})

        with pytest.raises(KeyError, match="unknown_field"):
            pending.effective_value("unknown_field")

    def test_error_message_contains_field_name(self) -> None:
        """The KeyError message includes the requested field name."""
        pending = _pending({"port": 8080})

        with pytest.raises(KeyError, match="nonexistent"):
            pending.effective_value("nonexistent")


class TestClearOverrideNoOp:
    """Requirement 1.5 edge case: clear_override on non-overridden field is a no-op."""

    def test_clear_override_on_non_overridden_field(self) -> None:
        """clear_override on a field without override does nothing."""
        pending = _pending({"port": 8080, "host": "localhost"})

        # Should not raise or change state
        pending.clear_override("port")

        assert not pending.has_override("port")
        assert pending.override_count() == 0
        assert pending.effective_value("port") == 8080

    def test_clear_override_does_not_affect_other_overrides(self) -> None:
        """Clearing a non-overridden field doesn't affect existing overrides."""
        pending = _pending({"port": 8080, "host": "localhost"})
        pending.overrides["host"] = "remote"

        pending.clear_override("port")  # port has no override

        assert pending.has_override("host")
        assert pending.override_count() == 1
        assert pending.effective_value("host") == "remote"


class TestAllEffective:
    """Requirement 1.9: all_effective returns complete dict with correct source labels."""

    def test_returns_all_fields(self) -> None:
        """all_effective returns an entry for every field in resolved_values."""
        pending = _pending({"alpha": 1, "beta": "hello", "gamma": True})

        result = pending.all_effective()

        assert set(result.keys()) == {"alpha", "beta", "gamma"}

    def test_non_overridden_uses_resolved_source(self) -> None:
        """Non-overridden fields use the resolved source_type as label."""
        resolved = {
            "port": _rv(8080, source_type="cli"),
            "host": _rv("localhost", source_type="env"),
        }
        pending = PendingExecution(job_name="test_job", resolved_values=resolved)

        result = pending.all_effective()

        assert result["port"] == (8080, "cli")
        assert result["host"] == ("localhost", "env")

    def test_overridden_field_uses_cli_label(self) -> None:
        """Overridden fields use 'cli' as source label (SmartBar-as-CLI)."""
        pending = _pending({"port": 8080, "host": "localhost"})
        pending.overrides["port"] = 9090

        result = pending.all_effective()

        assert result["port"] == (9090, "cli")
        assert result["host"] == ("localhost", "file")

    def test_empty_resolved_values_returns_empty_dict(self) -> None:
        """all_effective with no resolved_values returns empty dict."""
        pending = _pending({})

        result = pending.all_effective()

        assert result == {}


class TestOverrideCount:
    """Requirement 1.7: override_count starts at 0 and increments/decrements."""

    def test_starts_at_zero(self) -> None:
        """override_count is 0 for a fresh PendingExecution."""
        pending = _pending({"alpha": 1, "beta": 2, "gamma": 3})

        assert pending.override_count() == 0

    def test_increments_on_set(self) -> None:
        """override_count increments when new overrides are added."""
        pending = _pending({"alpha": 1, "beta": 2, "gamma": 3})

        pending.overrides["alpha"] = 10
        assert pending.override_count() == 1

        pending.overrides["beta"] = 20
        assert pending.override_count() == 2

        pending.overrides["gamma"] = 30
        assert pending.override_count() == 3

    def test_decrements_on_clear(self) -> None:
        """override_count decrements when overrides are cleared."""
        pending = _pending({"alpha": 1, "beta": 2})
        pending.overrides["alpha"] = 10
        pending.overrides["beta"] = 20

        assert pending.override_count() == 2

        pending.clear_override("alpha")
        assert pending.override_count() == 1

        pending.clear_override("beta")
        assert pending.override_count() == 0

    def test_re_setting_same_field_does_not_double_count(self) -> None:
        """Setting an override on already-overridden field doesn't increase count."""
        pending = _pending({"port": 8080})

        pending.overrides["port"] = 9090
        assert pending.override_count() == 1

        pending.overrides["port"] = 7070
        assert pending.override_count() == 1
