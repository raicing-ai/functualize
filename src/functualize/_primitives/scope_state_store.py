"""One run's job state, in one file — `.functualize/scope-state/<id>.json`.

`scope-record-lifecycle`/T3. `capability-duality` made a run's state durable by
putting it in the scope record, which was right about durability and wrong
about cost: the state then lived in a **project-wide** file, so writing one key
parsed and rewrote every scope record the project had ever made.

Measured on a 448 KB store holding 2,001 unrelated records: ``set`` **116×**
slower than against an empty one, ``get`` **102×**. On a real project's 1,019 KB
file an external review measured 58 ms per unbatched ``set``
(`.spec/reviews/omp-after-review.md` F1). The cost scaled with *how many runs
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

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from functualize._primitives.fresh_format import atomic_write_json, file_lock

__all__ = ["STATE_DIRNAME", "ScopeStateStore", "scope_state_dir", "scope_state_path"]

#: The directory holding per-scope state files, beside `scopes.json`.
STATE_DIRNAME = "scope-state"


def scope_state_dir(scopes_path: Path | str) -> Path:
    """The state directory for the store whose records live at ``scopes_path``.

    Derived from the scope file rather than resolved independently, for the
    reason `scope_format` gives for deriving its own path from the state file:
    two upward walks can disagree, and a reader must not reconstruct a key the
    writer computed.
    """
    return Path(scopes_path).parent / STATE_DIRNAME


def scope_state_path(scopes_path: Path | str, scope_id: str) -> Path:
    """Where ``scope_id``'s state lives.

    The id is used as the filename. Scope ids are ``<job>-<hex8>`` and job
    names are already constrained to identifier-ish characters, but a plugin
    could mint something else, so separators are rejected rather than escaped:
    a scope id that could name a path outside this directory is a bug at its
    source, and quietly rewriting it would hide that.
    """
    if "/" in scope_id or "\\" in scope_id or scope_id in {"", ".", ".."}:
        raise ValueError(
            f"scope id {scope_id!r} cannot be used as a filename; scope ids "
            f"must not contain path separators"
        )
    return scope_state_dir(scopes_path) / f"{scope_id}.json"


class ScopeStateUnreadableError(RuntimeError):
    """A scope's state file exists but could not be read.

    Deliberately not "degrade to empty". See the module docstring: a record
    that reads as empty when it is really corrupted makes a resumed run start
    over silently, which is the failure the whole durable-state change exists
    to prevent.
    """

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(
            f"Cannot read scope state at {path}: {detail}. The file has been "
            f"left in place; remove it to start this scope's state fresh."
        )
        self.path = path


class ScopeStateStore:
    """Read/write one scope's job state, under the scope file's lock discipline.

    Batching mirrors `ScopeStore.batch`, including its thread-locality: the
    open batch lives in a `threading.local`, because a parallel walk runs items
    on worker threads and a batch opened on one thread must not swallow another
    thread's writes into a payload it will overwrite.
    """

    __slots__ = ("_local", "_path")

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._local = threading.local()

    @property
    def path(self) -> Path:
        """The file this scope's state lives in."""
        return self._path

    @property
    def _batch(self) -> dict[str, Any] | None:
        return getattr(self._local, "batch", None)

    @_batch.setter
    def _batch(self, value: dict[str, Any] | None) -> None:
        self._local.batch = value

    def _load(self) -> dict[str, Any]:
        """The state on disk, or `{}` if this scope has none yet."""
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text())
        except (OSError, ValueError) as exc:
            raise ScopeStateUnreadableError(self._path, str(exc)) from exc
        if not isinstance(raw, dict):
            raise ScopeStateUnreadableError(
                self._path, f"expected an object, found {type(raw).__name__}"
            )
        state = raw.get("state")
        if state is None and "state" not in raw:
            return {}
        if not isinstance(state, dict):
            # Refuses rather than reading as empty. The next write would
            # otherwise replace the file with `{"state": {k: v}}` and drop
            # whatever was really there — the silent-loss shape this module's
            # docstring promises not to have. Found by external review
            # (`.spec/reviews/scope-state-review.md` Q1.6).
            raise ScopeStateUnreadableError(
                self._path,
                f"'state' is {type(state).__name__}, expected an object",
            )
        return state

    def _read(self) -> dict[str, Any]:
        batch = self._batch
        return batch if batch is not None else self._load()

    def _mutate(self, mutate: Any) -> None:
        """Apply ``mutate`` to this scope's state, honoring an open batch."""
        if self._batch is not None:
            mutate(self._batch)
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self._path):
            state = self._load()
            mutate(state)
            atomic_write_json(self._path, {"state": state})

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
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self._path):
            self._batch = self._load()
            try:
                yield self
                atomic_write_json(self._path, {"state": self._batch})
            finally:
                self._batch = None

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
        """Delete this scope's state file. True if there was one.

        Called when a scope record is purged. Ordering is the caller's
        responsibility and it matters: the record goes first. The reverse
        leaves a record pointing at state that is gone, which reads as
        corruption; this order leaves a file nothing references, which reads as
        nothing at all.

        **Takes the lock, and refuses inside a batch.** The first version
        unlinked with no lock at all, which external review
        (`.spec/reviews/scope-state-review.md` Q1.1) showed both ways round: a
        batch committing after the unlink *resurrects* the file, and an unlink
        landing between a `_mutate`'s load and its write is simply *lost*.
        Deleting the file a batch is about to write is incoherent whichever
        wins, so it is an error rather than a race.

        A failed unlink is **not** reported as "there was none" — that made a
        purge which could not delete look like one with nothing to delete.
        """
        if self._batch is not None:
            raise RuntimeError(
                f"cannot discard {self._path} while a batch is open on it; "
                f"the batch would rewrite the file on exit"
            )
        with file_lock(self._path):
            try:
                self._path.unlink()
            except FileNotFoundError:
                return False
        return True


class _Missing:
    """Sentinel for "key was absent", distinct from a stored ``None``."""


_MISSING = _Missing()
