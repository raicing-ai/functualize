"""Compatibility re-export — the validator moved to ``_cli/data/settings_schema``.

It moved because ``_cli/data/func_settings`` needs the schemas to build its
catalog, and importing anything under ``_cli/tui`` from ``data/`` triggers
the tui package ``__init__`` → settings panel → catalog import cycle.
"""

from __future__ import annotations

from functualize._cli.data.settings_schema import (
    SETTING_SCHEMAS,
    SettingSchema,
    ValidationResult,
    validate_against,
    validate_setting,
)

__all__ = [
    "SETTING_SCHEMAS",
    "SettingSchema",
    "ValidationResult",
    "validate_against",
    "validate_setting",
]
