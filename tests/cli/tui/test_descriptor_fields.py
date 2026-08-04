"""Unit tests for descriptor_fields.get_descriptor_fields."""

from __future__ import annotations

from types import SimpleNamespace

from functualize._cli.tui.descriptor_fields import get_descriptor_fields


class TestGetDescriptorFields:
    """Tests for get_descriptor_fields()."""

    def test_prefers_config_fields_when_both_present(self) -> None:
        """config_fields wins over parameters when both are non-empty."""
        descriptor = SimpleNamespace(config_fields=["config_a"], parameters=["param_a"])
        assert get_descriptor_fields(descriptor) == ["config_a"]

    def test_falls_back_to_parameters_when_config_fields_empty(self) -> None:
        """Falls back to parameters when config_fields is empty."""
        descriptor = SimpleNamespace(config_fields=[], parameters=["param_a"])
        assert get_descriptor_fields(descriptor) == ["param_a"]

    def test_falls_back_to_parameters_when_config_fields_missing(self) -> None:
        """Falls back to parameters when config_fields attribute is absent."""
        descriptor = SimpleNamespace(parameters=["param_a"])
        assert get_descriptor_fields(descriptor) == ["param_a"]

    def test_returns_none_when_neither_present(self) -> None:
        """Returns None when neither config_fields nor parameters is set."""
        descriptor = SimpleNamespace()
        assert get_descriptor_fields(descriptor) is None

    def test_returns_falsy_when_both_empty(self) -> None:
        """Returns a falsy value when both config_fields and parameters are empty."""
        descriptor = SimpleNamespace(config_fields=[], parameters=[])
        assert not get_descriptor_fields(descriptor)
