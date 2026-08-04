"""Property-based tests for INI to TOML migration equivalence.

Tests Property 21 from the design document:
For any valid INI configuration dictionary (sections with string key-value pairs),
migrating the INI file to TOML format and loading the generated TOML file SHALL
produce configuration values equivalent to loading the original INI file for all
sections and keys.

**Validates: Requirements 12.4**
"""

from __future__ import annotations

import os
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._config.migration import migrate_ini_to_toml
from functualize._config.providers.ini import IniFormatProvider
from functualize._config.providers.toml import TomlFormatProvider

# --- Strategies for valid INI configuration data ---

# INI section names: simple alphanumeric with underscores, no whitespace or brackets
ini_section_names = st.from_regex(r"[a-z][a-z0-9_]{0,9}", fullmatch=True)

# INI keys: simple lowercase alphanumeric with underscores (configparser lowercases)
ini_keys = st.from_regex(r"[a-z][a-z0-9_]{0,9}", fullmatch=True)

# INI string values: printable characters that survive configparser round-trip.
# Excludes:
#   - Newlines (multiline values change whitespace)
#   - Control characters
#   - INI-special characters that could be misinterpreted: []=;#
#   - Interpolation syntax %(...)s (would trigger MigrationError)
#   - Leading/trailing whitespace (configparser strips it)
_INI_SAFE_ALPHABET = st.characters(
    whitelist_categories=("L", "N", "P", "Zs"),
    blacklist_characters="\x00\n\r\t[]=;#%",
)

ini_string_values = st.text(
    alphabet=_INI_SAFE_ALPHABET,
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() == s and len(s.strip()) > 0)


def ini_config_dicts() -> st.SearchStrategy[dict[str, dict[str, str]]]:
    """Strategy for valid INI configuration dictionaries.

    Generates dicts of the form:
    { "section1": {"key1": "value1", ...}, "section2": {...}, ... }

    All values are strings (INI has no type information).
    Section names and keys are lowercase (configparser convention).
    Values exclude interpolation patterns to avoid MigrationError.
    """
    return st.dictionaries(
        keys=ini_section_names,
        values=st.dictionaries(
            keys=ini_keys,
            values=ini_string_values,
            min_size=1,
            max_size=5,
        ),
        min_size=1,
        max_size=5,
    )


# --- Helpers ---


def _write_ini_file(data: dict[str, dict[str, str]], path: str) -> None:
    """Write a valid INI file from a section->keys dict using IniFormatProvider."""
    provider = IniFormatProvider()
    content = provider.serialize(data)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# --- Property 21: INI to TOML migration equivalence ---


class TestProperty21IniToTomlMigrationEquivalence:
    """For any valid INI configuration file (sections with string key-value pairs),
    migrating to TOML format and loading the generated TOML file SHALL produce
    configuration values equivalent to loading the original INI file for all
    sections and keys.

    **Validates: Requirements 12.4**
    """

    @given(data=ini_config_dicts())
    @settings(max_examples=200)
    def test_migrated_toml_equivalent_to_original_ini(
        self, data: dict[str, dict[str, str]]
    ) -> None:
        """Loading the migrated TOML file produces the same configuration
        values as loading the original INI file."""
        ini_fd, ini_path = tempfile.mkstemp(suffix=".ini")
        toml_fd, toml_path = tempfile.mkstemp(suffix=".toml")
        os.close(toml_fd)

        try:
            # Write the INI file using the provider's serialization
            with os.fdopen(ini_fd, "w", encoding="utf-8") as f:
                provider = IniFormatProvider()
                f.write(provider.serialize(data))

            # Migrate INI to TOML
            migrate_ini_to_toml(ini_path, toml_path)

            # Load original INI
            ini_provider = IniFormatProvider()
            ini_data = ini_provider.parse(ini_path)

            # Load migrated TOML
            toml_provider = TomlFormatProvider()
            toml_data = toml_provider.parse(toml_path)

            # The TOML output must be equivalent to the INI input
            assert toml_data == ini_data, (
                f"Migration equivalence violated.\n"
                f"Input data: {data!r}\n"
                f"INI parsed: {ini_data!r}\n"
                f"TOML parsed: {toml_data!r}"
            )
        finally:
            os.unlink(ini_path)
            if os.path.exists(toml_path):
                os.unlink(toml_path)

    @given(data=ini_config_dicts())
    @settings(max_examples=100)
    def test_migrated_toml_preserves_all_sections(
        self, data: dict[str, dict[str, str]]
    ) -> None:
        """All sections from the original INI are present in the migrated TOML."""
        ini_fd, ini_path = tempfile.mkstemp(suffix=".ini")
        toml_fd, toml_path = tempfile.mkstemp(suffix=".toml")
        os.close(toml_fd)

        try:
            with os.fdopen(ini_fd, "w", encoding="utf-8") as f:
                provider = IniFormatProvider()
                f.write(provider.serialize(data))

            migrate_ini_to_toml(ini_path, toml_path)

            ini_provider = IniFormatProvider()
            ini_data = ini_provider.parse(ini_path)

            toml_provider = TomlFormatProvider()
            toml_data = toml_provider.parse(toml_path)

            # All sections in INI must appear in TOML
            assert set(toml_data.keys()) == set(ini_data.keys()), (
                f"Section mismatch.\n"
                f"INI sections: {set(ini_data.keys())}\n"
                f"TOML sections: {set(toml_data.keys())}"
            )
        finally:
            os.unlink(ini_path)
            if os.path.exists(toml_path):
                os.unlink(toml_path)

    @given(data=ini_config_dicts())
    @settings(max_examples=100)
    def test_migrated_toml_preserves_all_keys_per_section(
        self, data: dict[str, dict[str, str]]
    ) -> None:
        """All keys within each section are preserved through migration."""
        ini_fd, ini_path = tempfile.mkstemp(suffix=".ini")
        toml_fd, toml_path = tempfile.mkstemp(suffix=".toml")
        os.close(toml_fd)

        try:
            with os.fdopen(ini_fd, "w", encoding="utf-8") as f:
                provider = IniFormatProvider()
                f.write(provider.serialize(data))

            migrate_ini_to_toml(ini_path, toml_path)

            ini_provider = IniFormatProvider()
            ini_data = ini_provider.parse(ini_path)

            toml_provider = TomlFormatProvider()
            toml_data = toml_provider.parse(toml_path)

            for section in ini_data:
                assert section in toml_data, f"Section '{section}' missing from TOML"
                ini_keys_set = set(ini_data[section].keys())
                toml_keys_set = set(toml_data[section].keys())
                assert toml_keys_set == ini_keys_set, (
                    f"Key mismatch in section '{section}'.\n"
                    f"INI keys: {ini_keys_set}\n"
                    f"TOML keys: {toml_keys_set}"
                )
        finally:
            os.unlink(ini_path)
            if os.path.exists(toml_path):
                os.unlink(toml_path)
