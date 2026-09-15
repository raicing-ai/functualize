"""An in-memory `StoreSubstrate` — the whole of "bring your own storage".

Six methods, no framework knowledge. A substrate is asked for a **document** by
key and told to put one back; it is never asked what a scope is, what a step
record looks like, or which file degrades to empty when it cannot be read. Those
are decisions about *meaning* and they stay on the stores.

`contributor/adr/022` is why this is the seam rather than a key-value
`StateBackend`: a backend-agnostic key-value protocol can only offer the
intersection of every backend, which is worth least exactly where having a real
database is worth most. This example used to implement that protocol, and was
ported when the protocol was retired.

Everything here lives in a dict, so it is gone when the process is. That is the
point of the example — the *shape* is what transfers, and it is the same shape
`functualize-state-sqlite` fills with a database.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from copy import deepcopy
from typing import TYPE_CHECKING, Any

# `_types.protocols`, which is where `functualize-state-sqlite` imports it from
# too. `Stored` has no public re-export yet — a real gap in the substrate port,
# recorded rather than worked around here, because an example that reached for
# it differently from the shipped plugin would teach the wrong thing.
from functualize._types.protocols import Stored

if TYPE_CHECKING:
    from collections.abc import Iterator


class MemorySubstrate:
    """Keeps every document in a dict, with a lock and a revision counter.

    Satisfies `StoreSubstrate`: ``read``, ``write``, ``lock``, ``clear``,
    ``delete`` and ``describe``.
    """

    def __init__(self) -> None:
        self._documents: dict[str, dict[str, Any]] = {}
        self._revisions: dict[str, int] = {}
        # Re-entrant, because `lock` is asked for several keys at once and a
        # store may already hold it — the same reason the filesystem substrate
        # takes one lock for the whole batch rather than one per document.
        self._lock = threading.RLock()

    # -- the port ------------------------------------------------------

    def read(self, key: str) -> Stored | None:
        """The document at ``key``, or None if nothing was ever written there.

        None and an empty document are different answers, and the stores rely
        on it: a missing `scopes` reads as "no scopes", an unreadable one
        refuses. Copied on the way out so a caller mutating what it read cannot
        change what is stored.
        """
        with self._lock:
            document = self._documents.get(key)
            if document is None:
                return None
            return Stored(data=deepcopy(document), revision=self._revisions[key])

    def write(
        self, key: str, payload: dict[str, Any], *, expect: int | None = None
    ) -> bool:
        """Replace the document at ``key``. False when ``expect`` did not match.

        The compare-and-swap half of the port. A filesystem gets exclusion from
        `flock` and can ignore `expect`; a substrate that cannot lock — a remote
        object store — relies on this instead, so it is here from the start.
        """
        with self._lock:
            current = self._revisions.get(key, 0)
            if expect is not None and expect != current:
                return False
            self._documents[key] = deepcopy(payload)
            self._revisions[key] = current + 1
            return True

    @contextmanager
    def lock(self, *keys: str) -> Iterator[None]:
        """Hold every named document for the duration.

        One lock for all of them rather than one each: taking several in turn
        is how two writers deadlock, and the keys are named here so a substrate
        that *can* lock per document still has what it needs.
        """
        with self._lock:
            yield

    def clear(self, key: str) -> str | None:
        """Discard the document at ``key``, returning where it went.

        `func builtin data clear` — the documented way out of a document that
        cannot be read. None when there was nothing to clear. A filesystem
        substrate renames the file aside and returns the new path; there is
        nowhere to put one here, so the answer is a description.
        """
        with self._lock:
            if key not in self._documents:
                return None
            del self._documents[key]
            self._revisions.pop(key, None)
            return f"discarded (in memory, {key!r})"

    def delete(self, key: str) -> bool:
        """Remove the document at ``key``. True if there was one.

        The scope purge, which must **not** keep a copy — the difference
        between this and `clear`.
        """
        with self._lock:
            self._revisions.pop(key, None)
            return self._documents.pop(key, None) is not None

    def describe(self, key: str) -> str:
        """Where this document lives, for `func builtin data show`.

        A person asking where their data is deserves an answer even when the
        answer is "nowhere it will survive a restart".
        """
        return f"in memory (process-local), key {key!r}"

    # -- for the example's tests ---------------------------------------

    @property
    def size(self) -> int:
        """How many documents are stored."""
        with self._lock:
            return len(self._documents)
