"""Property-based tests for Format Provider round-trip behavior.

Tests Property 1 from the design document:
For any valid configuration dictionary (containing primitives, lists, and nested
dicts), serializing it with a Format_Provider and parsing the resulting string
back with the same provider SHALL produce a dictionary that is deeply equal to
the original.

**Validates: Requirements 2.9, 10.4**
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.providers.ini import IniFormatProvider
from functualize._config.providers.toml import TomlFormatProvider

# --- Strategies for TOML-compatible config dicts ---

# Valid TOML bare keys: A-Za-z0-9, -, _
toml_bare_keys = st.from_regex(r"[A-Za-z][A-Za-z0-9_-]{0,9}", fullmatch=True)

# TOML-safe strings: printable characters plus the whitespace chars the
# serializer can properly escape (\n, \r, \t, \b, \f). Excludes control
# characters that TOML disallows in basic strings without \uXXXX escapes.
_TOML_SAFE_CHARS = st.characters(
    whitelist_categories=("L", "N", "P", "Zs"),
    whitelist_characters="\n\r\t",
    blacklist_characters="\x00",
)

toml_strings = st.text(alphabet=_TOML_SAFE_CHARS, min_size=0, max_size=20)

# TOML scalar values (no NaN/Inf for floats)
toml_scalars = st.one_of(
    toml_strings,
    st.integers(min_value=-(2**31), max_value=2**31),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e10, max_value=1e10),
    st.booleans(),
)

# Homogeneous lists of TOML scalars (same type within the list for TOML compliance)
toml_scalar_lists = st.one_of(
    st.lists(toml_strings.filter(lambda s: len(s) <= 10), min_size=0, max_size=5),
    st.lists(st.integers(min_value=-1000, max_value=1000), min_size=0, max_size=5),
    st.lists(
        st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
        min_size=0,
        max_size=5,
    ),
    st.lists(st.booleans(), min_size=0, max_size=5),
)

# TOML leaf values: scalars or homogeneous scalar lists
toml_leaf_values = st.one_of(toml_scalars, toml_scalar_lists)


def toml_config_dicts(max_depth: int = 2) -> st.SearchStrategy[dict[str, Any]]:
    """Strategy for generating TOML-compatible configuration dictionaries.

    Generates nested dicts where:
    - Keys are valid TOML bare keys
    - Leaf values are TOML scalars (str, int, float, bool) or homogeneous lists
    - Nesting goes up to max_depth levels
    """
    if max_depth <= 0:
        return st.dictionaries(
            keys=toml_bare_keys,
            values=toml_leaf_values,
            min_size=0,
            max_size=4,
        )
    return st.dictionaries(
        keys=toml_bare_keys,
        values=st.one_of(
            toml_leaf_values,
            st.dictionaries(
                keys=toml_bare_keys,
                values=st.one_of(
                    toml_leaf_values,
                    toml_config_dicts(max_depth - 1),
                ),
                min_size=1,
                max_size=3,
            ),
        ),
        min_size=0,
        max_size=4,
    )


# --- Strategies for INI-compatible config dicts ---

# INI keys: simple alphanumeric with underscores
ini_keys = st.from_regex(r"[a-z][a-z0-9_]{0,9}", fullmatch=True)

# INI values are always strings (no type information in INI format).
# Exclude newlines (multi-line handling changes whitespace), control chars,
# INI-special chars, and filter out whitespace-only strings (configparser strips them).
ini_string_values = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Zs"),
        blacklist_characters="\x00\n\r\t[]=;#",
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() == s and len(s.strip()) > 0)

# INI section names
ini_section_names = st.from_regex(r"[a-z][a-z0-9_]{0,9}", fullmatch=True)


def ini_config_dicts() -> st.SearchStrategy[dict[str, Any]]:
    """Strategy for INI-compatible config dicts.

    INI format is flat sections with string values only:
    { "section1": {"key1": "val1", ...}, "section2": {...} }
    """
    return st.dictionaries(
        keys=ini_section_names,
        values=st.dictionaries(
            keys=ini_keys,
            values=ini_string_values,
            min_size=1,
            max_size=4,
        ),
        min_size=1,
        max_size=4,
    )


# --- Helpers ---


def _write_to_tempfile(content: str, suffix: str) -> str:
    """Write content to a temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# --- Property 1: Format Provider round-trip ---


class TestProperty1FormatProviderRoundTrip:
    """For any valid configuration dictionary, serializing it with a Format_Provider
    and parsing the resulting string back with the same provider SHALL produce a
    dictionary that is deeply equal to the original.

    **Validates: Requirements 2.9, 10.4**
    """

    @given(data=toml_config_dicts(max_depth=2))
    def test_toml_serialize_parse_roundtrip(self, data: dict[str, Any]) -> None:
        """For any valid TOML config dict, serialize → parse produces a dict
        deeply equal to the original."""
        provider = TomlFormatProvider()

        serialized = provider.serialize(data)
        path = _write_to_tempfile(serialized, suffix=".toml")
        try:
            parsed = provider.parse(path)
            assert parsed == data, (
                f"Round-trip failed.\n"
                f"Original: {data!r}\n"
                f"Serialized:\n{serialized}\n"
                f"Parsed back: {parsed!r}"
            )
        finally:
            os.unlink(path)

    @given(data=toml_config_dicts(max_depth=0))
    def test_toml_flat_dict_roundtrip(self, data: dict[str, Any]) -> None:
        """For any flat (non-nested) TOML config dict, round-trip is exact."""
        provider = TomlFormatProvider()

        serialized = provider.serialize(data)
        path = _write_to_tempfile(serialized, suffix=".toml")
        try:
            parsed = provider.parse(path)
            assert parsed == data
        finally:
            os.unlink(path)

    @given(
        data=st.dictionaries(
            keys=toml_bare_keys,
            values=st.dictionaries(
                keys=toml_bare_keys,
                values=toml_leaf_values,
                min_size=1,
                max_size=3,
            ),
            min_size=1,
            max_size=3,
        )
    )
    def test_toml_nested_sections_roundtrip(self, data: dict[str, Any]) -> None:
        """For any dict with one level of nesting (table sections), round-trip is exact."""
        provider = TomlFormatProvider()

        serialized = provider.serialize(data)
        path = _write_to_tempfile(serialized, suffix=".toml")
        try:
            parsed = provider.parse(path)
            assert parsed == data
        finally:
            os.unlink(path)

    @given(data=ini_config_dicts())
    def test_ini_serialize_parse_roundtrip(self, data: dict[str, Any]) -> None:
        """For any valid INI-compatible dict (flat sections with string values),
        serialize → parse produces equivalent data."""
        provider = IniFormatProvider()

        serialized = provider.serialize(data)
        path = _write_to_tempfile(serialized, suffix=".ini")
        try:
            parsed = provider.parse(path)
            # INI configparser lowercases keys, so we compare lowercase
            expected = {
                section: {k.lower(): v for k, v in values.items()}
                for section, values in data.items()
            }
            assert parsed == expected, (
                f"INI round-trip failed.\n"
                f"Original: {data!r}\n"
                f"Serialized:\n{serialized}\n"
                f"Parsed back: {parsed!r}\n"
                f"Expected (lowered keys): {expected!r}"
            )
        finally:
            os.unlink(path)

    @given(data=toml_config_dicts(max_depth=2))
    def test_toml_roundtrip_idempotent(self, data: dict[str, Any]) -> None:
        """Applying the round-trip twice yields the same result as once.
        serialize → parse → serialize → parse == serialize → parse."""
        provider = TomlFormatProvider()

        # First round-trip
        serialized1 = provider.serialize(data)
        path1 = _write_to_tempfile(serialized1, suffix=".toml")
        try:
            parsed1 = provider.parse(path1)
        finally:
            os.unlink(path1)

        # Second round-trip
        serialized2 = provider.serialize(parsed1)
        path2 = _write_to_tempfile(serialized2, suffix=".toml")
        try:
            parsed2 = provider.parse(path2)
        finally:
            os.unlink(path2)

        assert parsed1 == parsed2, (
            f"Round-trip not idempotent.\n"
            f"First parse: {parsed1!r}\n"
            f"Second parse: {parsed2!r}"
        )
