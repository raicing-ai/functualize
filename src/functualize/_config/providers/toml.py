"""Built-in TOML format provider using stdlib tomllib for parsing.

Implements the FormatProvider protocol for TOML configuration files.
Parsing uses Python's standard library ``tomllib`` module. Serialization
produces valid TOML output using a lightweight custom serializer (since
``tomllib`` is read-only).

Only imports from Python stdlib and _config/errors.
"""

from __future__ import annotations

import tomllib
from datetime import date, datetime, time
from typing import Any

from functualize._config.errors import FormatParseError


class TomlFormatProvider:
    """Format provider for TOML configuration files.

    Uses stdlib ``tomllib`` for parsing and a custom serializer for output.
    Handles ``.toml`` file extension.
    """

    def extensions(self) -> list[str]:
        """Return file extensions handled by this provider."""
        return [".toml"]

    def parse(self, path: str) -> dict[str, Any]:
        """Parse a TOML configuration file.

        Args:
            path: Absolute path to the TOML file.

        Returns:
            Parsed configuration as a normalized dictionary.

        Raises:
            FormatParseError: If the file cannot be read or contains
                malformed TOML.
        """
        try:
            with open(path, "rb") as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise FormatParseError(path=path, reason=str(exc)) from exc
        except OSError as exc:
            raise FormatParseError(path=path, reason=str(exc)) from exc

    def serialize(self, data: dict[str, Any]) -> str:
        """Serialize a configuration dictionary to TOML format.

        Produces valid TOML with conventional formatting:
        - Top-level scalar keys appear first
        - Nested tables use ``[section]`` headers
        - Arrays of tables use ``[[section]]`` headers
        - Strings are double-quoted
        - Multi-level nesting uses dotted table headers

        Args:
            data: Configuration dictionary to serialize.

        Returns:
            TOML-formatted string.
        """
        return _serialize_document(data)


def _serialize_document(data: dict[str, Any]) -> str:
    """Serialize a full TOML document from a dictionary."""
    lines: list[str] = []
    _serialize_table(data, [], lines)
    result = "\n".join(lines)
    if result and not result.endswith("\n"):
        result += "\n"
    return result


def _serialize_table(data: dict[str, Any], path: list[str], lines: list[str]) -> None:
    """Recursively serialize a table, emitting scalar keys first then sub-tables."""
    scalar_keys: list[str] = []
    table_keys: list[str] = []
    array_of_tables_keys: list[str] = []

    for key, value in data.items():
        if isinstance(value, dict):
            table_keys.append(key)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            array_of_tables_keys.append(key)
        else:
            scalar_keys.append(key)

    # Emit scalar key-value pairs
    for key in scalar_keys:
        lines.append(f"{_format_key(key)} = {_format_value(data[key])}")

    # Emit sub-tables
    for key in table_keys:
        sub_path = [*path, key]
        header = ".".join(_format_key(k) for k in sub_path)
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"[{header}]")
        _serialize_table(data[key], sub_path, lines)

    # Emit arrays of tables
    for key in array_of_tables_keys:
        sub_path = [*path, key]
        header = ".".join(_format_key(k) for k in sub_path)
        for item in data[key]:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[[{header}]]")
            if isinstance(item, dict):
                _serialize_table(item, sub_path, lines)
            else:
                lines.append(f"value = {_format_value(item)}")


def _format_key(key: str) -> str:
    """Format a TOML key, quoting if necessary."""
    if key and all(c.isalnum() or c in "-_" for c in key):
        return key
    return _format_basic_string(key)


def _format_value(value: Any) -> str:
    """Format a single TOML value."""
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return "nan"
        if value == float("inf"):
            return "inf"
        if value == float("-inf"):
            return "-inf"
        return str(value)
    if isinstance(value, str):
        return _format_basic_string(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, list):
        return _format_array(value)
    if isinstance(value, dict):
        return _format_inline_table(value)
    return _format_basic_string(str(value))


def _format_basic_string(s: str) -> str:
    """Format a TOML basic string with proper escaping."""
    escaped = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace("\b", "\\b")
        .replace("\f", "\\f")
    )
    return f'"{escaped}"'


def _format_array(values: list[Any]) -> str:
    """Format a TOML array."""
    if not values:
        return "[]"
    formatted = [_format_value(v) for v in values]
    single_line = f"[{', '.join(formatted)}]"
    if len(single_line) <= 80:
        return single_line
    inner = ",\n".join(f"    {item}" for item in formatted)
    return f"[\n{inner},\n]"


def _format_inline_table(data: dict[str, Any]) -> str:
    """Format a TOML inline table."""
    if not data:
        return "{}"
    pairs = [f"{_format_key(k)} = {_format_value(v)}" for k, v in data.items()]
    return "{" + ", ".join(pairs) + "}"
