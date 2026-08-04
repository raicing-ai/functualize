"""Path suggestion scanner for TUI completion.

Scans filesystem for path completions based on partial input.
Shared between Config Table inline edit and SmartBar value completions.
Supports relative (./ or bare word), absolute (/), and home-relative (~/) modes.
Debounces rescans by 100ms. Returns up to 20 suggestions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from functualize._cli.data.path_suggestion import PathSuggestion

_MAX_SUGGESTIONS = 20
_DEBOUNCE_MS = 100


@dataclass
class PathSuggestionScanner:
    """Scans filesystem for path completions.

    Supports relative (./), absolute (/), and home-relative (~/) modes.
    Debounces rescans by 100ms. Returns up to 20 suggestions.
    Handles permission errors gracefully by skipping unreadable directories.
    """

    _last_scan_time: float = field(default=0.0, init=False)
    _last_results: list[PathSuggestion] = field(default_factory=list, init=False)
    _last_partial: str = field(default="", init=False)

    def scan(
        self,
        partial: str,
        cwd: Path,
        path_mode: str | None = None,
        file_filter: str | None = None,
    ) -> list[PathSuggestion]:
        """Return up to 20 path suggestions matching the partial.

        Args:
            partial: The partially-typed path string.
            cwd: Current working directory for relative path resolution.
            path_mode: Force "relative" or "absolute" mode, or None for auto-detect.
            file_filter: "file" for files only, "directory" for dirs only, None for both.

        Returns:
            Up to 20 PathSuggestion items sorted alphabetically (dirs first).
        """
        now = time.monotonic() * 1000
        if now - self._last_scan_time < _DEBOUNCE_MS and partial == self._last_partial:
            return self._last_results

        self._last_scan_time = now
        self._last_partial = partial

        base_path, prefix = self._resolve_base(partial, cwd, path_mode)
        suggestions = self._scan_directory(base_path, prefix, file_filter, cwd, partial)

        self._last_results = suggestions[:_MAX_SUGGESTIONS]
        return self._last_results

    def _resolve_base(
        self, partial: str, cwd: Path, path_mode: str | None
    ) -> tuple[Path, str]:
        """Resolve the base directory and remaining prefix from partial input.

        Returns:
            A tuple of (base_directory, name_prefix) where base_directory is
            the directory to scan and name_prefix is the filter for entry names.
        """
        if not partial:
            return cwd, ""

        # Home-relative mode: ~/...
        if partial.startswith("~/"):
            expanded = Path.home() / partial[2:]
            if expanded.is_dir() and partial.endswith("/"):
                return expanded, ""
            return expanded.parent, expanded.name

        # Absolute mode: /...
        if partial.startswith("/"):
            p = Path(partial)
            if p.is_dir() and partial.endswith("/"):
                return p, ""
            return p.parent, p.name

        # Relative mode: ./ prefix or bare word
        rel = partial[2:] if partial.startswith("./") else partial

        p = cwd / rel
        if p.is_dir() and partial.endswith("/"):
            return p, ""
        return p.parent, p.name

    def _scan_directory(
        self,
        base_path: Path,
        prefix: str,
        file_filter: str | None,
        cwd: Path,
        partial: str,
    ) -> list[PathSuggestion]:
        """Scan a directory for matching entries.

        Entries are sorted with directories first, then alphabetically by name.
        Permission errors are handled gracefully (skip unreadable directories).
        """
        suggestions: list[PathSuggestion] = []

        try:
            if not base_path.is_dir():
                return []

            entries = sorted(
                base_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )

            for entry in entries:
                if len(suggestions) >= _MAX_SUGGESTIONS:
                    break

                # Filter by prefix (case-insensitive)
                if prefix and not entry.name.lower().startswith(prefix.lower()):
                    continue

                # Filter by file type
                is_dir = entry.is_dir()
                if file_filter == "file" and is_dir:
                    continue
                if file_filter == "directory" and not is_dir:
                    continue

                display = self._format_display(entry, cwd, partial)

                suggestions.append(
                    PathSuggestion(
                        path=entry,
                        is_directory=is_dir,
                        display=display,
                    )
                )
        except PermissionError:
            pass  # Skip unreadable directories gracefully
        except OSError:
            pass  # Handle other OS errors gracefully

        return suggestions

    def _format_display(self, path: Path, cwd: Path, partial: str) -> str:
        """Format a path for display.

        Uses relative display when the path is under cwd, otherwise absolute.
        Appends "/" suffix for directories.
        """
        if partial.startswith("~/"):
            # Display relative to home
            try:
                rel = path.relative_to(Path.home())
                display = "~/" + str(rel)
            except ValueError:
                display = str(path)
        elif partial.startswith("/"):
            # Display as absolute
            display = str(path)
        else:
            # Display relative to cwd
            try:
                rel = path.relative_to(cwd)
                display = "./" + str(rel)
            except ValueError:
                display = str(path)

        if path.is_dir():
            display += "/"

        return display
