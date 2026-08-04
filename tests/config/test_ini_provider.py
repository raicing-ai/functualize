"""Unit tests for the IniFormatProvider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from functualize._config.errors import FormatParseError
from functualize._config.providers.ini import IniFormatProvider


class TestExtensions:
    """Tests for IniFormatProvider.extensions()."""

    def test_returns_ini_and_cfg(self) -> None:
        provider = IniFormatProvider()
        assert provider.extensions() == [".ini", ".cfg"]


class TestParse:
    """Tests for IniFormatProvider.parse()."""

    def test_parse_basic_ini_file(self, tmp_path: Path) -> None:
        """Parses a basic INI file into nested dict structure."""
        ini_file = tmp_path / "config.ini"
        ini_file.write_text(
            "[database]\nhost = localhost\nport = 5432\n\n[logging]\nlevel = DEBUG\n",
            encoding="utf-8",
        )

        provider = IniFormatProvider()
        result = provider.parse(str(ini_file))

        assert result == {
            "database": {"host": "localhost", "port": "5432"},
            "logging": {"level": "DEBUG"},
        }

    def test_parse_multiline_values(self, tmp_path: Path) -> None:
        """Supports multi-line values as per configparser behavior."""
        ini_file = tmp_path / "config.ini"
        ini_file.write_text(
            "[section]\nkey = line1\n    line2\n    line3\n",
            encoding="utf-8",
        )

        provider = IniFormatProvider()
        result = provider.parse(str(ini_file))

        assert result["section"]["key"] == "line1\nline2\nline3"

    def test_parse_no_interpolation(self, tmp_path: Path) -> None:
        """Interpolation syntax is NOT expanded — values are literal strings."""
        ini_file = tmp_path / "config.ini"
        ini_file.write_text(
            "[section]\nbase = /usr/local\npath = %(base)s/bin\n",
            encoding="utf-8",
        )

        provider = IniFormatProvider()
        result = provider.parse(str(ini_file))

        # Should NOT expand %(base)s — interpolation is disabled
        assert result["section"]["path"] == "%(base)s/bin"

    def test_parse_raises_on_malformed_file(self, tmp_path: Path) -> None:
        """Raises FormatParseError for malformed INI content."""
        ini_file = tmp_path / "bad.ini"
        ini_file.write_text("this is not valid ini\n[broken\n", encoding="utf-8")

        provider = IniFormatProvider()
        with pytest.raises(FormatParseError) as exc_info:
            provider.parse(str(ini_file))

        assert exc_info.value.path == str(ini_file)

    def test_parse_raises_on_nonexistent_file(self, tmp_path: Path) -> None:
        """Raises FormatParseError when file does not exist."""
        missing = str(tmp_path / "nonexistent.ini")

        provider = IniFormatProvider()
        with pytest.raises(FormatParseError) as exc_info:
            provider.parse(missing)

        assert exc_info.value.path == missing
        assert "not found or not readable" in exc_info.value.reason.lower()

    def test_parse_empty_sections(self, tmp_path: Path) -> None:
        """Parses INI with empty sections."""
        ini_file = tmp_path / "empty.ini"
        ini_file.write_text("[empty]\n\n[also_empty]\n", encoding="utf-8")

        provider = IniFormatProvider()
        result = provider.parse(str(ini_file))

        assert result == {"empty": {}, "also_empty": {}}

    def test_parse_all_values_are_strings(self, tmp_path: Path) -> None:
        """All values are returned as strings — no type coercion."""
        ini_file = tmp_path / "types.ini"
        ini_file.write_text(
            "[section]\nnum = 42\nbool = true\nfloat = 3.14\n",
            encoding="utf-8",
        )

        provider = IniFormatProvider()
        result = provider.parse(str(ini_file))

        assert result["section"]["num"] == "42"
        assert result["section"]["bool"] == "true"
        assert result["section"]["float"] == "3.14"


class TestSerialize:
    """Tests for IniFormatProvider.serialize()."""

    def test_serialize_basic_dict(self) -> None:
        """Serializes a nested dict into valid INI format."""
        data: dict[str, Any] = {
            "database": {"host": "localhost", "port": "5432"},
            "logging": {"level": "DEBUG"},
        }

        provider = IniFormatProvider()
        output = provider.serialize(data)

        # Verify it's valid INI by parsing it back
        assert "[database]" in output
        assert "host = localhost" in output
        assert "[logging]" in output
        assert "level = debug" in output.lower()

    def test_serialize_roundtrip(self, tmp_path: Path) -> None:
        """Serialize then parse should produce equivalent data."""
        data: dict[str, Any] = {
            "server": {"host": "0.0.0.0", "port": "8080"},
            "auth": {"enabled": "true", "token": "abc123"},
        }

        provider = IniFormatProvider()
        serialized = provider.serialize(data)

        # Write to file and parse back
        ini_file = tmp_path / "roundtrip.ini"
        ini_file.write_text(serialized, encoding="utf-8")

        parsed = provider.parse(str(ini_file))
        assert parsed == data

    def test_serialize_empty_dict(self) -> None:
        """Serializing an empty dict produces empty output."""
        provider = IniFormatProvider()
        output = provider.serialize({})
        # Should be empty or just whitespace
        assert output.strip() == ""

    def test_serialize_converts_values_to_strings(self) -> None:
        """Non-string values are converted to strings during serialization."""
        data: dict[str, Any] = {
            "section": {"count": 42, "enabled": True, "ratio": 3.14},
        }

        provider = IniFormatProvider()
        output = provider.serialize(data)

        assert "42" in output
        assert "True" in output
        assert "3.14" in output


class TestProtocolCompliance:
    """Tests that IniFormatProvider satisfies FormatProvider protocol."""

    def test_is_format_provider(self) -> None:
        """IniFormatProvider satisfies the FormatProvider protocol."""
        from functualize._config.protocols import FormatProvider

        provider = IniFormatProvider()
        assert isinstance(provider, FormatProvider)
