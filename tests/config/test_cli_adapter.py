"""Unit tests for the CLI/TUI adapter integration.

Tests the adapter that captures explicitly-provided Typer args into CliSource,
distinguishes user-provided values from Typer defaults, maps option names to
config key paths, and validates keys against the active Settings_Model.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

from __future__ import annotations

from typing import Any

import click
import pytest

from functualize._config.cli_adapter import (
    UnrecognizedCliKeyError,
    create_cli_source_from_context,
    create_cli_source_from_params,
    extract_explicit_params,
    map_option_name_to_key,
    validate_keys_against_model,
)
from functualize._config.sources import CliSource


def _make_click_context(
    params: dict[str, Any],
    *,
    explicit_keys: set[str] | None = None,
) -> click.Context:
    """Create a mock Click context with parameter source tracking.

    Args:
        params: All parameters (both explicit and default).
        explicit_keys: Set of keys that were explicitly provided via CLI.
            If None, all keys are treated as COMMANDLINE source.

    Returns:
        A Click Context with proper get_parameter_source behavior.
    """
    if explicit_keys is None:
        explicit_keys = set(params.keys())

    # Create a real Click command to attach context to
    @click.command()
    def dummy() -> None:
        pass

    ctx = click.Context(dummy)
    ctx.params = dict(params)

    # Mock get_parameter_source to distinguish explicit from default
    def mock_get_parameter_source(param_name: str) -> click.core.ParameterSource | None:
        if param_name in explicit_keys:
            return click.core.ParameterSource.COMMANDLINE
        return click.core.ParameterSource.DEFAULT

    ctx.get_parameter_source = mock_get_parameter_source  # type: ignore[assignment]

    return ctx


class TestExtractExplicitParams:
    """Tests for extract_explicit_params function."""

    def test_extracts_only_commandline_sourced_params(self) -> None:
        """Only parameters sourced from COMMANDLINE are extracted."""
        ctx = _make_click_context(
            params={"port": 8080, "host": "localhost", "debug": False},
            explicit_keys={"port"},
        )

        result = extract_explicit_params(ctx)

        assert result == {"port": 8080}
        assert "host" not in result
        assert "debug" not in result

    def test_all_explicit_params_extracted(self) -> None:
        """All explicitly-provided parameters are extracted."""
        ctx = _make_click_context(
            params={"port": 8080, "host": "localhost", "debug": True},
            explicit_keys={"port", "host", "debug"},
        )

        result = extract_explicit_params(ctx)

        assert result == {"port": 8080, "host": "localhost", "debug": True}

    def test_empty_when_no_explicit_params(self) -> None:
        """Returns empty dict when all params are defaults."""
        ctx = _make_click_context(
            params={"port": 8080, "debug": False},
            explicit_keys=set(),
        )

        result = extract_explicit_params(ctx)

        assert result == {}

    def test_empty_context_params(self) -> None:
        """Returns empty dict when context has no params."""
        ctx = _make_click_context(params={})

        result = extract_explicit_params(ctx)

        assert result == {}

    def test_preserves_none_values_when_explicit(self) -> None:
        """None values are included when explicitly provided."""
        ctx = _make_click_context(
            params={"output": None, "verbose": False},
            explicit_keys={"output"},
        )

        result = extract_explicit_params(ctx)

        assert result == {"output": None}


class TestMapOptionNameToKey:
    """Tests for map_option_name_to_key function."""

    def test_simple_option_no_section(self) -> None:
        """Simple option name maps to (None, key)."""
        section, key = map_option_name_to_key("port")
        assert section is None
        assert key == "port"

    def test_hyphens_converted_to_underscores(self) -> None:
        """Hyphens in option names become underscores."""
        section, key = map_option_name_to_key("log-level")
        assert section is None
        assert key == "log_level"

    def test_dot_separated_produces_section_key(self) -> None:
        """Dot in option name produces section.key split."""
        section, key = map_option_name_to_key("database.port")
        assert section == "database"
        assert key == "port"

    def test_dot_with_hyphens_in_both_parts(self) -> None:
        """Hyphens in both section and key parts are converted."""
        section, key = map_option_name_to_key("my-section.my-key")
        assert section == "my_section"
        assert key == "my_key"

    def test_leading_dashes_stripped(self) -> None:
        """Leading dashes from --option style are stripped."""
        section, key = map_option_name_to_key("--port")
        assert section is None
        assert key == "port"

    def test_leading_dashes_with_dot(self) -> None:
        """Leading dashes stripped even with dot notation."""
        section, key = map_option_name_to_key("--database.port")
        assert section == "database"
        assert key == "port"


class TestValidateKeysAgainstModel:
    """Tests for validate_keys_against_model function."""

    def test_valid_keys_pass(self) -> None:
        """No error raised when all keys are in the model."""
        keys = {"port": 8080, "host": "localhost"}
        model_fields = {"port", "host", "debug"}

        # Should not raise
        validate_keys_against_model(keys, model_fields)

    def test_unrecognized_key_raises_error(self) -> None:
        """UnrecognizedCliKeyError raised for keys not in model."""
        keys = {"port": 8080, "unknown_key": "value"}
        model_fields = {"port", "host", "debug"}

        with pytest.raises(UnrecognizedCliKeyError) as exc_info:
            validate_keys_against_model(keys, model_fields)

        assert exc_info.value.key == "unknown_key"
        assert sorted(exc_info.value.available_keys) == ["debug", "host", "port"]

    def test_empty_keys_pass(self) -> None:
        """No error when no keys are provided."""
        validate_keys_against_model({}, {"port", "host"})

    def test_empty_model_fields_raises_for_any_key(self) -> None:
        """Any key is unrecognized when model has no fields."""
        with pytest.raises(UnrecognizedCliKeyError) as exc_info:
            validate_keys_against_model({"port": 8080}, set())

        assert exc_info.value.key == "port"
        assert exc_info.value.available_keys == []


class TestCreateCliSourceFromContext:
    """Tests for create_cli_source_from_context function."""

    def test_creates_cli_source_with_explicit_values(self) -> None:
        """Creates CliSource containing only explicit values."""
        ctx = _make_click_context(
            params={"port": 8080, "host": "localhost", "debug": False},
            explicit_keys={"port", "host"},
        )

        source = create_cli_source_from_context(ctx)

        assert isinstance(source, CliSource)
        assert source.source_type == "cli"

    def test_excludes_default_values(self) -> None:
        """Default values are excluded from the CliSource."""
        ctx = _make_click_context(
            params={"port": 8080, "debug": False},
            explicit_keys={"port"},
        )

        source = create_cli_source_from_context(ctx)

        # port was explicit — should be retrievable
        assert source.has("port") is True
        assert source.get("port") == 8080

        # debug was a default — should NOT be in the source
        assert source.has("debug") is False

    def test_section_prefix_applied(self) -> None:
        """When section is provided, keys are prefixed with section."""
        ctx = _make_click_context(
            params={"port": 8080},
            explicit_keys={"port"},
        )

        source = create_cli_source_from_context(ctx, section="database")

        # Key should be accessible with section
        assert source.has("port", section="database") is True
        assert source.get("port", section="database") == 8080

        # Key should NOT be accessible without section
        assert source.has("port") is False

    def test_validation_passes_for_valid_keys(self) -> None:
        """No error when all explicit keys are in the model."""
        ctx = _make_click_context(
            params={"port": 8080, "host": "localhost"},
            explicit_keys={"port"},
        )

        # Should not raise
        source = create_cli_source_from_context(
            ctx, model_fields={"port", "host", "debug"}
        )
        assert source.has("port") is True

    def test_validation_raises_for_unrecognized_key(self) -> None:
        """UnrecognizedCliKeyError raised for keys not in model."""
        ctx = _make_click_context(
            params={"unknown_option": "value"},
            explicit_keys={"unknown_option"},
        )

        with pytest.raises(UnrecognizedCliKeyError) as exc_info:
            create_cli_source_from_context(ctx, model_fields={"port", "host"})

        assert exc_info.value.key == "unknown_option"

    def test_no_validation_when_model_fields_not_provided(self) -> None:
        """No validation when model_fields is None."""
        ctx = _make_click_context(
            params={"anything": "value"},
            explicit_keys={"anything"},
        )

        # Should not raise even though "anything" is not in any model
        source = create_cli_source_from_context(ctx)
        assert source.has("anything") is True


class TestCreateCliSourceFromParams:
    """Tests for create_cli_source_from_params function (TUI integration)."""

    def test_creates_source_from_pre_extracted_params(self) -> None:
        """All provided params become source values (TUI case)."""
        params = {"port": 8080, "host": "localhost"}

        source = create_cli_source_from_params(params)

        assert source.has("port") is True
        assert source.get("port") == 8080
        assert source.has("host") is True
        assert source.get("host") == "localhost"

    def test_section_prefix_applied(self) -> None:
        """Section prefix groups keys under a namespace."""
        params = {"port": 5432, "name": "mydb"}

        source = create_cli_source_from_params(params, section="database")

        assert source.has("port", section="database") is True
        assert source.get("port", section="database") == 5432
        assert source.has("port") is False

    def test_validation_raises_for_unrecognized_key(self) -> None:
        """Validation catches keys not in the model."""
        params = {"bad_key": "value"}

        with pytest.raises(UnrecognizedCliKeyError) as exc_info:
            create_cli_source_from_params(params, model_fields={"port", "host"})

        assert exc_info.value.key == "bad_key"

    def test_empty_params_produces_empty_source(self) -> None:
        """Empty params dict produces a source with no values."""
        source = create_cli_source_from_params({})

        assert source.has("anything") is False

    def test_dot_notation_in_params_maps_to_section_key(self) -> None:
        """Params with dots already set section.key directly."""
        params = {"database.port": 5432}

        source = create_cli_source_from_params(params)

        assert source.has("port", section="database") is True
        assert source.get("port", section="database") == 5432


class TestUnrecognizedCliKeyError:
    """Tests for the UnrecognizedCliKeyError exception."""

    def test_error_message_contains_key(self) -> None:
        """Error message includes the unrecognized key."""
        err = UnrecognizedCliKeyError("bad_key", ["port", "host"])
        assert "bad_key" in str(err)

    def test_error_message_contains_available_keys(self) -> None:
        """Error message lists available keys."""
        err = UnrecognizedCliKeyError("bad_key", ["port", "host"])
        assert "host" in str(err)
        assert "port" in str(err)

    def test_error_message_with_empty_available_keys(self) -> None:
        """Error message handles empty available keys."""
        err = UnrecognizedCliKeyError("bad_key", [])
        assert "(none)" in str(err)

    def test_error_attributes(self) -> None:
        """Error stores key and available_keys as attributes."""
        err = UnrecognizedCliKeyError("bad_key", ["port", "host"])
        assert err.key == "bad_key"
        assert err.available_keys == ["port", "host"]

    def test_is_configuration_error(self) -> None:
        """UnrecognizedCliKeyError is a ConfigurationError."""
        from functualize._config.errors import ConfigurationError

        err = UnrecognizedCliKeyError("key", [])
        assert isinstance(err, ConfigurationError)
