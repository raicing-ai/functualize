"""Typed accessors over the freshness ledger. One store, one kind of data.

``FreshStore`` reads and writes **derived** runtime state — fingerprints, run
history, and the session-scoped precondition cache. It sits on
:mod:`functualize._primitives.fresh_format`, which owns that file's format,
locking, and atomic write.

**The façade is gone, and that is `store-substrate`/T3.** Workflow scopes used
to live in this envelope and no longer do: they are a *record* of an in-flight
run, not derived data, and the version-mismatch rule that is correct for a cache
silently erased them. They moved to
:class:`~functualize._primitives.scope_store.ScopeStore`, whose read fails
closed — and this class then forwarded **33 methods** to it so that nothing
outside ``_primitives`` had to change.

That was the right move at the time and the wrong shape to keep. Thirty-three of
forty-four methods delegating to a held collaborator is *middle man*, and the
answer to middle man is to remove it: a caller that wants scope records asks for
a :class:`ScopeStore`. What survives here is what this file is actually about —
fingerprints and the session precondition cache — and the two stores are peers
sharing one substrate rather than one wearing the other.

:attr:`scopes` is kept, because "the scope store beside this one" is a real
question with one right answer. It is a **reference**, not a forwarding layer:
callers reach through it and hold the result.

Both documents live in **one substrate**, handed in at construction. That is
what makes them inseparable: there is no longer a second path to resolve, so
they cannot land in different directories, different modes, or — once a
non-filesystem substrate exists — different backends.

**Write discipline.** Every mutation is a locked read-modify-write, so two
concurrent runs touching *different* keys merge rather than clobber
(last-writer-wins per key, not per file). A walk that makes several scope
mutations for one node takes the lock once with ``ScopeStore.batch``.

**Relationship to ``functualize-state``.** Every section in both files is a flat
``{str: record}`` mapping, which is exactly the shape the plugin's
``StateBackend`` KV protocol addresses (``get``/``set``/``delete``/``keys``).
That correspondence is deliberate so ``functualize-state-sqlite`` can back these
stores later without a record-format change. The backend indirection itself is
not built here — there is no second backend to serve yet, and a swap seam with
one implementation is speculation, not design.

Lives in ``_primitives/`` because both the engine and the CLI (`func history`,
`func builtin state clear`) read it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.fresh_format import (
    FRESH_KEY,
    empty_fresh,
    normalize_fresh,
    stamp_fresh,
)
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import SubstrateUnreadableError

if TYPE_CHECKING:

    from functualize._types.protocols import StoreSubstrate


class FreshStore:
    """Typed read/write access to ``.functualize/fresh.json`` and its sibling.

    Args:
        substrate: Where the documents live. Use :meth:`for_project` to resolve
            it the same way the discovery cache is resolved. The scope store is
            built on the *same* substrate, so a test constructing
            ``FreshStore(JsonFileSubstrate(tmp))`` gets its scopes in ``tmp``
            with no extra wiring and no second path to keep in agreement.
        key: The document name. Defaults to ``"fresh"``; it is a parameter only
            so a caller holding two isolated ledgers in one substrate can say so.
    """

    def __init__(self, substrate: StoreSubstrate, key: str = FRESH_KEY) -> None:
        self._substrate = substrate
        self._key = key
        self._batch: dict[str, Any] | None = None
        self._scopes = ScopeStore(substrate)

    @classmethod
    def for_project(cls, start: Path | str) -> FreshStore:
        """Build a store on the project's resolved substrate."""
        return cls(JsonFileSubstrate.for_project(Path(start)))

    @property
    def substrate(self) -> StoreSubstrate:
        """Where this store's documents live."""
        return self._substrate

    @property
    def scopes(self) -> ScopeStore:
        """The scope store sharing this substrate."""
        return self._scopes

    def describe(self) -> str:
        """Where the freshness ledger lives, for `func builtin data show`."""
        return self._substrate.describe(self._key)

    def is_empty(self) -> bool:
        """Whether anything has ever been stored here."""
        return self._substrate.read(self._key) is None

    # ------------------------------------------------------------------
    # Read / write plumbing
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        """Read the stored envelope, degrading to an empty one.

        Every section here is **derived** — recomputable from the source tree —
        so anything unusable costs one extra run and nothing more. `ScopeStore`
        deliberately does the opposite with the same inputs.
        """
        try:
            stored = self._substrate.read(self._key)
        except SubstrateUnreadableError:
            return empty_fresh()
        return empty_fresh() if stored is None else normalize_fresh(stored.data)

    def _read(self) -> dict[str, Any]:
        """Current state — the open batch if one is active, else storage."""
        if self._batch is not None:
            return self._batch
        return self._load()

    def _mutate(self, mutate: Any) -> None:
        """Apply ``mutate`` to the state, honoring an open batch.

        Outside a batch this is a locked read-modify-write: re-reading inside
        the lock is what lets two concurrent runs touching *different* job keys
        merge instead of clobbering each other.
        """
        if self._batch is not None:
            mutate(self._batch)
            return
        with self._substrate.lock(self._key):
            state = self._load()
            mutate(state)
            self._substrate.write(self._key, stamp_fresh(state))

    def get_fingerprint(self, key: str) -> dict[str, Any] | None:
        """Return the fingerprint record for ``key``, or None."""
        record = self._read()["fingerprints"].get(key)
        return record if isinstance(record, dict) else None

    def put_fingerprint(self, key: str, record: dict[str, Any]) -> None:
        """Store the fingerprint record for ``key``."""

        def _apply(state: dict[str, Any]) -> None:
            state["fingerprints"][key] = record

        self._mutate(_apply)

    def delete_fingerprint(self, key: str) -> None:
        """Remove a fingerprint record (no-op if absent)."""

        def _apply(state: dict[str, Any]) -> None:
            state["fingerprints"].pop(key, None)

        self._mutate(_apply)

    def fingerprint_keys(self, prefix: str = "") -> list[str]:
        """All fingerprint keys, optionally filtered by prefix."""
        return sorted(k for k in self._read()["fingerprints"] if k.startswith(prefix))

    # ------------------------------------------------------------------
    # Scopes — forwarded to the scope store (scopes.json)
    #
    # Signatures are identical to when these lived here, so no caller outside
    # `_primitives` needed editing when the two files split. Reads raise
    # `ScopeStoreUnreadableError` rather than degrading to "no scopes"; that is
    # the whole point of the separation, and callers at a delivery boundary turn
    # it into a refusal.
    # ------------------------------------------------------------------

    def get_precondition(self, key: str) -> bool | None:
        """Cached precondition result for this session, or None if unseen."""
        value = self._read()["session"]["preconditions"].get(key)
        return value if isinstance(value, bool) else None

    def set_precondition(self, key: str, passed: bool) -> None:
        """Cache a precondition result for the session (``docker --version``
        runs once per run, not once per job)."""

        def _apply(state: dict[str, Any]) -> None:
            state["session"]["preconditions"][key] = passed

        self._mutate(_apply)

    def clear_session(self) -> None:
        """Drop the session cache — called at the start of a run session."""

        def _apply(state: dict[str, Any]) -> None:
            state["session"]["preconditions"] = {}

        self._mutate(_apply)

    # ------------------------------------------------------------------
    # Lifecycle (`func builtin state clear`)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Lifecycle (`func builtin data clear`)
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset the freshness ledger. Fingerprints, session cache, nothing else.

        **No ``scopes=`` argument any more.** It used to take one and forward to
        the scope store, which made "clear my state" a single call that
        discarded a run somebody was waiting on — under help text naming only
        "fingerprints, history". The caller now says
        ``store.clear(); store.scopes.clear()`` and has to mean both.

        Never touches the discovery cache — the two have different lifecycles.
        """
        with self._substrate.lock(self._key):
            self._substrate.write(self._key, stamp_fresh(empty_fresh()))
