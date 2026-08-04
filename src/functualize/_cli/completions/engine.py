"""SwappableCompleter — strategy pattern for mode-aware autocomplete.

Provides different autocomplete candidates depending on whether the TUI is in
COMMAND mode (delegating to SmartBarAutoComplete) or edit mode (field-specific
choices or path completions).

The same AutoComplete widget stays mounted; only the data source returned by
``get_items()`` changes when mode switches occur.

This module lives in ``_cli/completions/`` and MUST NOT import from ``_cli/tui/``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

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


class CommandCompleterCallback(Protocol):
    """Protocol for command-mode candidate generation callback."""

    def __call__(self, text: str) -> list[object]: ...


class SwappableCompleter:
    """Provides autocomplete candidates based on current mode.

    In COMMAND mode, delegates to a callback (typically the existing
    SmartBarAutoComplete ``get_candidates`` method). In edit mode, returns
    field-specific candidates: filtered enum choices or path completions.
    """

    def __init__(
        self,
        command_callback: CommandCompleterCallback | None = None,
    ) -> None:
        self._mode: str = "command"
        self._field_name: str = ""
        self._choices: list[str] | None = None
        self._is_path: bool = False
        self._command_callback: CommandCompleterCallback | None = command_callback

    @property
    def mode(self) -> str:
        """Current completer mode: ``'command'`` or ``'edit'``."""
        return self._mode

    def set_command_mode(self) -> None:
        """Switch to command/flag/value completions.

        Delegates candidate generation to the existing SmartBarAutoComplete
        engine (via the command_callback). If no callback is configured,
        ``get_items()`` returns an empty list in command mode.
        """
        self._mode = "command"
        self._field_name = ""
        self._choices = None
        self._is_path = False

    def set_edit_mode(
        self,
        field_name: str,
        choices: list[str] | None = None,
        is_path: bool = False,
    ) -> None:
        """Switch to field-specific completions (enum choices, paths).

        Args:
            field_name: The name of the field being edited.
            choices: Optional list of valid enum values for the field.
            is_path: If True, provide filesystem path completions.
        """
        self._mode = "edit"
        self._field_name = field_name
        self._choices = choices
        self._is_path = is_path

    def get_items(self, text: str) -> list[DropdownItem]:
        """Return candidates for current text and mode.

        In command mode, delegates to the command callback.
        In edit mode with choices, filters by case-insensitive prefix (max 50).
        In edit mode with is_path=True, scans filesystem (max 20).
        Returns empty list when no match or no choices configured.
        """
        if self._mode == "command":
            return self._command_candidates(text)
        return self._edit_candidates(text)

    # ─── Private helpers ─────────────────────────────────────────────────

    def _command_candidates(self, text: str) -> list[DropdownItem]:
        """Delegate to the command callback for COMMAND mode candidates."""
        if self._command_callback is None:
            return []
        results = self._command_callback(text)
        # Wrap raw results into DropdownItem if they aren't already
        items: list[DropdownItem] = []
        for item in results:
            if isinstance(item, DropdownItem):
                items.append(item)
            elif hasattr(item, "main"):
                # Compatible object (e.g. textual_autocomplete.DropdownItem)
                main_val = item.main
                # Handle Content/Text objects — extract plain text
                if hasattr(main_val, "plain"):
                    main_val = main_val.plain
                items.append(DropdownItem(main=str(main_val)))
            else:
                items.append(DropdownItem(main=str(item)))
        return items

    def _edit_candidates(self, text: str) -> list[DropdownItem]:
        """Generate candidates for edit mode (choices or paths)."""
        if self._is_path:
            return self._path_candidates(text)

        if not self._choices:
            return []

        return self._choice_candidates(text)

    def _choice_candidates(self, text: str) -> list[DropdownItem]:
        """Filter choices by case-insensitive prefix match, max 50."""
        if not self._choices:
            return []

        prefix = text.lower()
        candidates: list[DropdownItem] = []

        for choice in self._choices:
            if prefix and not choice.lower().startswith(prefix):
                continue
            candidates.append(DropdownItem(main=choice))
            if len(candidates) >= _MAX_CHOICES_CANDIDATES:
                break

        return candidates

    def _path_candidates(self, text: str) -> list[DropdownItem]:
        """Scan filesystem for path completion candidates, max 20.

        Thin wrapper over the module-level :func:`path_candidates`, which the
        ``!`` shell mode needs too. Kept as a method so this class's existing
        callers and tests are untouched.
        """
        return path_candidates(text)


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
