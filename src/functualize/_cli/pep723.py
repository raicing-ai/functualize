"""PEP 723 inline script metadata: dependencies, and the script's entry point.

Handles detection of `# /// script` metadata blocks in Python files,
checking whether declared dependencies are available, and delegating
execution to `uv run` when dependencies are missing.

The block also carries `[tool.functualize]`, which is what makes a `func`
script runnable *as a program* (T41)::

    #!/usr/bin/env -S func
    # /// script
    # dependencies = ["httpx"]
    #
    # [tool.functualize]
    # job = "fetch"
    # ///

Without that table, `func file.py …` reads the first argument as a **function
name** — so `./script.py --url x` fails with "Function '--url' not found", and
a bare `./script.py` prints a listing instead of running anything. Neither is
acceptable for something with a shebang: a program takes its own flags. The
declared `job` says "this file *is* that job", after which everything on the
command line belongs to it.

PEP 723 reserves `[tool.<name>]` for exactly this, so no new file, flag or
convention is involved — the metadata a script already carries gains one field.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPT_BLOCK_RE = re.compile(
    r"^# /// script\s*\n((?:#[^\n]*\n)*?)# ///$",
    re.MULTILINE,
)

_DEPTH_ENV_VAR = "_FUNCTUALIZE_PEP723_DEPTH"

#: Keys recognized in `[tool.functualize]`. Anything else earns a warning
#: rather than an error: a newer functualize may add keys, and refusing to run
#: a script because of a field this version has not heard of would be worse
#: than the typo it protects against. Silence would be worse still — that is
#: how a misspelled setting looks exactly like a setting with no effect.
_KNOWN_TOOL_KEYS = frozenset({"job"})


@dataclass(frozen=True)
class ScriptMetadata:
    """What a `# /// script` block declares.

    Attributes:
        dependencies: PEP 723 `dependencies`, or None if unset.
        job: `[tool.functualize] job` — the function this script runs when
            invoked as a program. None if unset, which keeps the pre-T41
            behaviour (first argument is read as a function name).
    """

    dependencies: list[str] | None = None
    job: str | None = None


def parse_script_metadata(source_file: Path) -> ScriptMetadata | None:
    """Parse the whole `# /// script` block once.

    Args:
        source_file: Path to the Python source file.

    Returns:
        The declared metadata, or None when there is no block, the file cannot
        be read, or the TOML is malformed. Malformed is deliberately treated as
        *absent* rather than fatal — the block is a comment, and a script whose
        dependencies are already installed must still run.
    """
    try:
        content = source_file.read_text(encoding="utf-8")
    except OSError:
        return None

    match = _SCRIPT_BLOCK_RE.search(content)
    if not match:
        return None

    # PEP 723: strip exactly `"# "`, or the single `"#"` on an otherwise empty
    # line. Not `lstrip("# ")` — that also eats leading spaces, reindenting
    # lines inside a multi-line TOML value.
    #
    # No key read here is whitespace-sensitive (`dependencies` is an array of
    # one-line strings, `job` is one string), so today the two rules give the
    # same answer and no test can tell them apart — a fact worth stating rather
    # than pretending otherwise. It is spelled correctly anyway because the
    # first whitespace-sensitive key added would otherwise be quietly mangled,
    # and that bug would look like malformed user TOML.
    toml_lines: list[str] = []
    for line in match.group(1).splitlines():
        stripped = line.rstrip()
        if stripped.startswith("# "):
            toml_lines.append(stripped[2:])
        elif stripped == "#":
            toml_lines.append("")
        else:
            toml_lines.append(stripped.lstrip("#"))
    toml_text = "\n".join(toml_lines)

    try:
        import tomllib

        data = tomllib.loads(toml_text)
    except Exception:
        # Malformed TOML treated as absent metadata (proceed normally)
        return None

    deps = data.get("dependencies")
    if not isinstance(deps, list):
        deps = None

    return ScriptMetadata(dependencies=deps, job=_parse_tool_table(data, source_file))


def _parse_tool_table(data: dict[str, Any], source_file: Path) -> str | None:
    """Read `[tool.functualize]`, warning about anything not understood."""
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return None
    table = tool.get("functualize")
    if not isinstance(table, dict):
        return None

    unknown = sorted(set(table) - _KNOWN_TOOL_KEYS)
    if unknown:
        print(
            f"Warning: {source_file.name}: unknown key(s) in "
            f"[tool.functualize]: {', '.join(unknown)}. Known: "
            f"{', '.join(sorted(_KNOWN_TOOL_KEYS))}.",
            file=sys.stderr,
        )

    job = table.get("job")
    return job if isinstance(job, str) and job else None


def parse_pep723_deps(source_file: Path) -> list[str] | None:
    """Parse PEP 723 inline script metadata for dependencies.

    Args:
        source_file: Path to the Python source file.

    Returns:
        List of dependency specifiers, or None if no metadata block found
        or if the block cannot be parsed (malformed TOML treated as absent).
    """
    metadata = parse_script_metadata(source_file)
    return metadata.dependencies if metadata is not None else None


def declared_job(source_file: Path) -> str | None:
    """The function a script declares as its entry point, if any (T41)."""
    metadata = parse_script_metadata(source_file)
    return metadata.job if metadata is not None else None


def check_deps_available(deps: list[str]) -> list[str]:
    """Check which dependencies are missing from the current environment.

    Normalizes package names by replacing hyphens with underscores for
    the import check using importlib.util.find_spec().

    Args:
        deps: List of dependency specifiers (e.g., ["requests>=2.0", "rich"]).

    Returns:
        List of dependency specifiers that are NOT available in the
        current environment.
    """
    missing: list[str] = []
    for dep in deps:
        # Extract package name from specifier (strip version constraints)
        package_name = _extract_package_name(dep)
        # Normalize: replace hyphens with underscores for import check
        import_name = package_name.replace("-", "_")
        if importlib.util.find_spec(import_name) is None:
            missing.append(dep)
    return missing


def maybe_delegate_to_uv(
    source_file: Path,
    cli_args: list[str],
    *,
    metadata: ScriptMetadata | None = None,
) -> bool:
    """Check PEP 723 deps and delegate to uv if needed.

    Enhancements:
    - Recursion guard via _FUNCTUALIZE_PEP723_DEPTH env var (max 1)
    - Informational message to stderr listing missing packages
    - Structured error when uv not found (includes manual instructions)
    - Malformed TOML treated as absent (no metadata)

    Args:
        source_file: Path to the Python source file.
        cli_args: CLI arguments to pass through to the delegated execution.
        metadata: Already-parsed block, when the caller has one. Passing it
            avoids a second parse — which would also re-print any
            `[tool.functualize]` warning, and a warning shown twice reads as
            two problems.

    Returns:
        True if execution was delegated (caller should exit).
        Returns False if normal execution should proceed.
    """
    if metadata is None:
        metadata = parse_script_metadata(source_file)
    deps = metadata.dependencies if metadata is not None else None
    if deps is None:
        return False

    missing = check_deps_available(deps)
    if not missing:
        return False

    # ── Recursion guard ──────────────────────────────────────────────────
    # If _FUNCTUALIZE_PEP723_DEPTH is already set to a non-zero value,
    # we've already delegated once and deps are still missing.
    depth_str = os.environ.get(_DEPTH_ENV_VAR, "")
    if depth_str and depth_str != "0":
        _missing_names = ", ".join(_extract_package_name(d) for d in missing)
        print(
            f"Error: Dependencies still missing after uv delegation: "
            f"{_missing_names}\n"
            f"\n"
            f"The following packages could not be resolved automatically:\n"
            f"  {', '.join(missing)}\n"
            f"\n"
            f"To fix this manually, install the missing packages:\n"
            f"  pip install {' '.join(_extract_package_name(d) for d in missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Check if uv is available ─────────────────────────────────────────
    if shutil.which("uv") is None:
        _missing_names = ", ".join(_extract_package_name(d) for d in missing)
        print(
            f"Error: Cannot resolve inline script dependencies — "
            f"'uv' is not installed.\n"
            f"\n"
            f"The script '{source_file.name}' declares PEP 723 dependencies "
            f"that are not available:\n"
            f"  {', '.join(missing)}\n"
            f"\n"
            f"To auto-resolve, install uv:\n"
            f"  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            f"  # or: pip install uv\n"
            f"\n"
            f"To resolve manually without uv:\n"
            f"  pip install {' '.join(_extract_package_name(d) for d in missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Print informational message ──────────────────────────────────────
    _missing_names = ", ".join(_extract_package_name(d) for d in missing)
    print(
        f"\u2139 Resolving missing dependencies via uv: {_missing_names}...",
        file=sys.stderr,
    )

    # ── Set recursion guard and delegate ─────────────────────────────────
    env = os.environ.copy()
    env[_DEPTH_ENV_VAR] = "1"

    uv_cmd = ["uv", "run", "--with", "functualize"]
    for dep in deps:
        uv_cmd.extend(["--with", dep])
    uv_cmd.extend(["--", sys.executable, "-m", "functualize"] + cli_args)

    sys.exit(subprocess.call(uv_cmd, env=env))

    # Technically unreachable, but satisfies the return type
    return True  # pragma: no cover


def _extract_package_name(dep: str) -> str:
    """Extract the package name from a dependency specifier.

    Handles specifiers like:
      - "requests"
      - "requests>=2.0"
      - "my-package[extra]>=1.0"
      - "package ==1.0"

    Args:
        dep: A PEP 508 dependency specifier string.

    Returns:
        The bare package name without version constraints or extras.
    """
    # Strip leading/trailing whitespace
    dep = dep.strip()
    # Split on version specifiers and extras
    # Package name is the part before any of: [, >, <, =, !, ~, ;, @
    match = re.match(r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)", dep)
    if match:
        return match.group(1)
    return dep
