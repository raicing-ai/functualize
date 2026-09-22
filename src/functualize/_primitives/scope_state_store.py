"""One run's job state, in one file — `.functualize/scope-state/<id>.json`.

`scope-record-lifecycle`/T3. `capability-duality` made a run's state durable by
putting it in the scope record, which was right about durability and wrong
about cost: the state then lived in a **project-wide** file, so writing one key
parsed and rewrote every scope record the project had ever made.

Measured on a 448 KB store holding 2,001 unrelated records: ``set`` **116×**
slower than against an empty one, ``get`` **102×**. On a real project's 1,019 KB
file an external review measured 58 ms per unbatched ``set``
An external review measured the same cost. The cost scaled with *how many runs
the project had ever done* — nothing to do with what the job stored.

**A per-run value belongs in a per-run file.** After this, a `set` touches one
file holding one run's state, so the cost is what the job stored and a project
with 2,000 past runs measures like an empty one.

The second effect is worth as much as the first and was not the reason for the
change: **unrelated runs stop contending.** One file means one `fcntl.flock`
sidecar, so two jobs sharing nothing serialized on every write. Per-scope files
give each run its own lock.

What did *not* change is the durability rule this file inherits from
`scope_format`: a record is not a cache. A missing file reads as "no state" —
that is the absence of a run, not a lost one — but a file that exists and
cannot be parsed **refuses** rather than degrading to empty, because silently
reading a corrupted state file as empty is how a resumed run starts over
without saying so.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from functualize._types.errors import SubstrateUnreadableError

if TYPE_CHECKING:
    from functualize._types.protocols import Revision, StoreSubstrate

__all__ = ["STATE_DIRNAME", "ScopeStateStore", "scope_state_key"]

#: The directory holding per-scope state files, beside `scopes.json`.
STATE_DIRNAME = "scope-state"
_WRITE_ATTEMPTS = 8


def scope_state_key(scope_id: str) -> str:
    """The document name ``scope_id``'s state is stored under.

    A key, not a path. Under `JsonFileSubstrate` it becomes
    ``scope-state/<id>.json`` beside the records, which is where these files
    have always been; another substrate may make it anything.

    The id is used verbatim, so separators are rejected rather than escaped: a
    scope id that could name a document outside this namespace is a bug at its
    source, and quietly rewriting it would hide that. Scope ids are
    ``<job>-<hex8>`` and job names are already constrained, but a plugin could
    mint something else.
    """
    if "/" in scope_id or "\\" in scope_id or scope_id in {"", ".", ".."}:
        raise ValueError(
            f"scope id {scope_id!r} cannot be used as a document name; scope "
            f"ids must not contain path separators"
        )
    return f"{STATE_DIRNAME}/{scope_id}"


class ScopeStateUnreadableError(RuntimeError):
    """A scope's state file exists but could not be read.

    Deliberately not "degrade to empty". See the module docstring: a record
    that reads as empty when it is really corrupted makes a resumed run start
    over silently, which is the failure the whole durable-state change exists
    to prevent.
    """

    def __init__(self, where: str, detail: str) -> None:
        super().__init__(
            f"Cannot read scope state at {where}: {detail}. It has been left "
            f"in place; remove it to start this scope's state fresh."
        )
        self.where = where


class ScopeStateStore:
    """Read/write one scope's job state, under the scope file's lock discipline.

    Batching mirrors `ScopeStore.batch`, including its thread-locality: the
    open batch lives in a `threading.local`, because a parallel walk runs items
    on worker threads and a batch opened on one thread must not swallow another
    thread's writes into a payload it will overwrite.
    """

    __slots__ = ("_key", "_local", "_substrate")

    def __init__(self, substrate: StoreSubstrate, scope_id: str) -> None:
        self._substrate = substrate
        self._key = scope_state_key(scope_id)
        self._local = threading.local()

    @property
    def key(self) -> str:
        """The document name this scope's state lives under."""
        return self._key

    @property
    def _batch(self) -> dict[str, Any] | None:
        return getattr(self._local, "batch", None)

    @_batch.setter
    def _batch(self, value: dict[str, Any] | None) -> None:
        self._local.batch = value

    @property
    def _batch_mutations(self) -> list[Any] | None:
        return getattr(self._local, "batch_mutations", None)

    @_batch_mutations.setter
    def _batch_mutations(self, value: list[Any] | None) -> None:
        self._local.batch_mutations = value

    def _load(self) -> dict[str, Any]:
        """This scope's stored state, or `{}` if it has none yet."""
        state, _ = self._load_with_revision()
        return state

    def _load_with_revision(self) -> tuple[dict[str, Any], Revision | None]:
        """This scope's state and the revision read with it."""
        try:
            stored = self._substrate.read(self._key)
        except SubstrateUnreadableError as exc:
            raise ScopeStateUnreadableError(self._key, str(exc)) from exc
        if stored is None:
            return {}, None
        raw = stored.data
        state = raw.get("state")
        if state is None and "state" not in raw:
            return {}, stored.revision
        if not isinstance(state, dict):
            # Refuses rather than reading as empty. The next write would
            # otherwise replace the file with `{"state": {k: v}}` and drop
            # whatever was really there — the silent-loss shape this module's
            # docstring promises not to have. Found by external review
            # (as identified by the external scope-state review).
            raise ScopeStateUnreadableError(
                self._key,
                f"'state' is {type(state).__name__}, expected an object",
            )
        return state, stored.revision

    def _read(self) -> dict[str, Any]:
        batch = self._batch
        return batch if batch is not None else self._load()

    def _mutate(self, mutate: Any) -> None:
        """Apply ``mutate`` to this scope's state, honoring an open batch."""
        if self._batch is not None:
            mutate(self._batch)
            mutations = self._batch_mutations
            assert mutations is not None
            mutations.append(mutate)
            return
        for _ in range(_WRITE_ATTEMPTS):
            with self._substrate.lock(self._key):
                state, revision = self._load_with_revision()
                mutate(state)
                if self._substrate.write(self._key, {"state": state}, expect=revision):
                    return
        raise RuntimeError(
            f"could not write {self._key!r} after {_WRITE_ATTEMPTS} attempts; "
            f"another writer is winning every round"
        )

    @contextmanager
    def batch(self) -> Iterator[ScopeStateStore]:
        """Hold the lock for many writes, writing once at the end.

        Writes on clean exit only, as `ScopeStore.batch` does: an exception
        inside the block discards the block's mutations rather than persisting
        some of them.
        """
        if self._batch is not None:  # already batching — reuse the outer one
            yield self
            return
        with self._substrate.lock(self._key):
            self._batch, revision = self._load_with_revision()
            self._batch_mutations = []
            try:
                yield self
                for _ in range(_WRITE_ATTEMPTS):
                    if self._substrate.write(
                        self._key, {"state": self._batch}, expect=revision
                    ):
                        break
                    self._batch, revision = self._load_with_revision()
                    for mutate in self._batch_mutations:
                        mutate(self._batch)
                else:
                    raise RuntimeError(
                        f"could not write {self._key!r} after "
                        f"{_WRITE_ATTEMPTS} attempts; another writer is winning "
                        "every round"
                    )
            finally:
                self._batch = None
                self._batch_mutations = None

    def get(self, key: str, default: Any = None) -> Any:
        return self._read().get(key, default)

    def set(self, key: str, value: Any) -> None:
        def _apply(state: dict[str, Any]) -> None:
            state[key] = value

        self._mutate(_apply)

    def delete(self, key: str) -> bool:
        removed = False

        def _apply(state: dict[str, Any]) -> None:
            nonlocal removed
            removed = state.pop(key, _MISSING) is not _MISSING

        self._mutate(_apply)
        return removed

    def snapshot(self) -> dict[str, Any]:
        """A copy of every key this scope holds."""
        return dict(self._read())

    def clear(self) -> None:
        def _apply(state: dict[str, Any]) -> None:
            state.clear()

        self._mutate(_apply)

    def discard(self) -> bool:
        """Delete this scope's stored state. True if there was one.

        Called when a scope record is purged. Ordering is the caller's
        responsibility and it matters: the record goes first. The reverse
        leaves a record pointing at state that is gone, which reads as
        corruption; this order leaves a file nothing references, which reads as
        nothing at all.

        **Takes the lock, and refuses inside a batch.** The first version
        unlinked with no lock at all, which external review
        An external review showed both ways round: a
        batch committing after the unlink *resurrects* the file, and an unlink
        landing between a `_mutate`'s load and its write is simply *lost*.
        Deleting the file a batch is about to write is incoherent whichever
        wins, so it is an error rather than a race.

        A failed unlink is **not** reported as "there was none" — that made a
        purge which could not delete look like one with nothing to delete.
        """
        if self._batch is not None:
            raise RuntimeError(
                f"cannot discard {self._key} while a batch is open on it; "
                f"the batch would rewrite it on exit"
            )
        with self._substrate.lock(self._key):
            return self._substrate.delete(self._key)


class _Missing:
    """Sentinel for "key was absent", distinct from a stored ``None``."""


_MISSING = _Missing()
