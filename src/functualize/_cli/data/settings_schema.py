"""Setting schemas and value validation.

Validates user input against defined constraints for each setting. Lives in
``_cli/data/`` (pure logic, no Textual) so that ``func_settings`` — also in
``data/`` — can build its catalog without importing the ``tui`` package,
whose ``__init__`` imports the settings panel, which imports the catalog: a
cycle. ``_cli/tui/settings_validator`` re-exports everything here for its
existing importers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingSchema:
    """Schema definition for a single TUI setting."""

    name: str
    type: str  # "enum" | "int" | "bool" | "list" | "str"
    description: str
    choices: list[str] | None = None  # For enum type
    min_value: int | None = None  # For int type
    max_value: int | None = None  # For int type
    max_items: int | None = None  # For list type


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a setting value."""

    valid: bool
    error: str | None = None  # Human-readable error message if invalid


# Define the TUI setting schemas per Requirements 12.4
SETTING_SCHEMAS: dict[str, SettingSchema] = {
    "default_surface": SettingSchema(
        name="default_surface",
        type="enum",
        description="Where a job renders when run from the TUI",
        choices=["panel", "stdout"],
    ),
    "show_session_stamp": SettingSchema(
        name="show_session_stamp",
        type="bool",
        description="Show session stamp on TUI exit",
    ),
    "history_retention": SettingSchema(
        name="history_retention",
        type="int",
        description="Number of history entries to retain",
        min_value=1,
        max_value=1000,
    ),
    "signature_enabled": SettingSchema(
        name="signature_enabled",
        type="bool",
        description="Show signature slot",
    ),
    "display_auto_switch": SettingSchema(
        name="display_auto_switch",
        type="enum",
        description="Display panel auto-switch behavior",
        choices=["auto", "indicator", "off"],
    ),
    "default_override_target": SettingSchema(
        name="default_override_target",
        type="enum",
        description="Default persistence target for overrides",
        choices=["file", "env"],
    ),
    "theme": SettingSchema(
        name="theme",
        type="str",
        description="Active theme ID (must match registered theme_id)",
    ),
}


def validate_setting(setting_name: str, value: str) -> ValidationResult:
    """Validate a TUI setting value against its schema, looked up by name.

    Args:
        setting_name: The setting key to validate.
        value: The user-provided value string.

    Returns:
        ValidationResult with valid=True if acceptable, or
        valid=False with error message describing the constraint.
    """
    schema = SETTING_SCHEMAS.get(setting_name)
    if schema is None:
        return ValidationResult(valid=False, error=f"Unknown setting: {setting_name}")
    return validate_against(schema, value)


def validate_against(schema: SettingSchema, value: str) -> ValidationResult:
    """Validate a value against an explicit schema.

    The schema-first entry point: the func-settings catalog covers far more
    than the 9 TUI settings in :data:`SETTING_SCHEMAS`, so it passes its own
    schemas here rather than being limited to that dict.
    """
    if schema.type == "enum":
        return _validate_enum(value, schema.choices or [])
    elif schema.type == "int":
        return _validate_int(value, schema.min_value, schema.max_value)
    elif schema.type == "bool":
        return _validate_bool(value)
    elif schema.type == "list":
        return _validate_list(value, schema.max_items or 50)
    elif schema.type == "str":
        return _validate_str(value)

    return ValidationResult(valid=False, error=f"Unknown type: {schema.type}")


def _validate_enum(value: str, choices: list[str]) -> ValidationResult:
    if value in choices:
        return ValidationResult(valid=True)
    return ValidationResult(
        valid=False,
        error=f"Must be one of: {', '.join(choices)}",
    )


def _validate_int(
    value: str, min_val: int | None, max_val: int | None
) -> ValidationResult:
    try:
        n = int(value)
    except ValueError:
        return ValidationResult(valid=False, error="Must be an integer")

    if min_val is not None and n < min_val:
        return ValidationResult(valid=False, error=f"Must be >= {min_val}")
    if max_val is not None and n > max_val:
        return ValidationResult(valid=False, error=f"Must be <= {max_val}")

    return ValidationResult(valid=True)


def _validate_bool(value: str) -> ValidationResult:
    if value.lower() in ("true", "false"):
        return ValidationResult(valid=True)
    return ValidationResult(valid=False, error="Must be 'true' or 'false'")


def _validate_list(value: str, max_items: int) -> ValidationResult:
    if not value.strip():
        return ValidationResult(valid=True)  # Empty list is valid
    items = [item.strip() for item in value.split(",")]
    if len(items) > max_items:
        return ValidationResult(
            valid=False,
            error=f"Maximum {max_items} items allowed (got {len(items)})",
        )
    return ValidationResult(valid=True)


def _validate_str(value: str) -> ValidationResult:
    # String type: any non-empty string is valid
    if not value:
        return ValidationResult(valid=False, error="Must not be empty")
    return ValidationResult(valid=True)
