"""Unit tests for the built-in TOML format provider."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from functualize._config.errors import FormatParseError
from functualize._config.protocols import FormatProvider
from functualize._config.providers.toml import TomlFormatProvider


@pytest.fixture
def provider() -> TomlFormatProvider:
    """Create a TomlFormatProvider instance."""
    return TomlFormatProvider()


def _write_toml(content: str) -> str:
    """Write content to a temporary TOML file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".toml")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


class TestProtocolConformance:
    """Verify TomlFormatProvider satisfies the FormatProvider protocol."""

    def test_is_instance_of_format_provider(self, provider: TomlFormatProvider) -> None:
        assert isinstance(provider, FormatProvider)

    def test_has_extensions_method(self, provider: TomlFormatProvider) -> None:
        result = provider.extensions()
        assert isinstance(result, list)
        assert all(isinstance(ext, str) for ext in result)

    def test_has_parse_method(self, provider: TomlFormatProvider) -> None:
        assert callable(provider.parse)

    def test_has_serialize_method(self, provider: TomlFormatProvider) -> None:
        assert callable(provider.serialize)


class TestExtensions:
    """Test the extensions() method."""

    def test_returns_toml_extension(self, provider: TomlFormatProvider) -> None:
        assert provider.extensions() == [".toml"]

    def test_extension_includes_leading_dot(self, provider: TomlFormatProvider) -> None:
        for ext in provider.extensions():
            assert ext.startswith(".")


class TestParse:
    """Test the parse() method."""

    def test_parse_simple_key_values(self, provider: TomlFormatProvider) -> None:
        path = _write_toml('name = "test"\ncount = 42\n')
        try:
            result = provider.parse(path)
            assert result == {"name": "test", "count": 42}
        finally:
            os.unlink(path)

    def test_parse_nested_table(self, provider: TomlFormatProvider) -> None:
        content = '[database]\nhost = "localhost"\nport = 5432\n'
        path = _write_toml(content)
        try:
            result = provider.parse(path)
            assert result == {"database": {"host": "localhost", "port": 5432}}
        finally:
            os.unlink(path)

    def test_parse_array_of_tables(self, provider: TomlFormatProvider) -> None:
        content = '[[servers]]\nname = "alpha"\n\n[[servers]]\nname = "beta"\n'
        path = _write_toml(content)
        try:
            result = provider.parse(path)
            assert result == {"servers": [{"name": "alpha"}, {"name": "beta"}]}
        finally:
            os.unlink(path)

    def test_parse_boolean_values(self, provider: TomlFormatProvider) -> None:
        path = _write_toml("enabled = true\ndebug = false\n")
        try:
            result = provider.parse(path)
            assert result == {"enabled": True, "debug": False}
        finally:
            os.unlink(path)

    def test_parse_float_values(self, provider: TomlFormatProvider) -> None:
        path = _write_toml("pi = 3.14159\nrate = 1.0\n")
        try:
            result = provider.parse(path)
            assert result["pi"] == 3.14159
            assert result["rate"] == 1.0
        finally:
            os.unlink(path)

    def test_parse_array_values(self, provider: TomlFormatProvider) -> None:
        path = _write_toml('tags = ["a", "b", "c"]\n')
        try:
            result = provider.parse(path)
            assert result == {"tags": ["a", "b", "c"]}
        finally:
            os.unlink(path)

    def test_parse_empty_file(self, provider: TomlFormatProvider) -> None:
        path = _write_toml("")
        try:
            result = provider.parse(path)
            assert result == {}
        finally:
            os.unlink(path)

    def test_parse_malformed_toml_raises_format_parse_error(
        self, provider: TomlFormatProvider
    ) -> None:
        path = _write_toml("[invalid\nkey = ")
        try:
            with pytest.raises(FormatParseError) as exc_info:
                provider.parse(path)
            assert exc_info.value.path == path
            assert exc_info.value.reason != ""
        finally:
            os.unlink(path)

    def test_parse_nonexistent_file_raises_format_parse_error(
        self, provider: TomlFormatProvider
    ) -> None:
        with pytest.raises(FormatParseError) as exc_info:
            provider.parse("/nonexistent/path/config.toml")
        assert exc_info.value.path == "/nonexistent/path/config.toml"

    def test_parse_error_preserves_path(self, provider: TomlFormatProvider) -> None:
        path = _write_toml("= invalid")
        try:
            with pytest.raises(FormatParseError) as exc_info:
                provider.parse(path)
            assert exc_info.value.path == path
        finally:
            os.unlink(path)


class TestSerialize:
    """Test the serialize() method."""

    def test_serialize_empty_dict(self, provider: TomlFormatProvider) -> None:
        result = provider.serialize({})
        assert result == ""

    def test_serialize_simple_string(self, provider: TomlFormatProvider) -> None:
        result = provider.serialize({"name": "test"})
        assert 'name = "test"' in result

    def test_serialize_integer(self, provider: TomlFormatProvider) -> None:
        result = provider.serialize({"count": 42})
        assert "count = 42" in result

    def test_serialize_float(self, provider: TomlFormatProvider) -> None:
        result = provider.serialize({"rate": 1.5})
        assert "rate = 1.5" in result

    def test_serialize_boolean_true(self, provider: TomlFormatProvider) -> None:
        result = provider.serialize({"flag": True})
        assert "flag = true" in result

    def test_serialize_boolean_false(self, provider: TomlFormatProvider) -> None:
        result = provider.serialize({"flag": False})
        assert "flag = false" in result

    def test_serialize_array(self, provider: TomlFormatProvider) -> None:
        result = provider.serialize({"tags": ["a", "b"]})
        assert 'tags = ["a", "b"]' in result

    def test_serialize_nested_table(self, provider: TomlFormatProvider) -> None:
        data: dict[str, Any] = {"database": {"host": "localhost", "port": 5432}}
        result = provider.serialize(data)
        assert "[database]" in result
        assert 'host = "localhost"' in result
        assert "port = 5432" in result

    def test_serialize_array_of_tables(self, provider: TomlFormatProvider) -> None:
        data: dict[str, Any] = {"servers": [{"name": "alpha"}, {"name": "beta"}]}
        result = provider.serialize(data)
        assert "[[servers]]" in result
        assert 'name = "alpha"' in result
        assert 'name = "beta"' in result

    def test_serialize_special_characters_in_string(
        self, provider: TomlFormatProvider
    ) -> None:
        data = {"msg": 'He said "hello"\nGoodbye'}
        result = provider.serialize(data)
        assert '\\"hello\\"' in result
        assert "\\n" in result

    def test_serialize_key_with_spaces_is_quoted(
        self, provider: TomlFormatProvider
    ) -> None:
        result = provider.serialize({"key with spaces": "value"})
        assert '"key with spaces"' in result

    def test_serialize_trailing_newline(self, provider: TomlFormatProvider) -> None:
        result = provider.serialize({"key": "value"})
        assert result.endswith("\n")


class TestRoundTrip:
    """Test that serialize then parse produces equivalent data."""

    def _round_trip(
        self, provider: TomlFormatProvider, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Serialize data to TOML, write to temp file, parse back."""
        output = provider.serialize(data)
        path = _write_toml(output)
        try:
            return provider.parse(path)
        finally:
            os.unlink(path)

    def test_round_trip_scalars(self, provider: TomlFormatProvider) -> None:
        data: dict[str, Any] = {
            "name": "hello",
            "count": 99,
            "rate": 2.5,
            "flag": True,
        }
        assert self._round_trip(provider, data) == data

    def test_round_trip_nested(self, provider: TomlFormatProvider) -> None:
        data: dict[str, Any] = {"section": {"key": "value", "nested": {"deep": 42}}}
        assert self._round_trip(provider, data) == data

    def test_round_trip_arrays(self, provider: TomlFormatProvider) -> None:
        data: dict[str, Any] = {"items": ["a", "b", "c"], "nums": [1, 2, 3]}
        assert self._round_trip(provider, data) == data

    def test_round_trip_array_of_tables(self, provider: TomlFormatProvider) -> None:
        data: dict[str, Any] = {
            "entries": [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]
        }
        assert self._round_trip(provider, data) == data

    def test_round_trip_empty_dict(self, provider: TomlFormatProvider) -> None:
        assert self._round_trip(provider, {}) == {}

    def test_round_trip_empty_array(self, provider: TomlFormatProvider) -> None:
        data: dict[str, Any] = {"items": []}
        assert self._round_trip(provider, data) == data
