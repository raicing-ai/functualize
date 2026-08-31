"""Property-based tests for settings value validation (Property 17).

# Feature: tui-architecture-v2, Property 17: Settings value validation

Tests validate_setting from functualize._cli.tui.settings_validator:
- Enum settings: accept only defined choices, reject everything else
- Int settings: accept integers in range, reject out-of-range and non-integers
- Bool settings: accept "true"/"false" (case-insensitive), reject others
- List settings: accept comma-separated lists with ≤ max_items, reject > max_items
- Str settings: accept non-empty strings, reject empty
"""

from __future__ import annotations

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.data.func_settings import FUNC_SETTINGS
from functualize._cli.tui.settings_validator import (
    SETTING_SCHEMAS,
    SettingSchema,
    validate_against,
    validate_setting,
)

# =============================================================================
# Strategies
# =============================================================================

# --- Enum strategies ---

_ENUM_SETTINGS = {
    name: schema for name, schema in SETTING_SCHEMAS.items() if schema.type == "enum"
}


def _valid_enum_choice(setting_name: str) -> st.SearchStrategy[str]:
    """Strategy for a valid enum choice for a given setting."""
    choices = SETTING_SCHEMAS[setting_name].choices or []
    return st.sampled_from(choices)


def _invalid_enum_choice(setting_name: str) -> st.SearchStrategy[str]:
    """Strategy for a string that is NOT a valid enum choice."""
    choices = set(SETTING_SCHEMAS[setting_name].choices or [])
    return st.text(
        alphabet=string.ascii_lowercase + string.digits + "_-",
        min_size=1,
        max_size=20,
    ).filter(lambda s: s not in choices)


# --- Int strategies ---

_INT_SETTINGS = {
    name: schema for name, schema in SETTING_SCHEMAS.items() if schema.type == "int"
}


def _valid_int_value(setting_name: str) -> st.SearchStrategy[str]:
    """Strategy for a valid integer string within the setting's range."""
    schema = SETTING_SCHEMAS[setting_name]
    min_val = schema.min_value if schema.min_value is not None else 0
    max_val = schema.max_value if schema.max_value is not None else 10000
    return st.integers(min_value=min_val, max_value=max_val).map(str)


def _out_of_range_int(setting_name: str) -> st.SearchStrategy[str]:
    """Strategy for an integer string outside the setting's range."""
    schema = SETTING_SCHEMAS[setting_name]
    min_val = schema.min_value if schema.min_value is not None else 0
    max_val = schema.max_value if schema.max_value is not None else 10000
    below = st.integers(max_value=min_val - 1).map(str)
    above = st.integers(min_value=max_val + 1).map(str)
    return st.one_of(below, above)


_NON_INTEGER_STRINGS = st.text(
    alphabet=string.ascii_letters + "!@#$%^&*().,",
    min_size=1,
    max_size=20,
).filter(lambda s: not s.lstrip("-").isdigit())

# --- Bool strategies ---

_BOOL_SETTINGS = {
    name: schema for name, schema in SETTING_SCHEMAS.items() if schema.type == "bool"
}

_VALID_BOOL_VALUES = st.sampled_from(
    ["true", "false", "True", "False", "TRUE", "FALSE"]
)

_INVALID_BOOL_VALUES = st.text(
    alphabet=string.ascii_letters + string.digits,
    min_size=1,
    max_size=20,
).filter(lambda s: s.lower() not in ("true", "false"))

# --- List strategies ---

# List settings are drawn from the func-settings catalog, not from
# ``SETTING_SCHEMAS``: `tui.sensitive_keywords` was the only list-typed *TUI*
# setting and was removed (2026-08-27), leaving that dict with no list entries
# at all. The list branch of the validator is still live — the catalog reaches
# it through the schema-first ``validate_against``, which is what these tests
# now call.
_LIST_SETTINGS = {
    setting.name: setting.schema
    for setting in FUNC_SETTINGS
    if setting.schema.type == "list"
}

# Items for comma-separated lists (no commas within items)
_LIST_ITEM = st.text(
    alphabet=string.ascii_lowercase + string.digits + "_- ",
    min_size=1,
    max_size=20,
)


def _valid_list_value(schema: SettingSchema) -> st.SearchStrategy[str]:
    """Strategy for a comma-separated list within the max_items limit."""
    max_items = schema.max_items or 50
    return st.lists(
        _LIST_ITEM,
        min_size=1,
        max_size=max_items,
    ).map(lambda items: ",".join(items))


def _oversized_list_value(schema: SettingSchema) -> st.SearchStrategy[str]:
    """Strategy for a comma-separated list exceeding max_items."""
    max_items = schema.max_items or 50
    return st.lists(
        _LIST_ITEM,
        min_size=max_items + 1,
        max_size=max_items + 10,
    ).map(lambda items: ",".join(items))


# --- Str strategies ---

_STR_SETTINGS = {
    name: schema for name, schema in SETTING_SCHEMAS.items() if schema.type == "str"
}

_VALID_STR = st.text(min_size=1, max_size=50)


# =============================================================================
# Property 17: Settings value validation
# =============================================================================


@pytest.mark.slow
class TestSettingsValueValidation:
    """Property 17: Settings value validation.

    For any setting with a defined type constraint (enum choices, int range 1-1000,
    bool, comma-separated list max 50 items) and any input value, the Settings panel
    should accept the value if and only if it conforms to the constraint, rejecting
    invalid enum choices, non-integers, out-of-range values, and lists exceeding 50
    items.

    **Validates: Requirements 12.7**
    """

    # --- Enum tests ---

    @given(data=st.data())
    def test_valid_enum_choices_are_accepted(self, data: st.DataObject) -> None:
        """Valid enum choices are accepted for all enum settings.

        **Validates: Requirements 12.7**
        """
        setting_name = data.draw(st.sampled_from(list(_ENUM_SETTINGS.keys())))
        value = data.draw(_valid_enum_choice(setting_name))
        result = validate_setting(setting_name, value)
        assert result.valid is True

    @given(data=st.data())
    def test_invalid_enum_choices_are_rejected(self, data: st.DataObject) -> None:
        """Random strings not in the enum choices are rejected.

        **Validates: Requirements 12.7**
        """
        setting_name = data.draw(st.sampled_from(list(_ENUM_SETTINGS.keys())))
        value = data.draw(_invalid_enum_choice(setting_name))
        result = validate_setting(setting_name, value)
        assert result.valid is False
        assert result.error is not None

    # --- Int tests ---

    @given(data=st.data())
    def test_in_range_integers_are_accepted(self, data: st.DataObject) -> None:
        """Integer values within the defined range are accepted.

        **Validates: Requirements 12.7**
        """
        setting_name = data.draw(st.sampled_from(list(_INT_SETTINGS.keys())))
        value = data.draw(_valid_int_value(setting_name))
        result = validate_setting(setting_name, value)
        assert result.valid is True

    @given(data=st.data())
    def test_out_of_range_integers_are_rejected(self, data: st.DataObject) -> None:
        """Integer values outside the defined range are rejected.

        **Validates: Requirements 12.7**
        """
        setting_name = data.draw(st.sampled_from(list(_INT_SETTINGS.keys())))
        value = data.draw(_out_of_range_int(setting_name))
        result = validate_setting(setting_name, value)
        assert result.valid is False
        assert result.error is not None

    @given(data=st.data())
    def test_non_integer_strings_are_rejected_for_int_settings(
        self, data: st.DataObject
    ) -> None:
        """Non-integer strings are rejected for int-type settings.

        **Validates: Requirements 12.7**
        """
        setting_name = data.draw(st.sampled_from(list(_INT_SETTINGS.keys())))
        value = data.draw(_NON_INTEGER_STRINGS)
        result = validate_setting(setting_name, value)
        assert result.valid is False
        assert result.error is not None

    # --- Bool tests ---

    @given(data=st.data())
    def test_valid_bool_values_are_accepted(self, data: st.DataObject) -> None:
        """'true' and 'false' (case-insensitive) are accepted for bool settings.

        **Validates: Requirements 12.7**
        """
        setting_name = data.draw(st.sampled_from(list(_BOOL_SETTINGS.keys())))
        value = data.draw(_VALID_BOOL_VALUES)
        result = validate_setting(setting_name, value)
        assert result.valid is True

    @given(data=st.data())
    def test_invalid_bool_values_are_rejected(self, data: st.DataObject) -> None:
        """Strings other than 'true'/'false' are rejected for bool settings.

        **Validates: Requirements 12.7**
        """
        setting_name = data.draw(st.sampled_from(list(_BOOL_SETTINGS.keys())))
        value = data.draw(_INVALID_BOOL_VALUES)
        result = validate_setting(setting_name, value)
        assert result.valid is False
        assert result.error is not None

    # --- List tests ---

    @given(data=st.data())
    def test_lists_within_max_items_are_accepted(self, data: st.DataObject) -> None:
        """Comma-separated lists with ≤ max_items items are accepted.

        **Validates: Requirements 12.7**
        """
        schema = data.draw(st.sampled_from(list(_LIST_SETTINGS.values())))
        value = data.draw(_valid_list_value(schema))
        result = validate_against(schema, value)
        assert result.valid is True

    @given(data=st.data())
    def test_lists_exceeding_max_items_are_rejected(self, data: st.DataObject) -> None:
        """Comma-separated lists with > max_items items are rejected.

        **Validates: Requirements 12.7**
        """
        schema = data.draw(st.sampled_from(list(_LIST_SETTINGS.values())))
        value = data.draw(_oversized_list_value(schema))
        result = validate_against(schema, value)
        assert result.valid is False
        assert result.error is not None

    # --- Str tests ---

    @given(data=st.data())
    def test_non_empty_strings_are_accepted_for_str_settings(
        self, data: st.DataObject
    ) -> None:
        """Non-empty strings are accepted for str-type settings.

        **Validates: Requirements 12.7**
        """
        setting_name = data.draw(st.sampled_from(list(_STR_SETTINGS.keys())))
        value = data.draw(_VALID_STR)
        result = validate_setting(setting_name, value)
        assert result.valid is True

    def test_empty_string_is_rejected_for_str_settings(self) -> None:
        """Empty string is rejected for str-type settings.

        **Validates: Requirements 12.7**
        """
        for setting_name in _STR_SETTINGS:
            result = validate_setting(setting_name, "")
            assert result.valid is False
            assert result.error is not None
