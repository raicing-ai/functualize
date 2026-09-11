"""Commands typed in the TUI's shell mode — `.functualize/shell-history.json`.

`durable-run-layer`/T3b. These used to share a ring inside `fresh.json` with
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
`fresh.json` holds **only freshness verdicts**, which is what lets it be named
for what it is rather than for the vaguest word available.

**A convenience, and treated as one.** Unlike `scopes.json`, losing this file
costs a user their command recall and nothing else. So it follows
`state_format`'s discard rule rather than `scope_format`'s refuse rule: an
unreadable file reads as empty and is overwritten. That asymmetry is deliberate
and is the same one those two modules already draw between derived data and a
record.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.substrate import substrate_for_project
from functualize._types.errors import SubstrateUnreadableError

if TYPE_CHECKING:
    from functualize._types.protocols import StoreSubstrate

__all__ = [
    "SHELL_HISTORY_KEY",
    "SHELL_HISTORY_LIMIT",
    "ShellHistoryStore",
]

#: The document name this store's entries live under.
#:
#: A key, not a path. It lands beside the other documents because they share
#: one substrate, not because a second upward walk agreed with the first.
SHELL_HISTORY_KEY = "shell-history"

#: Ring bound. Matches the 200 the shared ring used, so a user's recall depth
#: is unchanged by the move — a migration that silently shortens history is a
#: migration that gets noticed for the wrong reason.
SHELL_HISTORY_LIMIT = 200

logger = logging.getLogger(__name__)


class ShellHistoryStore:
    """The commands typed in shell mode, newest last on disk.

    Deliberately small. It has one writer (`_cli/tui/shell_mode.py`) and one
    reader (`func builtin history`), and giving it the full store vocabulary
    would invite it to grow a second purpose.
    """

    __slots__ = ("_key", "_substrate")

    def __init__(self, substrate: StoreSubstrate, key: str = SHELL_HISTORY_KEY) -> None:
        self._substrate = substrate
        self._key = key

    @classmethod
    def for_project(cls, start: Path | str) -> ShellHistoryStore:
        """The store for the project containing ``start``."""
        return cls(substrate_for_project(Path(start)))

    @property
    def substrate(self) -> StoreSubstrate:
        """Where this store's documents live."""
        return self._substrate

    def describe(self) -> str:
        """Where shell history lives, for `func builtin data show`."""
        return self._substrate.describe(self._key)

    def clear(self) -> bool:
        """Forget every recorded command. True if there was anything to forget.

        Deleted rather than moved aside, like the freshness ledger: this is a
        convenience, and nobody is waiting on it.
        """
        with self._substrate.lock(self._key):
            return self._substrate.delete(self._key)

    def _load(self) -> list[dict[str, Any]]:
        """The entries on disk, or `[]`.

        **Degrades to empty rather than refusing.** See the module docstring:
        this is a convenience, and the worst case of a lost file is that a user
        cannot recall what they typed. `scopes.json` refuses because the worst
        case there is an approval spent on a run that no longer exists.
        """
        try:
            stored = self._substrate.read(self._key)
        except SubstrateUnreadableError as exc:
            logger.warning(
                "shell history at %s could not be read (%s); treating as empty",
                self._substrate.describe(self._key),
                exc,
            )
            return []
        if stored is None:
            return []
        entries = stored.data.get("entries")
        if not isinstance(entries, list):
            return []
        return [entry for entry in entries if isinstance(entry, dict)]

    def append(self, record: dict[str, Any]) -> None:
        """Add one command, trimming to :data:`SHELL_HISTORY_LIMIT`.

        Read-modify-write under this document's lock, so two shells in one
        project interleave rather than clobbering each other.
        """
        with self._substrate.lock(self._key):
            entries = self._load()
            entries.append(dict(record))
            if len(entries) > SHELL_HISTORY_LIMIT:
                del entries[: len(entries) - SHELL_HISTORY_LIMIT]
            self._substrate.write(self._key, {"entries": entries})

    def entries(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Commands **newest first**, optionally capped at ``limit``.

        Newest first matches what `get_history` returned, so the CLI's
        rendering is unchanged by the move.
        """
        entries = list(reversed(self._load()))
        return entries[:limit] if limit is not None else entries

    def count(self) -> int:
        """How many commands are recorded."""
        return len(self._load())
