"""INI to TOML configuration file migration utility.

Provides migrate_ini_to_toml() for converting INI configuration files
to TOML format, detecting unsupported interpolation references.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

from functualize._config.errors import MigrationError

# Pattern for %(key)s style interpolation references
_INTERPOLATION_PATTERN = re.compile(r"%\(\w+\)s")


def migrate_ini_to_toml(ini_path: str, toml_path: str) -> None:
    """Migrate an INI configuration file to TOML format.

    Reads the INI file, checks for interpolation references (which cannot
    be represented in TOML), and writes a TOML equivalent.

    Args:
        ini_path: Path to the source INI file.
        toml_path: Path to the target TOML file to create.

    Raises:
        OSError: If the INI file does not exist or cannot be read.
        MigrationError: If interpolation references are detected.
    """
    ini_file = Path(ini_path)
    if not ini_file.exists():
        raise OSError(f"INI file not found: {ini_path}")

    content = ini_file.read_text(encoding="utf-8")

    # Check for interpolation references in values (not comments or headers)
    _check_interpolation(content, ini_path)

    # Parse INI using RawConfigParser (no interpolation expansion)
    parser = configparser.RawConfigParser()
    parser.read_string(content)

    # Build TOML output
    toml_lines: list[str] = []
    sections = parser.sections()

    for i, section in enumerate(sections):
        if i > 0:
            toml_lines.append("")
        toml_lines.append(f"[{section}]")
        for key, value in parser.items(section):
            # Escape quotes in values for TOML string representation
            escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
            toml_lines.append(f'{key} = "{escaped_value}"')

    toml_content = "\n".join(toml_lines)
    if toml_lines:
        toml_content += "\n"

    Path(toml_path).write_text(toml_content, encoding="utf-8")


def _check_interpolation(content: str, file_path: str) -> None:
    """Check for %(key)s interpolation references in INI value lines.

    Only checks lines that are key-value pairs (not comments or headers).

    Raises:
        MigrationError: If an interpolation reference is found.
    """
    for line_num, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue

        # Skip section headers
        if stripped.startswith("["):
            continue

        # This is a key=value line — check for interpolation
        if _INTERPOLATION_PATTERN.search(stripped):
            raise MigrationError(
                file=file_path,
                line=line_num,
                construct="interpolation reference",
            )
