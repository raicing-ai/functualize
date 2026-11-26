"""Filesystem and executable candidates for shell completion.

This module lives in ``_cli/completions/`` and MUST NOT import from ``_cli/tui/``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_MAX_CHOICES_CANDIDATES = 50
_MAX_PATH_CANDIDATES = 20


class DropdownItem:
    """Lightweight autocomplete candidate.

    Compatible with the interface expected by the existing autocomplete
    widget. At runtime the real ``textual_autocomplete.DropdownItem`` is
    used; this class provides a test-friendly stand-in and structural
    contract.
    """

    __slots__ = ("main", "prefix", "description")

    def __init__(self, main: str, prefix: str = "", description: str = "") -> None:
        self.main = main
        self.prefix = prefix
        self.description = description

    def __repr__(self) -> str:
        return f"DropdownItem(main={self.main!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DropdownItem):
            return self.main == other.main
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.main)


def path_candidates(text: str) -> list[DropdownItem]:
    """Filesystem candidates for ``text``, max 20.

    Uses the parent directory of the input text and filters entries by prefix
    of the final path segment.
    """
    candidates: list[DropdownItem] = []

    try:
        if not text:
            base_dir = Path(".")
            prefix = ""
        else:
            input_path = Path(text)
            if text.endswith("/") or text.endswith("\\"):
                # User typed a trailing slash — list contents of that dir
                base_dir = input_path
                prefix = ""
            elif input_path.is_dir():
                # Input is a complete directory name without trailing slash
                base_dir = input_path
                prefix = ""
            else:
                # Partial filename — scan parent, filter by last segment
                base_dir = input_path.parent
                prefix = input_path.name.lower()

        if not base_dir.exists() or not base_dir.is_dir():
            return []

        for entry in sorted(base_dir.iterdir()):
            name = entry.name
            if prefix and not name.lower().startswith(prefix):
                continue

            # Build display path relative to what the user typed
            display = str(base_dir / name)
            if entry.is_dir():
                display += "/"

            candidates.append(DropdownItem(main=display))
            if len(candidates) >= _MAX_PATH_CANDIDATES:
                break

    except (PermissionError, OSError):
        pass

    return candidates


def executable_candidates(prefix: str) -> list[DropdownItem]:
    """Executables on ``$PATH`` starting with ``prefix``, max 50.

    The scan is **cached for the process** (:func:`_scan_path_executables`).
    Enumerating every ``$PATH`` directory on each keystroke is the one thing in
    the completion path expensive enough to tempt someone into a background
    worker — and a worker here would need cancelling on every mode swap, with
    late candidates painting into whatever widget won the race. Caching keeps
    the whole completion path synchronous, which is the property the rest of
    this module already relies on. The cost is that an executable installed
    mid-session is not offered until restart; completion is a convenience and
    the command still runs if typed in full.
    """
    lowered = prefix.lower()
    return [
        DropdownItem(main=name)
        for name in _scan_path_executables()
        if name.lower().startswith(lowered)
    ][:_MAX_CHOICES_CANDIDATES]


@lru_cache(maxsize=1)
def _scan_path_executables() -> tuple[str, ...]:
    """Sorted, de-duplicated executable names on ``$PATH``."""
    names: set[str] = set()
    for raw in os.environ.get("PATH", "").split(os.pathsep):
        if not raw:
            continue
        try:
            with os.scandir(raw) as entries:
                for entry in entries:
                    if entry.is_file() and os.access(entry.path, os.X_OK):
                        names.add(entry.name)
        except (PermissionError, OSError):
            # A missing or unreadable $PATH entry is ordinary, not an error.
            continue
    return tuple(sorted(names))
