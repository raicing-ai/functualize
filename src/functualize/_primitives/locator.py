"""ResourceLocator — fluent builder for ordered resource location with read/write asymmetry.

Replaces PathResolver and scattered path discovery mechanisms with a single,
composable builder pattern. Supports:

- Multiple read sources with priority ordering
- Separate write targets (read/write asymmetry)
- Standalone mode: writes to XDG cache, reads from CWD → ancestors → XDG cache
- Declared-project mode: reads/writes to <project_root>/.functualize/

Only imports from _types/ and stdlib — zero third-party runtime dependencies.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import platform
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self


@dataclass(frozen=True)
class LocateResult:
    """Result from introspect() — a located resource with provenance information."""

    path: str
    """Absolute path to the located resource."""

    source: str
    """Human-readable label of the source that provided this result."""

    priority: int
    """Priority rank (0 = highest priority source)."""


# Type for candidate-based resolution: either a plain filename (parsed as TOML)
# or a (filename, extractor_callback) tuple where the callback validates/extracts.
Candidate = str | tuple[str, Callable[[Path], dict[str, Any] | None]]


class ResourceLocatorError(Exception):
    """Raised when ResourceLocator encounters an unrecoverable error."""

    pass


@dataclass
class _SearchSource:
    """Internal representation of a configured read source."""

    directory: Path
    label: str
    priority: int
    env_gate: str | None = None


@dataclass
class _UpwardSearch:
    """Internal config for an upward directory traversal."""

    start: Path
    stop: Path | None
    marker: str | None
    label: str
    priority: int
    env_gate: str | None = None


class ResourceLocator:
    """Fluent builder for ordered resource location with read/write asymmetry.

    Example (standalone mode):
        locator = (
            ResourceLocator()
            .search_explicit("./config")
            .search_upward()
            .search_platform_cache(project_id)
            .write_to_platform_cache(project_id)
        )

        # Read: searches config/ → ancestors → XDG cache
        # Write: always to XDG cache
        path = locator.resolve_one("cache.json")
        writable_path = locator.writable("cache.json")
    """

    def __init__(self) -> None:
        self._explicit_sources: list[_SearchSource] = []
        self._upward_searches: list[_UpwardSearch] = []
        self._write_target: Path | None = None
        self._write_label: str = ""
        self._priority_counter: int = 0

    # =========================================================================
    # Builder: read sources (order = priority, first added = highest priority)
    # =========================================================================

    def search_explicit(self, directory: str | Path) -> Self:
        """Add an explicit directory as a read source.

        The directory is resolved to an absolute path. If the directory does
        not exist at resolution time, it is silently skipped during resolve().
        """
        resolved = Path(directory).resolve()
        self._explicit_sources.append(
            _SearchSource(
                directory=resolved,
                label=f"explicit({resolved})",
                priority=self._priority_counter,
            )
        )
        self._priority_counter += 1
        return self

    def search_upward(
        self,
        start: Path | None = None,
        stop: Path | None = None,
        *,
        marker: str | None = None,
    ) -> Self:
        """Add upward directory traversal as a read source.

        Walks from `start` (default: CWD) up to `stop` (default: filesystem root),
        stopping at the first directory containing `marker` (e.g., '.functualize').
        Each ancestor directory is searched for resources.

        Args:
            start: Starting directory for upward search. Defaults to CWD.
            stop: Stop directory (exclusive). Defaults to filesystem root.
            marker: If set, stop at first directory containing this marker entry.
        """
        effective_start = (start or Path.cwd()).resolve()
        self._upward_searches.append(
            _UpwardSearch(
                start=effective_start,
                stop=stop.resolve() if stop else None,
                marker=marker,
                label=f"upward(start={effective_start})",
                priority=self._priority_counter,
            )
        )
        self._priority_counter += 1
        return self

    def search_platform_cache(self, project_id: str) -> Self:
        """Add XDG platform cache as a read source.

        Location: ~/.cache/functualize/<project_id>/
        """
        cache_dir = _xdg_cache_dir() / "functualize" / project_id
        self._explicit_sources.append(
            _SearchSource(
                directory=cache_dir,
                label=f"platform_cache({project_id})",
                priority=self._priority_counter,
            )
        )
        self._priority_counter += 1
        return self

    def search_platform_user(self, app_name: str = "functualize") -> Self:
        """Add XDG user data directory as a read source.

        Location: ~/.local/share/<app_name>/ (or platform equivalent)
        """
        data_dir = _xdg_data_dir() / app_name
        self._explicit_sources.append(
            _SearchSource(
                directory=data_dir,
                label=f"platform_user({app_name})",
                priority=self._priority_counter,
            )
        )
        self._priority_counter += 1
        return self

    def when_env(self, env_var: str) -> Self:
        """Gate the previous read source on an environment variable being set.

        If the environment variable is not set (or empty), the most recently
        added read source is skipped during resolution.
        """
        # Apply env gate to the most recently added source
        if self._upward_searches and (
            not self._explicit_sources
            or self._upward_searches[-1].priority > self._explicit_sources[-1].priority
        ):
            self._upward_searches[-1].env_gate = env_var
        elif self._explicit_sources:
            self._explicit_sources[-1].env_gate = env_var
        return self

    # =========================================================================
    # Builder: write targets
    # =========================================================================

    def write_to_explicit(self, directory: str | Path) -> Self:
        """Set an explicit directory as the write target."""
        self._write_target = Path(directory).resolve()
        self._write_label = f"explicit({self._write_target})"
        return self

    def write_to_platform_cache(self, project_id: str) -> Self:
        """Set XDG platform cache as the write target.

        Location: ~/.cache/functualize/<project_id>/
        """
        self._write_target = _xdg_cache_dir() / "functualize" / project_id
        self._write_label = f"platform_cache({project_id})"
        return self

    # =========================================================================
    # Resolution
    # =========================================================================

    def resolve(self, pattern: str) -> list[str]:
        """Return union of all matches across read sources, deduplicated by absolute path.

        Results are ordered by source priority (first configured source first).
        Uses glob-style pattern matching against filenames within each source directory.

        Args:
            pattern: Glob pattern to match (e.g., "*.toml", "config.*").

        Returns:
            List of absolute paths as strings, deduplicated, priority-ordered.
        """
        seen: set[str] = set()
        results: list[str] = []

        for source_dir, _label, _priority in self._iter_read_directories():
            if not source_dir.is_dir():
                continue
            for entry in sorted(source_dir.iterdir()):
                if fnmatch.fnmatch(entry.name, pattern):
                    abs_path = str(entry.resolve())
                    if abs_path not in seen:
                        seen.add(abs_path)
                        results.append(abs_path)

        return results

    def resolve_one(self, relative_path: str) -> str | None:
        """Return the first match found across read sources (first source wins).

        Args:
            relative_path: Relative path to look for within each source directory.

        Returns:
            Absolute path as string if found, None otherwise.
        """
        for source_dir, _label, _priority in self._iter_read_directories():
            candidate = source_dir / relative_path
            if candidate.exists():
                return str(candidate.resolve())
        return None

    def writable(self, relative_path: str) -> Path:
        """Return the write target path, creating parent directories.

        Args:
            relative_path: Relative path within the write target directory.

        Returns:
            Absolute Path to the writable location.

        Raises:
            ResourceLocatorError: If no write target is configured or if
                parent directory creation fails due to permissions.
        """
        if self._write_target is None:
            raise ResourceLocatorError(
                "No write target configured. "
                "Call write_to_explicit() or write_to_platform_cache() first."
            )

        target = self._write_target / relative_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise ResourceLocatorError(
                f"Failed to create parent directories for '{target}': {e}"
            ) from e
        except OSError as e:
            raise ResourceLocatorError(
                f"Failed to create parent directories for '{target}': {e}"
            ) from e
        return target

    def introspect(self, pattern: str) -> list[LocateResult]:
        """Return all matches with provenance information.

        Like resolve() but includes source labels and priority for diagnostics.

        Args:
            pattern: Glob pattern to match.

        Returns:
            List of LocateResult with path, source label, and priority.
        """
        seen: set[str] = set()
        results: list[LocateResult] = []

        for source_dir, label, priority in self._iter_read_directories():
            if not source_dir.is_dir():
                continue
            for entry in sorted(source_dir.iterdir()):
                if fnmatch.fnmatch(entry.name, pattern):
                    abs_path = str(entry.resolve())
                    if abs_path not in seen:
                        seen.add(abs_path)
                        results.append(
                            LocateResult(
                                path=abs_path,
                                source=label,
                                priority=priority,
                            )
                        )

        return results

    # =========================================================================
    # Candidate-based resolution
    # =========================================================================

    def resolve_first_candidate(
        self, candidates: list[Candidate]
    ) -> tuple[Path, dict[str, Any]] | None:
        """Find the first matching candidate across all read directories.

        Walks directories in priority order. In each directory, tries candidates
        in list order. Returns the first overall match.

        For each candidate:
        - ``str``: checks if the file exists, parses it as TOML.
        - ``tuple[str, callback]``: checks if the file exists, calls the
          callback with the file path. A non-None return is a valid match.

        Args:
            candidates: List of candidates to try per directory.

        Returns:
            Tuple of (directory, parsed_config) for the first match,
            or None if nothing matched anywhere.
        """
        for source_dir, _label, _priority in self._iter_read_directories():
            if not source_dir.is_dir():
                continue
            result = self._try_candidates_in_dir(source_dir, candidates)
            if result is not None:
                return result
        return None

    def resolve_all_candidates(
        self, candidates: list[Candidate]
    ) -> list[tuple[Path, dict[str, Any]]]:
        """Collect one matching candidate per directory across all read directories.

        Walks directories in priority order. In each directory, tries candidates
        in list order and takes the first match. Collects results from all
        directories that have at least one matching candidate.

        Args:
            candidates: List of candidates to try per directory.

        Returns:
            List of (directory, parsed_config) tuples in priority order.
        """
        results: list[tuple[Path, dict[str, Any]]] = []
        seen_dirs: set[Path] = set()

        for source_dir, _label, _priority in self._iter_read_directories():
            if not source_dir.is_dir():
                continue
            resolved_dir = source_dir.resolve()
            if resolved_dir in seen_dirs:
                continue
            result = self._try_candidates_in_dir(source_dir, candidates)
            if result is not None:
                seen_dirs.add(resolved_dir)
                results.append(result)

        return results

    def _try_candidates_in_dir(
        self, directory: Path, candidates: list[Candidate]
    ) -> tuple[Path, dict[str, Any]] | None:
        """Try each candidate in a single directory, return first match."""
        for candidate in candidates:
            if isinstance(candidate, str):
                file_path = directory / candidate
                if file_path.is_file():
                    parsed = self._parse_toml(file_path)
                    if parsed is not None:
                        return (directory, parsed)
            else:
                filename, extractor = candidate
                file_path = directory / filename
                if file_path.is_file():
                    extracted = extractor(file_path)
                    if extracted is not None:
                        return (directory, extracted)
        return None

    @staticmethod
    def _parse_toml(path: Path) -> dict[str, Any] | None:
        """Parse a TOML file, returning None on any error.

        Args:
            path: Path to the TOML file.

        Returns:
            Parsed dict or None if the file cannot be read/parsed.
        """
        try:
            content = path.read_bytes()
            return tomllib.loads(content.decode("utf-8"))
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            return None

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _iter_read_directories(self) -> list[tuple[Path, str, int]]:
        """Yield (directory, label, priority) for all configured read sources in priority order."""
        directories: list[tuple[Path, str, int]] = []

        # Collect explicit sources (respecting env gates)
        for source in self._explicit_sources:
            if source.env_gate and not os.environ.get(source.env_gate):
                continue
            directories.append((source.directory, source.label, source.priority))

        # Collect upward search results (respecting env gates)
        for upward in self._upward_searches:
            if upward.env_gate and not os.environ.get(upward.env_gate):
                continue
            for directory in self._walk_upward(upward):
                directories.append((directory, upward.label, upward.priority))

        # Sort by priority (lower = higher priority)
        directories.sort(key=lambda x: x[2])

        return directories

    def _walk_upward(self, config: _UpwardSearch) -> list[Path]:
        """Walk upward from start to stop/root, respecting marker stops."""
        results: list[Path] = []
        current = config.start

        while True:
            results.append(current)

            # Stop if marker found in this directory
            if config.marker and (current / config.marker).exists():
                break

            # Stop if we've reached the stop directory
            if config.stop and current == config.stop:
                break

            # Stop at filesystem root
            parent = current.parent
            if parent == current:
                break

            current = parent

        return results


# =============================================================================
# Module-level helpers (no functualize.* imports)
# =============================================================================


def _xdg_cache_dir() -> Path:
    """Return XDG-compliant cache directory.

    Respects XDG_CACHE_HOME on Linux/macOS.
    Uses appropriate platform directories on Windows.
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg)

    system = platform.system()
    if system == "Windows":
        # Use LOCALAPPDATA on Windows
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Cache"
        return Path.home() / "AppData" / "Local" / "Cache"

    # Linux, macOS, and other Unix-like
    return Path.home() / ".cache"


def _xdg_data_dir() -> Path:
    """Return XDG-compliant data directory.

    Respects XDG_DATA_HOME on Linux/macOS.
    Uses appropriate platform directories on Windows.
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)

    system = platform.system()
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data)
        return Path.home() / "AppData" / "Local"

    # Linux, macOS, and other Unix-like
    return Path.home() / ".local" / "share"


def compute_project_id(cwd: str | Path) -> str:
    """Compute deterministic project_id from absolute working directory path.

    Returns first 12 characters of the SHA-256 hex digest of the absolute path.
    """
    abs_path = str(Path(cwd).resolve())
    return hashlib.sha256(abs_path.encode()).hexdigest()[:12]
