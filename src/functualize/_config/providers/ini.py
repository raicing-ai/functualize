"""Built-in INI format provider.

Provides parsing and serialization for configparser-style INI files.

Only imports from Python stdlib and _config/errors.
"""

from __future__ import annotations

import configparser
import io
from typing import Any

from functualize._config.errors import FormatParseError


class IniFormatProvider:
    """Format provider for INI configuration files.

    Uses configparser with interpolation disabled.
    """

    def extensions(self) -> list[str]:
        """Return file extensions handled by this provider."""
        return [".ini", ".cfg"]

    def parse(self, path: str) -> dict[str, Any]:
        """Parse an INI configuration file into a nested dictionary.

        Args:
            path: Absolute path to the INI file.

        Returns:
            Dictionary mapping section names to dicts of key-value pairs.
            All values are strings (INI has no type information).

        Raises:
            FormatParseError: If the file is malformed or unreadable.
        """
        parser = configparser.ConfigParser(interpolation=None)

        try:
            files_read = parser.read(path, encoding="utf-8")
        except configparser.Error as exc:
            raise FormatParseError(path, str(exc)) from exc
        except OSError as exc:
            raise FormatParseError(path, str(exc)) from exc

        if not files_read:
            raise FormatParseError(path, "File not found or not readable")

        result: dict[str, Any] = {}
        for section in parser.sections():
            result[section] = dict(parser.items(section))

        return result

    def serialize(self, data: dict[str, Any]) -> str:
        """Serialize a configuration dictionary to INI format.

        Args:
            data: Configuration dictionary where top-level keys are section
                names and values are dicts of key-value pairs.

        Returns:
            INI-formatted string representation.
        """
        parser = configparser.ConfigParser(interpolation=None)

        for section, values in data.items():
            parser.add_section(section)
            if isinstance(values, dict):
                for key, value in values.items():
                    parser.set(section, str(key), str(value))

        output = io.StringIO()
        parser.write(output)
        return output.getvalue()
