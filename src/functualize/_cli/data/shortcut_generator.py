"""Shortcut file content generation (Python-only).

Generates valid Python shortcut files from a job name and keyword
arguments. Shortcuts are ordinary functualize job modules that invoke the
target with fixed arguments; a module-level ``JOB_GROUP = "shortcut"``
groups every generated shortcut under the ``shortcut.*`` namespace so a
shortcut named after its target job (e.g. a shortcut for job ``deploy``
defaulting to the name ``deploy``) never collides with the real
top-level job.

This module is in the ``_cli/`` layer — it imports only from stdlib.
"""

from __future__ import annotations

import keyword
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShortcutSpec:
    """Specification for generating a Python shortcut file.

    Attributes:
        shortcut_name: Name used for the generated function.
        job_name: The target job to invoke.
        kwargs: Keyword arguments to pass to the target job.
        output_file: The full path (as typed by the user) of the file the
            shortcut will be written or appended to.
    """

    shortcut_name: str
    job_name: str
    kwargs: dict[str, str]
    output_file: Path


def _validate_shortcut_name(name: str) -> None:
    """Validate that ``name`` is a usable Python function identifier.

    Args:
        name: The shortcut name to validate.

    Raises:
        ValueError: If the name is empty, not a valid Python identifier,
            or a Python keyword.
    """
    if not name:
        raise ValueError("Shortcut name must not be empty.")

    if not name.isidentifier():
        raise ValueError(f"Shortcut name {name!r} is not a valid Python identifier.")
    if keyword.iskeyword(name):
        raise ValueError(f"Shortcut name {name!r} is a Python keyword.")


def _escape_python_string(value: str) -> str:
    """Escape a string value for embedding in a Python source double-quoted string.

    Handles backslashes, double quotes, newlines, and other control characters.
    """
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


# The module-level group assignment emitted by ``_generate_python_shortcut``
# — this groups every generated shortcut under the ``shortcut.*`` namespace
# (see ``functualize._discovery.naming.qualified_name``) so a shortcut
# named after its target job never collides with the real top-level job.
_JOB_GROUP_LINE = 'JOB_GROUP = "shortcut"'

# The import line emitted by ``_generate_python_shortcut`` — deduplicated
# by exact string match when appending to an existing file (see
# ``append_or_write_python_shortcut``).
_PYTHON_IMPORT_LINE = "from functualize.job import Invoke, Log"


def _generate_python_shortcut(spec: ShortcutSpec) -> str:
    """Generate a Python job file that invokes the target with fixed args.

    Output is a valid functualize job module:
    - Has a module docstring
    - Declares ``JOB_GROUP = "shortcut"`` so the shortcut registers as
      ``shortcut.<shortcut_name>``, avoiding collisions with real jobs
    - Imports RunContext capabilities
    - Defines a function with the shortcut name
    - Calls invoke(job_name, **kwargs)
    """
    escaped_job_name = _escape_python_string(spec.job_name)
    lines = [
        f'"""Auto-generated shortcut for: {spec.job_name}"""',
        "",
        _JOB_GROUP_LINE,
        "",
        _PYTHON_IMPORT_LINE,
        "",
        "",
        f"def {spec.shortcut_name}(log: Log, invoke: Invoke):",
        f'    """Shortcut: {spec.job_name} with preset arguments."""',
        f'    invoke("{escaped_job_name}",',
    ]
    for key, value in spec.kwargs.items():
        escaped_value = _escape_python_string(value)
        lines.append(f'        {key}="{escaped_value}",')
    lines.append("    )")
    lines.append("")
    return "\n".join(lines)


def _collapse_blank_line_runs(lines: list[str], max_consecutive: int = 2) -> list[str]:
    """Collapse runs of 3+ consecutive blank lines down to ``max_consecutive``.

    Used after stripping duplicate lines (import / JOB_GROUP) so the
    appended block doesn't leave an oversized gap where they used to sit.
    """
    result: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run > max_consecutive:
                continue
        else:
            blank_run = 0
        result.append(line)
    return result


def append_or_write_python_shortcut(spec: ShortcutSpec, generated_content: str) -> None:
    """Write a Python shortcut, appending to an existing file rather than overwriting.

    - If ``spec.output_file`` does not exist yet, ``generated_content`` is
      written fresh (identical to a plain overwrite).
    - If it already exists, ``generated_content``'s function block is
      appended to the end of the file, separated by two blank lines
      (PEP 8 style, matching the spacing ``_generate_python_shortcut``
      already uses between its own import and function def).
    - The import line (``from functualize.job import Invoke, Log``) and the
      ``JOB_GROUP = "shortcut"`` line are each skipped from the appended
      block if ALREADY PRESENT VERBATIM (exact string match) anywhere in
      the existing file. This is a deliberately simple exact-line check —
      not AST-based merging — to avoid the risk of rewriting a user's
      existing source. A structurally different line in the existing file
      is left alone and the new line is appended as-is (redundant lines
      are an acceptable trade-off for that edge case).

    Args:
        spec: The shortcut specification (used for ``output_file``).
        generated_content: The Python source to write/append. Normally
            ``generate_shortcut_content(spec)``, but callers may pass
            edited content (e.g. from an editable preview widget).
    """
    output_file = spec.output_file
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if not output_file.exists():
        output_file.write_text(generated_content, encoding="utf-8")
        return

    existing_content = output_file.read_text(encoding="utf-8")

    block_lines = generated_content.splitlines()
    for dedup_line in (_JOB_GROUP_LINE, _PYTHON_IMPORT_LINE):
        if dedup_line in existing_content:
            block_lines = [ln for ln in block_lines if ln != dedup_line]
    block_lines = _collapse_blank_line_runs(block_lines)
    block = "\n".join(block_lines).strip("\n")

    new_content = existing_content.rstrip("\n") + "\n\n\n" + block + "\n"
    output_file.write_text(new_content, encoding="utf-8")


def generate_shortcut_content(spec: ShortcutSpec) -> str:
    """Generate the file content for a shortcut specification.

    Validates the shortcut name, then generates the Python job function
    that invokes the target with fixed args.

    Args:
        spec: The shortcut specification describing what to generate.

    Returns:
        The generated file content as a string.

    Raises:
        ValueError: If the shortcut name is not a valid Python identifier.
    """
    _validate_shortcut_name(spec.shortcut_name)
    return _generate_python_shortcut(spec)
