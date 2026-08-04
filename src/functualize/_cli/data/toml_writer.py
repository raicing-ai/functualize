"""Atomic TOML section writer for TUI-staged config edits.

The TUI edits every value as text, but TOML is typed: writing a port back as
``port = "9090"`` silently changes an integer setting into a string. This
module renders each edited value using the type the field declares
(``FieldDef.type_annotation`` for job config, ``SettingSchema.type`` for TUI
settings) so a round-trip through the TUI preserves the file's types.

Writes go through a tempfile in the target directory followed by
``os.replace()``, so a failure mid-write can never leave a partial file.

This module is in the ``_cli/`` layer — stdlib only, no kernel imports.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["format_toml_value", "write_toml_section"]

# Type hints that mean "emit a bare TOML scalar, not a quoted string".
# Anything not listed here (str, enum, Path, unknown) is quoted — quoting is
# the safe default, since a mis-typed bare value is a parse error while an
# over-quoted value is merely a string.
_INT_HINTS = frozenset({"int"})
_FLOAT_HINTS = frozenset({"float"})
_BOOL_HINTS = frozenset({"bool"})
_LIST_HINTS = frozenset({"list", "list[str]", "sequence"})


def _quote(raw: str) -> str:
    """Render a TOML basic string, escaping what the spec requires."""
    escaped = (
        raw.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _normalize_hint(type_hint: str | None) -> str:
    """Reduce a type annotation to a lowercase bare name.

    Handles the ``Optional[int]`` / ``int | None`` shapes that
    ``FieldDef.type_annotation`` can carry, so an optional int still writes
    as a bare integer.
    """
    if not type_hint:
        return ""
    hint = type_hint.strip().lower()
    if hint.startswith("optional[") and hint.endswith("]"):
        hint = hint[len("optional[") : -1]
    # "int | none" -> "int"
    if "|" in hint:
        parts = [p.strip() for p in hint.split("|") if p.strip() not in ("none", "")]
        if len(parts) == 1:
            hint = parts[0]
    return hint.strip()


def format_toml_value(raw: str, type_hint: str | None = None) -> str:
    """Render a TUI-edited string as a TOML value literal.

    Falls back to a quoted string whenever the value does not actually parse
    as the hinted type — a user who types ``eight`` into an int field gets a
    still-parseable file plus a visibly wrong value, rather than a TOML
    syntax error that makes the whole file unloadable.

    Args:
        raw: The value as edited in the TUI.
        type_hint: The declared type (``FieldDef.type_annotation`` or
            ``SettingSchema.type``). ``None`` means "unknown" — quote it.

    Returns:
        A TOML value literal ready to place after ``key = ``.
    """
    hint = _normalize_hint(type_hint)

    if hint in _BOOL_HINTS:
        lowered = raw.strip().lower()
        if lowered in ("true", "false"):
            return lowered
        return _quote(raw)

    if hint in _INT_HINTS:
        try:
            return str(int(raw.strip()))
        except ValueError:
            return _quote(raw)

    if hint in _FLOAT_HINTS:
        try:
            return repr(float(raw.strip()))
        except ValueError:
            return _quote(raw)

    if hint in _LIST_HINTS:
        if not raw.strip():
            return "[]"
        items = [item.strip() for item in raw.split(",") if item.strip()]
        return "[" + ", ".join(_quote(item) for item in items) + "]"

    return _quote(raw)


def write_toml_section(
    path: Path,
    section: str,
    edits: dict[str, str],
    removals: set[str],
    type_hints: dict[str, str] | None = None,
) -> None:
    """Write edits and removals to a TOML section atomically.

    Strategy:
    - If file exists: read, locate section, modify in place (comments and
      unrelated sections are preserved verbatim)
    - If file doesn't exist: create minimal template
    - Uses tempfile in same directory + os.replace() for atomicity

    The section format:
    - Regular files: [section_name]
    - For nested sections like "tool.functualize.serve": [tool.functualize.serve]
    - An empty ``section`` targets the document top level — the keys before
      the first section header (``dotenv = true`` in ``.functualize.toml``).

    Args:
        path: The target TOML file path.
        section: The TOML section name (e.g., "serve" or "tool.functualize.serve"),
            or "" for document-top-level keys.
        edits: Mapping of key → new value to write.
        removals: Set of key names to remove from the section.
        type_hints: Optional mapping of key → declared type, used to emit
            correctly-typed literals. Keys absent from it are quoted.

    Raises:
        OSError: If the file cannot be written (permissions, disk full, etc.)
    """
    if not edits and not removals:
        return

    hints = type_hints or {}

    if path.exists():
        lines = path.read_text().splitlines(keepends=True)
        if section:
            lines = _apply_section_changes(
                lines, f"[{section}]", edits, removals, hints
            )
        else:
            lines = _apply_top_level_changes(lines, edits, removals, hints)
    else:
        # Create minimal template with section header (if any) and edited keys
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"[{section}]\n"] if section else []
        for key, value in edits.items():
            lines.append(f"{key} = {format_toml_value(value, hints.get(key))}\n")

    # Write atomically: tempfile in same directory, then os.replace()
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".toml.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.writelines(lines)
        os.replace(tmp_path, str(path))
    except BaseException:
        # Clean up tempfile on any failure
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _apply_section_changes(
    lines: list[str],
    section_header: str,
    edits: dict[str, str],
    removals: set[str],
    hints: dict[str, str],
) -> list[str]:
    """Apply edits and removals to a specific section within TOML lines.

    Locates the section header, then within that section (until next [header]
    or EOF): replaces existing key values, removes keys marked for removal,
    and appends new keys that don't already exist.

    Args:
        lines: The existing file lines (with newlines preserved).
        section_header: The section header string, e.g. "[serve]".
        edits: Key-value pairs to write.
        removals: Keys to remove.
        hints: Key → declared type, for typed literal emission.

    Returns:
        Modified list of lines.
    """
    # Find the section start
    section_start = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == section_header:
            section_start = i
            break

    if section_start == -1:
        # Section doesn't exist — append it at the end
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append("\n")
        lines.append(f"{section_header}\n")
        for key, value in edits.items():
            lines.append(f"{key} = {format_toml_value(value, hints.get(key))}\n")
        return lines

    # Find section end (next section header or EOF)
    section_end = len(lines)
    for i in range(section_start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("[") and not stripped.startswith("[["):
            section_end = i
            break

    # Process lines within the section
    result = list(lines[: section_start + 1])  # Include section header
    edited_keys: set[str] = set()

    for i in range(section_start + 1, section_end):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines and comments — keep them as-is
        if not stripped or stripped.startswith("#"):
            result.append(line)
            continue

        # Parse key = value
        if "=" in stripped:
            key_part = stripped.split("=", 1)[0].strip()

            if key_part in removals:
                continue  # Skip this line (remove it)

            if key_part in edits:
                literal = format_toml_value(edits[key_part], hints.get(key_part))
                result.append(f"{key_part} = {literal}\n")
                edited_keys.add(key_part)
                continue

        result.append(line)

    # Append new keys that weren't already in the section
    for key, value in edits.items():
        if key not in edited_keys:
            result.append(f"{key} = {format_toml_value(value, hints.get(key))}\n")

    # Append the rest of the file (after section end)
    result.extend(lines[section_end:])
    return result


def _apply_top_level_changes(
    lines: list[str],
    edits: dict[str, str],
    removals: set[str],
    hints: dict[str, str],
) -> list[str]:
    """Apply edits and removals to the document's top-level keys.

    The top-level region runs from the start of the file to the first
    section header; keys added there must land *before* that header, or
    TOML would attribute them to the section instead.
    """
    region_end = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and not stripped.startswith("[["):
            region_end = i
            break

    result: list[str] = []
    edited_keys: set[str] = set()

    for i in range(region_end):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            result.append(line)
            continue

        if "=" in stripped:
            key_part = stripped.split("=", 1)[0].strip()
            if key_part in removals:
                continue
            if key_part in edits:
                literal = format_toml_value(edits[key_part], hints.get(key_part))
                result.append(f"{key_part} = {literal}\n")
                edited_keys.add(key_part)
                continue

        result.append(line)

    for key, value in edits.items():
        if key not in edited_keys:
            result.append(f"{key} = {format_toml_value(value, hints.get(key))}\n")

    rest = lines[region_end:]
    if rest and result and result[-1].strip():
        # Keep a blank line between the top-level block and the first header.
        result.append("\n")
    result.extend(rest)
    return result
