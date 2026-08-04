"""CLI/TUI adapter integration for the pluggable configuration system.

Provides an adapter that wraps a Click context to:
- Distinguish explicitly-provided CLI/TUI arguments from Click defaults
- Map Click option names to configuration key paths (dot-separated namespaces)
- Create a CliSource from explicitly-provided values
- Validate keys against the active Settings_Model

The adapter implements Requirement 6 (CLI and TUI as Configuration Sources):
- 6.1: Accept values from CLI options as a source in Resolution_Chain
- 6.2: Accept values from TUI inputs as a source in Resolution_Chain
- 6.3: Treat explicitly provided CLI/TUI values at highest precedence
- 6.4: Provide adapter interface implementing Source protocol
- 6.5: Map CLI option names to config key paths using dot-separated convention
- 6.6: Raise error for unrecognized keys not in active Settings_Model
"""

from __future__ import annotations

from typing import Any

import click

from functualize._config.errors import ConfigurationError
from functualize._config.sources import CliSource


class UnrecognizedCliKeyError(ConfigurationError):
    """CLI/TUI value provided for a key not in the active Settings_Model.

    Attributes:
        key: The unrecognized CLI option key.
        available_keys: List of valid keys from the active Settings_Model.
    """

    def __init__(self, key: str, available_keys: list[str]) -> None:
        self.key = key
        self.available_keys = available_keys
        available_str = (
            ", ".join(sorted(available_keys)) if available_keys else "(none)"
        )
        super().__init__(
            f"Unrecognized CLI key '{key}'. "
            f"Available keys in active Settings_Model: {available_str}"
        )


def extract_explicit_params(ctx: click.Context) -> dict[str, Any]:
    """Extract explicitly-provided parameters from a Click context.

    Distinguishes between user-provided values and Click defaults by
    inspecting the context's parameter source information. Only parameters
    that were explicitly supplied via the command line (or TUI input) are
    returned.

    Click tracks the source of each parameter value. A parameter is
    considered "explicitly provided" if its source is COMMANDLINE (from
    CLI invocation). Parameters with source DEFAULT, ENVIRONMENT, or
    PROMPT are excluded (those are handled by other sources in the
    Resolution_Chain).

    Args:
        ctx: The Click context containing parsed parameters.

    Returns:
        Dict mapping parameter names (as they appear in the Click context)
        to their explicitly-provided values. Only includes parameters that
        were explicitly supplied by the user.
    """
    explicit: dict[str, Any] = {}

    for param_name, value in ctx.params.items():
        source = ctx.get_parameter_source(param_name)
        if source == click.core.ParameterSource.COMMANDLINE:
            explicit[param_name] = value

    return explicit


def map_option_name_to_key(option_name: str) -> tuple[str | None, str]:
    """Map a Click option name to a configuration key path.

    Applies the same normalization as CliSource._parse_cli_key:
    - Strips leading dashes
    - Converts hyphens to underscores
    - Splits on dot for section.key namespacing

    Args:
        option_name: The raw option name from the CLI context.

    Returns:
        Tuple of (section_or_None, normalized_key).
    """
    return CliSource._parse_cli_key(option_name)


def validate_keys_against_model(
    keys: dict[str, Any],
    model_fields: set[str],
    *,
    section: str | None = None,
) -> None:
    """Validate that all provided CLI keys exist in the active Settings_Model.

    Checks that each explicitly-provided CLI key corresponds to a field in
    the model. Keys that don't match any field cause an error.

    Args:
        keys: Dict of normalized key names to their values.
        model_fields: Set of valid field names from the active Settings_Model.
        section: Optional section name for error context.

    Raises:
        UnrecognizedCliKeyError: If any key is not in the model's fields.
    """
    for key in keys:
        if key not in model_fields:
            available = sorted(model_fields)
            raise UnrecognizedCliKeyError(key=key, available_keys=available)


def create_cli_source_from_context(
    ctx: click.Context,
    *,
    model_fields: set[str] | None = None,
    section: str | None = None,
) -> CliSource:
    """Create a CliSource from a Click context.

    This is the main integration point for wiring CLI/TUI arguments into
    the configuration Resolution_Chain. It:

    1. Extracts only explicitly-provided parameters from the context
    2. Maps option names to config key paths (hyphens → underscores, dot namespacing)
    3. Optionally validates keys against a Settings_Model's fields

    Args:
        ctx: The Click context with parsed parameters.
        model_fields: Optional set of valid field names from the active
            Settings_Model. If provided, unrecognized keys raise an error.
        section: Optional section name for namespaced keys.

    Returns:
        A CliSource containing only explicitly-provided values, with
        option names mapped to config key paths.

    Raises:
        UnrecognizedCliKeyError: If model_fields is provided and an
            explicitly-provided key doesn't match any field.
    """
    # Step 1: Extract only explicitly-provided parameters
    explicit_params = extract_explicit_params(ctx)

    # Step 2: Build the normalized values dict for CliSource
    # The CliSource constructor already handles hyphen→underscore and dot→section
    # mapping, so we pass option names as-is (they may have underscores from
    # Click's normalization of --kebab-case to param names with underscores).
    normalized_values: dict[str, Any] = {}
    for param_name, value in explicit_params.items():
        # Click normalizes --my-option to my_option in ctx.params
        # We need to apply the section prefix if provided
        if section and "." not in param_name:
            key_for_source = f"{section}.{param_name}"
        else:
            key_for_source = param_name
        normalized_values[key_for_source] = value

    # Step 3: Validate keys against the model if provided
    if model_fields is not None:
        # Parse the keys to get the actual key names (without section prefix)
        for param_name in explicit_params:
            parsed_section, parsed_key = CliSource._parse_cli_key(param_name)
            # If a section was injected by us, validate the bare key
            # Otherwise validate the full mapped key
            key_to_validate = parsed_key
            if key_to_validate not in model_fields:
                raise UnrecognizedCliKeyError(
                    key=key_to_validate,
                    available_keys=sorted(model_fields),
                )

    # Step 4: Create and return the CliSource
    return CliSource(normalized_values)


def create_cli_source_from_params(
    params: dict[str, Any],
    *,
    model_fields: set[str] | None = None,
    section: str | None = None,
) -> CliSource:
    """Create a CliSource from pre-extracted explicit parameters.

    This is a lower-level API useful when the explicit values have already
    been extracted (e.g., from a TUI form submission where all submitted
    values are explicit by definition).

    Args:
        params: Dict of parameter names to their values. All values are
            treated as explicitly provided.
        model_fields: Optional set of valid field names from the active
            Settings_Model. If provided, unrecognized keys raise an error.
        section: Optional section name to prefix keys with.

    Returns:
        A CliSource containing the provided values with names mapped to
        config key paths.

    Raises:
        UnrecognizedCliKeyError: If model_fields is provided and a key
            doesn't match any field.
    """
    # Build the values dict with optional section prefixing
    values: dict[str, Any] = {}
    for param_name, value in params.items():
        if section and "." not in param_name:
            key_for_source = f"{section}.{param_name}"
        else:
            key_for_source = param_name
        values[key_for_source] = value

    # Validate keys against the model if provided
    if model_fields is not None:
        for param_name in params:
            _section, parsed_key = CliSource._parse_cli_key(param_name)
            if parsed_key not in model_fields:
                raise UnrecognizedCliKeyError(
                    key=parsed_key,
                    available_keys=sorted(model_fields),
                )

    return CliSource(values)
