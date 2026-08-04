"""Unit tests for the INI → TOML migration utility."""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._config.errors import MigrationError
from functualize._config.migration import migrate_ini_to_toml
from functualize._config.providers.ini import IniFormatProvider
from functualize._config.providers.toml import TomlFormatProvider


class TestMigrateIniToToml:
    """Tests for migrate_ini_to_toml function."""

    def test_converts_basic_ini_to_toml(self, tmp_path: Path) -> None:
        """Converts sections and key-value pairs from INI to TOML."""
        ini_file = tmp_path / "config.ini"
        ini_file.write_text(
            "[database]\nhost = localhost\nport = 5432\n\n[logging]\nlevel = DEBUG\n",
            encoding="utf-8",
        )
        toml_file = tmp_path / "config.toml"

        migrate_ini_to_toml(str(ini_file), str(toml_file))

        assert toml_file.exists()
        toml_provider = TomlFormatProvider()
        result = toml_provider.parse(str(toml_file))

        assert result == {
            "database": {"host": "localhost", "port": "5432"},
            "logging": {"level": "DEBUG"},
        }

    def test_loading_toml_produces_equivalent_values(self, tmp_path: Path) -> None:
        """Loading TOML output produces values equivalent to loading original INI."""
        ini_file = tmp_path / "config.ini"
        ini_file.write_text(
            "[server]\nhost = 0.0.0.0\nport = 8080\n\n"
            "[auth]\nenabled = true\ntoken = abc123\n",
            encoding="utf-8",
        )
        toml_file = tmp_path / "config.toml"

        migrate_ini_to_toml(str(ini_file), str(toml_file))

        ini_provider = IniFormatProvider()
        ini_data = ini_provider.parse(str(ini_file))

        toml_provider = TomlFormatProvider()
        toml_data = toml_provider.parse(str(toml_file))

        assert toml_data == ini_data

    def test_raises_migration_error_for_interpolation(self, tmp_path: Path) -> None:
        """Raises MigrationError when interpolation references are found."""
        ini_file = tmp_path / "interp.ini"
        ini_file.write_text(
            "[paths]\nbase = /usr/local\nbin = %(base)s/bin\n",
            encoding="utf-8",
        )
        toml_file = tmp_path / "interp.toml"

        with pytest.raises(MigrationError) as exc_info:
            migrate_ini_to_toml(str(ini_file), str(toml_file))

        err = exc_info.value
        assert err.file == str(ini_file)
        assert err.line == 3
        assert err.construct == "interpolation reference"

    def test_does_not_create_toml_on_interpolation_error(self, tmp_path: Path) -> None:
        """TOML file is not created when MigrationError is raised."""
        ini_file = tmp_path / "interp.ini"
        ini_file.write_text(
            "[section]\nval = %(other)s/path\n",
            encoding="utf-8",
        )
        toml_file = tmp_path / "output.toml"

        with pytest.raises(MigrationError):
            migrate_ini_to_toml(str(ini_file), str(toml_file))

        assert not toml_file.exists()

    def test_handles_empty_ini_file(self, tmp_path: Path) -> None:
        """Handles an INI file with no sections or keys."""
        ini_file = tmp_path / "empty.ini"
        ini_file.write_text("", encoding="utf-8")
        toml_file = tmp_path / "empty.toml"

        migrate_ini_to_toml(str(ini_file), str(toml_file))

        assert toml_file.exists()
        toml_provider = TomlFormatProvider()
        result = toml_provider.parse(str(toml_file))
        assert result == {}

    def test_handles_empty_sections(self, tmp_path: Path) -> None:
        """Handles INI file with empty sections."""
        ini_file = tmp_path / "config.ini"
        ini_file.write_text("[empty]\n\n[also_empty]\n", encoding="utf-8")
        toml_file = tmp_path / "config.toml"

        migrate_ini_to_toml(str(ini_file), str(toml_file))

        toml_provider = TomlFormatProvider()
        result = toml_provider.parse(str(toml_file))
        assert result == {"empty": {}, "also_empty": {}}

    def test_preserves_special_characters_in_values(self, tmp_path: Path) -> None:
        """Preserves special characters in values through migration."""
        ini_file = tmp_path / "special.ini"
        ini_file.write_text(
            '[section]\nurl = https://example.com/path?q=1&b=2\nmsg = hello "world"\n',
            encoding="utf-8",
        )
        toml_file = tmp_path / "special.toml"

        migrate_ini_to_toml(str(ini_file), str(toml_file))

        ini_provider = IniFormatProvider()
        ini_data = ini_provider.parse(str(ini_file))

        toml_provider = TomlFormatProvider()
        toml_data = toml_provider.parse(str(toml_file))

        assert toml_data == ini_data

    def test_detects_interpolation_in_first_value(self, tmp_path: Path) -> None:
        """Detects interpolation reference in the first key-value pair."""
        ini_file = tmp_path / "first.ini"
        ini_file.write_text(
            "[section]\npath = %(home)s/.config\n",
            encoding="utf-8",
        )
        toml_file = tmp_path / "first.toml"

        with pytest.raises(MigrationError) as exc_info:
            migrate_ini_to_toml(str(ini_file), str(toml_file))

        assert exc_info.value.line == 2

    def test_does_not_flag_percent_in_non_interpolation_context(
        self, tmp_path: Path
    ) -> None:
        """Percent signs that are not interpolation references are allowed."""
        ini_file = tmp_path / "percent.ini"
        ini_file.write_text(
            "[section]\nprogress = 95%\nformat = %Y-%m-%d\n",
            encoding="utf-8",
        )
        toml_file = tmp_path / "percent.toml"

        # Should not raise — these are not %(key)s patterns
        migrate_ini_to_toml(str(ini_file), str(toml_file))

        toml_provider = TomlFormatProvider()
        result = toml_provider.parse(str(toml_file))
        assert result["section"]["progress"] == "95%"
        assert result["section"]["format"] == "%Y-%m-%d"

    def test_multiple_sections_all_values_as_strings(self, tmp_path: Path) -> None:
        """All INI values are output as TOML strings."""
        ini_file = tmp_path / "types.ini"
        ini_file.write_text(
            "[section]\ncount = 42\nenabled = true\nratio = 3.14\n",
            encoding="utf-8",
        )
        toml_file = tmp_path / "types.toml"

        migrate_ini_to_toml(str(ini_file), str(toml_file))

        toml_provider = TomlFormatProvider()
        result = toml_provider.parse(str(toml_file))

        # All values should be strings since INI has no type info
        assert result["section"]["count"] == "42"
        assert result["section"]["enabled"] == "true"
        assert result["section"]["ratio"] == "3.14"

    def test_raises_on_nonexistent_ini_file(self, tmp_path: Path) -> None:
        """Raises OSError when INI file does not exist."""
        ini_file = str(tmp_path / "nonexistent.ini")
        toml_file = str(tmp_path / "output.toml")

        with pytest.raises(OSError):
            migrate_ini_to_toml(ini_file, toml_file)

    def test_interpolation_in_comment_is_ignored(self, tmp_path: Path) -> None:
        """Interpolation-like patterns in comments are not flagged."""
        ini_file = tmp_path / "comments.ini"
        ini_file.write_text(
            "# This has %(key)s in a comment\n[section]\nvalue = plain\n",
            encoding="utf-8",
        )
        toml_file = tmp_path / "comments.toml"

        # Should not raise — comments are skipped
        migrate_ini_to_toml(str(ini_file), str(toml_file))

        toml_provider = TomlFormatProvider()
        result = toml_provider.parse(str(toml_file))
        assert result["section"]["value"] == "plain"

    def test_interpolation_in_section_header_is_ignored(self, tmp_path: Path) -> None:
        """Section headers are not scanned for interpolation."""
        ini_file = tmp_path / "header.ini"
        ini_file.write_text(
            "[section]\nkey = value\n",
            encoding="utf-8",
        )
        toml_file = tmp_path / "header.toml"

        migrate_ini_to_toml(str(ini_file), str(toml_file))
        assert toml_file.exists()
