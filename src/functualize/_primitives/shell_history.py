"""Commands typed in the TUI's shell mode — `.functualize/shell-history.json`.

`durable-run-layer`/T3b. These used to share a ring inside `state.json` with
job-run history, under a `namespace` discriminator. That was the right home
while both were "things the user did"; it stopped being right once the run log
existed, because the two halves went in opposite directions:

* **job history** is a strict subset of `runs.json`, which records the same runs
  plus the nested ones plus who invoked them. Keeping a second, poorer copy is
  the drift these projections exist to end — so it is derived now, not stored.
* **shell history** has no counterpart anywhere. `git status` typed into shell
  mode was never a run: it has no job, no scope, no args hash. The run log has
  nowhere to put it, and putting it there would oblige every run consumer to
  filter out the things that are not runs — a rule everyone must remember,
  which is the kind that gets forgotten once and then ships.

So it gets its own file. The gain is not tidiness: with `history` gone,
`state.json` holds **only freshness verdicts**, which is what lets it be named
for what it is rather than for the vaguest word available.

**A convenience, and treated as one.** Unlike `scopes.json`, losing this file
costs a user their command recall and nothing else. So it follows
`state_format`'s discard rule rather than `scope_format`'s refuse rule: an
unreadable file reads as empty and is overwritten. That asymmetry is deliberate
and is the same one those two modules already draw between derived data and a
record.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from functualize._primitives.state_format import (
    atomic_write_json,
    resolve_state_location,
    state_lock,
)

__all__ = [
    "SHELL_HISTORY_FILENAME",
    "SHELL_HISTORY_LIMIT",
    "ShellHistoryStore",
    "resolve_shell_history_path",
]

#: Beside the other stores, in the directory the upward walk resolved.
SHELL_HISTORY_FILENAME = "shell-history.json"

#: Ring bound. Matches the 200 the shared ring used, so a user's recall depth
#: is unchanged by the move — a migration that silently shortens history is a
#: migration that gets noticed for the wrong reason.
SHELL_HISTORY_LIMIT = 200

logger = logging.getLogger(__name__)


def resolve_shell_history_path(start: Path | str) -> Path:
    """Where shell history lives — always the state file's sibling.

    Derived from `resolve_state_location` rather than repeating its upward
    walk, for the reason `scope_format` gives for doing the same: two walks can
    disagree about which project or which mode they are in, and a reader must
    not reconstruct a key the writer computed.
    """
    return resolve_state_location(Path(start))[0].with_name(SHELL_HISTORY_FILENAME)


class ShellHistoryStore:
    """The commands typed in shell mode, newest last on disk.

    Deliberately small. It has one writer (`_cli/tui/shell_mode.py`) and one
    reader (`func builtin history`), and giving it the full store vocabulary
    would invite it to grow a second purpose.
    """

    __slots__ = ("_path",)

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @classmethod
    def for_project(cls, start: Path | str) -> ShellHistoryStore:
        """The store for the project containing ``start``."""
        return cls(resolve_shell_history_path(start))

    @classmethod
    def beside_state(cls, state_path: Path | str) -> ShellHistoryStore:
        """The store that sits beside an already-resolved state file."""
        return cls(Path(state_path).with_name(SHELL_HISTORY_FILENAME))

    @property
    def path(self) -> Path:
        """The file this store reads and writes."""
        return self._path

    def _load(self) -> list[dict[str, Any]]:
        """The entries on disk, or `[]`.

        **Degrades to empty rather than refusing.** See the module docstring:
        this is a convenience, and the worst case of a lost file is that a user
        cannot recall what they typed. `scopes.json` refuses because the worst
        case there is an approval spent on a run that no longer exists.
        """
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text())
        except (OSError, ValueError) as exc:
            logger.warning(
                "shell history at %s could not be read (%s); treating as empty",
                self._path,
                exc,
            )
            return []
        entries = raw.get("entries") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            return []
        return [entry for entry in entries if isinstance(entry, dict)]

    def append(self, record: dict[str, Any]) -> None:
        """Add one command, trimming to :data:`SHELL_HISTORY_LIMIT`.

        Read-modify-write under the file's own lock, so two shells in one
        project interleave rather than clobbering each other.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with state_lock(self._path):
            entries = self._load()
            entries.append(dict(record))
            if len(entries) > SHELL_HISTORY_LIMIT:
                del entries[: len(entries) - SHELL_HISTORY_LIMIT]
            atomic_write_json(self._path, {"entries": entries})

    def entries(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Commands **newest first**, optionally capped at ``limit``.

        Newest first matches what `get_history` returned, so the CLI's
        rendering is unchanged by the move.
        """
        entries = list(reversed(self._load()))
        return entries[:limit] if limit is not None else entries
