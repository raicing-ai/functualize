"""Shared discovery-cache format: single source of truth for the cache file.

The discovery cache is a single JSON file managed by
CachedDirectoryScanProvider. Its location is mode-dependent:
- Declared-project mode: `.functualize/cache.json`
- Standalone mode: `$XDG_CACHE_HOME/functualize/<project_id>/cache.json`

This module holds the format version, filename, location resolution, and
the global-invalidation helpers so that the writer (the provider) and the
readers (CLI routing fast path, `func cache` commands) never drift.

Lives in `_primitives/` (stdlib-only) because the CLI routing fast path
reads it inside a ~3ms budget — it must not pull `_discovery/`'s package
imports or any heavy dependency (no pydantic, no `_types`).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from functualize._primitives.locator import _xdg_cache_dir, compute_project_id

# Current cache file format version. Bump on any incompatible format change.
# v4: FieldDescriptor gained is_stdin/stdin_flag (Stdin() marker fidelity in the
# warm --help tree). Backward-compatible on read, but the bump forces a one-time
# rebuild so existing warm caches pick up the new fields immediately.
# v5: JobDescriptor gained requires_tty/optional_tty/uses_live (TTY/Live capability
# markers harvested from the signature). Warm/lazy boot routes on these without
# importing the job, so they must be cached. Backward-compatible on read (missing
# keys default False); the bump forces a one-time rebuild.
# v6: JobDescriptor gained suppress_live (@job(suppress_live=[...])), read at
# surface-setup time to decide which ambient live constructs to pre-mount —
# so it must be available without importing the job. Backward-compatible on
# read (missing key means "suppress nothing"); the bump forces a one-time
# rebuild.
# v7 (2026-07-19): new top-level "displays" section ({source_file:
# DisplayCacheEntry}) so display discovery piggybacks on the job scan and the
# TUI imports only flagged modules; JobDescriptor gained surface_hint
# (@surface_hint("stdout"|"panel")), read by the surface-resolution ladder
# without importing the job. Backward-compatible on read (missing section =
# no cached displays, missing key = no hint); the bump forces a one-time
# rebuild.
# v8 (2026-07-19): JobDescriptor gained decorators (root names of the decorators
# applied to the function, read from the source AST). Job-level filtering on
# require_job_decorators is applied on the cache-read path, so the names must
# survive in the cache. Backward-compatible on read (missing key = no decorators
# recorded); the bump forces a one-time rebuild so pre-v8 entries don't read as
# "undecorated" under an active decorator filter.
# v9 (2026-07-20): JobDescriptor gained declaration (the frozen JobDeclaration
# from @job(...): deps/cache/guards/exec/matrix + identity overrides). Warm/lazy
# boot resolves deps, guards, and execution policy without importing the job, so
# the declaration must be cached. Backward-compatible on read (missing key =
# convention job, None); the bump forces a one-time rebuild so pre-v9 entries
# don't read as "no declaration" under the task-runner engine.
# v10 (2026-07-20): JobDescriptor gained workflow (the @workflow graph shape:
# node names, node kinds, edges, and branch targets). Listing and describing a
# workflow — including over MCP — must not import the declaring module, so the
# topology is cached. Gate model classes and branch conditions are NOT cached
# (they are live objects); only the gate's model *name* survives, and the real
# schema materializes on demand. Backward-compatible on read (missing key =
# not a workflow); the bump forces a one-time rebuild.
# v11 (2026-07-21): JobDescriptor gained from_job_deps — the dependency edges
# derived from `FromJob` parameters. They live in the signature, so a warm boot
# (function not imported) cannot re-derive them and would silently drop them.
# v12 (2026-07-21): JobDeclaration lost `name` and `aliases`. Both were second
# spellings of one job, and `from_dict` reads those keys positionally-by-name,
# so a v11 entry would raise KeyError rather than degrade. The bump forces a
# one-time rebuild instead.
# v13 (2026-07-23): new top-level "group_options" section ({group_path:
# GroupOptionsSpec}) from `class X(GroupOptions, group="...")` declarations.
# Mid-path group flags must be parsed by surfaces that never boot — completion
# and the shell — so the declared flags are cached as pure data and the
# declaring class is imported only to validate a value. Backward-compatible on
# read (missing section = no group options); the bump forces a one-time rebuild
# so pre-v13 caches don't read as "this group declares no flags" and reject a
# legal invocation.
# v14 (2026-07-23): JobDeclaration lost `pipe`. It was declared, validated and
# cached but read by nothing, and the Part C redesign dissolved its meaning:
# "force the piped surface" mattered only while the return value was
# auto-emitted, and emission is now explicit (`out.emit()`, never
# surface-suppressed). What remained — "render as if piped" — is already the
# surface-hint ladder's job. `from_dict` reads keys by name, so a v13 entry
# would raise KeyError rather than degrade; the bump forces a one-time rebuild.
# v15 (2026-08-27): FieldDescriptor gained `secret`. The TUI panels mask from the
# cached descriptor — a warm boot never imports the config model — so a v14 entry
# would render every credential in cleartext until the next rescan. `_field_from_dict`
# defaults the key to False, which is exactly the wrong direction to fail in, so the
# version bump (not the default) is what protects the value.
# v16 (2026-08-29): new header field `discovery_hash`, fingerprinting the effective
# discovery filter configuration. Without it the cache was replayed under whatever
# filters happened to be active: adding `[discovery] exclude_patterns` after a warm
# run did nothing, and a single `--exclude` run removed the excluded jobs *permanently*
# — the next flagless invocation replayed the filtered `pre_filter_decisions` and
# `func <job>` answered "Unknown command". The bump is not cosmetic: anyone who ran
# `--exclude` on 0.1.0 has a poisoned cache on disk right now, and only the version
# check reaches it, because a 0.1.0 cache carries no `discovery_hash` to compare.
CACHE_VERSION = 16

# Cache file name within the resolved cache directory.
CACHE_FILENAME = "cache.json"


@dataclass(frozen=True)
class PreFilterDecision:
    """Persisted negative pre-filter decision.

    Only negative decisions (eligible=False) are persisted. Positive decisions
    don't need caching — the module gets imported and cached as a descriptor.

    Attributes:
        source_file: Absolute path to the source .py file.
        eligible: Always False when persisted.
        source_mtime: os.path.getmtime() value at decision time (float timestamp).
    """

    source_file: str
    eligible: bool  # Always False when persisted
    source_mtime: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "source_file": self.source_file,
            "eligible": self.eligible,
            "source_mtime": self.source_mtime,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PreFilterDecision:
        """Deserialize from a JSON dict.

        Raises:
            ValueError: If required keys are missing or values have wrong types.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a dict for PreFilterDecision, got {type(data).__name__}"
            )
        required_keys = {"source_file", "eligible", "source_mtime"}
        missing = required_keys - set(data.keys())
        if missing:
            raise ValueError(
                f"Missing required keys in PreFilterDecision dict: {sorted(missing)}"
            )
        if not isinstance(data["source_file"], str):
            raise ValueError(
                f"Expected 'source_file' to be str, got {type(data['source_file']).__name__}"
            )
        if not isinstance(data["eligible"], bool):
            raise ValueError(
                f"Expected 'eligible' to be bool, got {type(data['eligible']).__name__}"
            )
        if not isinstance(data["source_mtime"], int | float):
            raise ValueError(
                f"Expected 'source_mtime' to be a number, got {type(data['source_mtime']).__name__}"
            )
        return cls(
            source_file=data["source_file"],
            eligible=data["eligible"],
            source_mtime=float(data["source_mtime"]),
        )


@dataclass(frozen=True)
class DisplayCacheEntry:
    """Persisted record of DisplayProvider classes found in a module.

    Written by the job scan's display-detection pass so the TUI can import
    only the modules known to contain displays. Validated the same way as
    job entries: mtime first, content hash on mismatch.

    Attributes:
        source_file: Absolute path to the source .py file.
        class_names: Names of the DisplayProvider classes in the module.
        source_mtime: os.path.getmtime() value at scan time.
        content_hash: sha256 hex digest of the file content at scan time.
    """

    source_file: str
    class_names: tuple[str, ...]
    source_mtime: float
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "source_file": self.source_file,
            "class_names": list(self.class_names),
            "source_mtime": self.source_mtime,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DisplayCacheEntry:
        """Deserialize from a JSON dict.

        Raises:
            ValueError: If required keys are missing or values have wrong types.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a dict for DisplayCacheEntry, got {type(data).__name__}"
            )
        required_keys = {"source_file", "class_names", "source_mtime", "content_hash"}
        missing = required_keys - set(data.keys())
        if missing:
            raise ValueError(
                f"Missing required keys in DisplayCacheEntry dict: {sorted(missing)}"
            )
        if not isinstance(data["source_file"], str):
            raise ValueError(
                f"Expected 'source_file' to be str, got {type(data['source_file']).__name__}"
            )
        if not isinstance(data["class_names"], list) or not all(
            isinstance(name, str) for name in data["class_names"]
        ):
            raise ValueError("Expected 'class_names' to be a list of str")
        if not isinstance(data["source_mtime"], int | float):
            raise ValueError(
                f"Expected 'source_mtime' to be a number, got {type(data['source_mtime']).__name__}"
            )
        if not isinstance(data["content_hash"], str):
            raise ValueError(
                f"Expected 'content_hash' to be str, got {type(data['content_hash']).__name__}"
            )
        return cls(
            source_file=data["source_file"],
            class_names=tuple(data["class_names"]),
            source_mtime=float(data["source_mtime"]),
            content_hash=data["content_hash"],
        )


def find_functualize_dir(start: Path) -> Path | None:
    """Search upward from start for a .functualize/ directory.

    Args:
        start: The directory to start the upward search from.

    Returns:
        Path to the .functualize/ directory if found, None otherwise.
    """
    current = start
    while True:
        candidate = current / ".functualize"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def resolve_cache_path(start: Path) -> Path:
    """Resolve the discovery cache file path for a project.

    Mirrors the ResourceLocator wiring in build_cached_provider so that
    readers that must not boot the app (CLI routing fast path, `func cache`
    commands) agree with the writer on the file location:
    - Declared-project mode (.functualize/ found upward): that directory.
    - Standalone mode: XDG platform cache keyed by project_id of `start`.

    Args:
        start: Project root (or cwd) to resolve from.

    Returns:
        Absolute path where the cache file lives (may not exist yet).
    """
    start = Path(start).resolve()
    functualize_dir = find_functualize_dir(start)
    if functualize_dir is not None:
        return functualize_dir / CACHE_FILENAME
    project_id = compute_project_id(str(start))
    return _xdg_cache_dir() / "functualize" / project_id / CACHE_FILENAME


def get_functualize_version() -> str:
    """Get the currently installed functualize version."""
    try:
        return importlib.metadata.version("functualize")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def compute_deps_hash(project_root: Path) -> str:
    """Compute sha256 hash of pyproject.toml's [project.dependencies] section.

    Returns a "sha256:<hex>" string. If pyproject.toml doesn't exist or the
    section is unreadable, returns a sentinel that won't match any cached value,
    which triggers global invalidation.
    """
    pyproject_path = project_root / "pyproject.toml"

    try:
        content = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        return "sha256:__UNREADABLE__"

    deps_text = _extract_dependencies_section(content)
    if deps_text is None:
        return "sha256:__UNREADABLE__"

    digest = hashlib.sha256(deps_text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compute_discovery_hash(fields: Sequence[tuple[str, object]]) -> str:
    """Compute a sha256 fingerprint of the effective discovery filter config.

    Returns a "sha256:<hex>" string. Callers pass ``(name, value)`` pairs for the
    discovery settings that shape which modules and jobs are admitted; the pairs
    are sorted by name, so declaration order does not affect the digest.

    ``None`` and an empty container hash **differently** on purpose. To the filter
    factory ``None`` means "not configured" (no constraint) while ``()`` / ``""``
    means "configured empty", and those are not the same filter set — collapsing
    them here would reintroduce the class of bug this field exists to close.

    Lives here rather than in ``_discovery`` because the fast-path cache readers
    must compare it without importing ``_discovery``; and it takes primitive pairs
    rather than a ``DiscoveryConfig`` because ``_primitives`` may not import the
    public ``app`` package (see ``.spec/CONSTITUTION.md`` layer rules).
    """
    parts: list[str] = []
    for name, value in sorted(fields, key=lambda pair: pair[0]):
        parts.append(f"{name}={_normalize_discovery_value(value)}")
    payload = "\n".join(parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _normalize_discovery_value(value: object) -> str:
    """Render one discovery setting as a stable, unambiguous string.

    The ``\x00`` separator and the type tags keep ``("a", "b")`` distinct from
    ``("a,b",)`` and ``None`` distinct from ``()``.
    """
    if value is None:
        return "\x00none"
    if isinstance(value, (list, tuple)):
        return "\x00seq(" + "\x00".join(str(item) for item in value) + ")"
    return f"\x00str({value})"


def _extract_dependencies_section(toml_content: str) -> str | None:
    """Extract the [project.dependencies] section text from pyproject.toml.

    Uses simple line-based parsing to find the dependencies array.
    Returns the raw text of the dependencies section, or None if not found.
    """
    lines = toml_content.splitlines()
    in_project = False
    in_deps = False
    bracket_depth = 0
    deps_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Track when we're in [project] section
        if stripped == "[project]":
            in_project = True
            continue
        elif stripped.startswith("[") and stripped != "[project]" and not in_deps:
            if in_project and not stripped.startswith("[project."):
                in_project = False
            continue

        if not in_project:
            continue

        # Look for dependencies key
        if not in_deps:
            if stripped.startswith("dependencies"):
                in_deps = True
                deps_lines.append(line)
                # Check if it's a single-line definition
                if "[" in stripped and "]" in stripped:
                    return "\n".join(deps_lines)
                bracket_depth = stripped.count("[") - stripped.count("]")
                continue
        else:
            deps_lines.append(line)
            bracket_depth += stripped.count("[") - stripped.count("]")
            if bracket_depth <= 0:
                return "\n".join(deps_lines)

    if deps_lines:
        return "\n".join(deps_lines)

    return None
