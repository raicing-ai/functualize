"""Typed accessors over the runtime state envelope, and the façade over both stores.

``StateStore`` reads and writes **derived** runtime state — fingerprints, run
history, and the session-scoped precondition cache. It sits on
:mod:`functualize._primitives.state_format`, which owns that file's format,
locking, and atomic write.

**Two files, one façade.** Workflow scopes used to live in this envelope and no
longer do: they are a *record* of an in-flight run, not derived data, and the
version-mismatch rule that is correct for a cache silently erased them. They now
live in ``scopes.json`` behind :class:`~functualize._primitives.scope_store.ScopeStore`,
whose read fails closed. ``StateStore`` owns one and forwards every scope method
to it, so **which file a section lives in is not a caller's concern** — nothing
outside ``_primitives`` changed when they split.

The scope file is always this file's sibling, derived via
``ScopeStore.beside_state``. One upward walk decides both, so the two can never
land in different directories or different modes.

**Write discipline.** Every mutation is a locked read-modify-write, so two
concurrent runs touching *different* keys merge rather than clobber
(last-writer-wins per key, not per file). A walk that makes several scope
mutations for one node takes the lock once with :meth:`StateStore.scope_batch`.

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

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.state_format import (
    HISTORY_LIMIT,
    empty_state,
    load_state,
    resolve_state_path,
    save_state,
    state_lock,
    update_state,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class StateStore:
    """Typed read/write access to ``.functualize/state.json`` and its sibling.

    Args:
        path: The state file. Use :meth:`for_project` to resolve it the same
            way the discovery cache is resolved. The scope file is derived from
            it, so a test constructing ``StateStore(tmp / "state.json")`` gets
            ``tmp / "scopes.json"`` with no extra wiring.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._batch: dict[str, Any] | None = None
        self._scopes = ScopeStore.beside_state(self._path)

    @classmethod
    def for_project(cls, start: Path | str) -> StateStore:
        """Build a store at the project's resolved state path."""
        return cls(resolve_state_path(Path(start)))

    @property
    def path(self) -> Path:
        """The state file this store reads and writes."""
        return self._path

    @property
    def scopes_path(self) -> Path:
        """The scope file beside it."""
        return self._scopes.path

    # ------------------------------------------------------------------
    # Read / write plumbing
    # ------------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        """Current state — the open batch if one is active, else the file."""
        if self._batch is not None:
            return self._batch
        return load_state(self._path)

    def _mutate(self, mutate: Any) -> None:
        """Apply ``mutate`` to the state, honoring an open batch."""
        if self._batch is not None:
            mutate(self._batch)
            return
        update_state(self._path, mutate)

    @contextmanager
    def scope_batch(self) -> Iterator[StateStore]:
        """Hold the scope-file lock for many mutations, writing once at the end.

        Without this, a walk that records a step, sets the position and sets the
        status does three locked read-modify-writes of the whole scope file for
        one node.

        Scoped to the scope store deliberately. There is no ``batch()`` for the
        derived store: nothing in ``src/`` or ``plugins/`` ever called the one
        that used to exist, while the module docstring instructed callers to use
        it. A mechanism nothing calls is worse than no mechanism, because it
        reads as a solved problem.
        """
        with self._scopes.batch():
            yield self

    # ------------------------------------------------------------------
    # Fingerprints
    # ------------------------------------------------------------------

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

    def get_scope(self, scope_id: str) -> dict[str, Any] | None:
        """Return the scope record, or None if the scope is unknown."""
        return self._scopes.get_scope(scope_id)

    def ensure_scope(self, scope_id: str, workflow: str | None = None) -> None:
        """Create the scope record if absent (idempotent)."""
        self._scopes.ensure_scope(scope_id, workflow)

    def set_scope_status(self, scope_id: str, status: str) -> None:
        """Set a scope's status (running/blocked/completed/failed/cancelled)."""
        self._scopes.set_scope_status(scope_id, status)

    def record_step(self, scope_id: str, step_key: str, record: dict[str, Any]) -> None:
        """Record a per-scope step result, keyed ``<job_name>::<args_hash>``."""
        self._scopes.record_step(scope_id, step_key, record)

    def get_step(self, scope_id: str, step_key: str) -> dict[str, Any] | None:
        """Return a recorded step result for this scope, or None."""
        return self._scopes.get_step(scope_id, step_key)

    def record_branch(self, scope_id: str, source: str, target: str) -> None:
        """Record a chosen ``ConditionalEdge`` target on first evaluation."""
        self._scopes.record_branch(scope_id, source, target)

    def get_branch(self, scope_id: str, source: str) -> str | None:
        """Return the branch target recorded for ``source``, or None."""
        return self._scopes.get_branch(scope_id, source)

    def put_gate(self, scope_id: str, gate_name: str, record: dict[str, Any]) -> None:
        """Persist a blocked gate: model name, input schema, payload."""
        self._scopes.put_gate(scope_id, gate_name, record)

    def get_gate(self, scope_id: str, gate_name: str) -> dict[str, Any] | None:
        """Return a persisted gate record, or None."""
        return self._scopes.get_gate(scope_id, gate_name)

    def deposit_gate_payload(self, scope_id: str, gate_name: str, payload: Any) -> bool:
        """Deposit resolved input for a blocked gate. False if no such gate."""
        return self._scopes.deposit_gate_payload(scope_id, gate_name, payload)

    def set_position(self, scope_id: str, node: str | None) -> None:
        """Persist the blocked-walk position so a walk survives."""
        self._scopes.set_position(scope_id, node)

    def get_position(self, scope_id: str) -> str | None:
        """Return the persisted walk position, or None."""
        return self._scopes.get_position(scope_id)

    def record_epilogue(self, scope_id: str, record: dict[str, Any]) -> None:
        """Record the once-per-scope epilogue body result."""
        self._scopes.record_epilogue(scope_id, record)

    def get_epilogue(self, scope_id: str) -> dict[str, Any] | None:
        """Return the epilogue record, or None if it has not run."""
        return self._scopes.get_epilogue(scope_id)

    def record_tool_call(self, scope_id: str, record: dict[str, Any]) -> None:
        """Append a gate-tool invocation to this scope's audit log."""
        self._scopes.record_tool_call(scope_id, record)

    def get_tool_calls(self, scope_id: str) -> list[dict[str, Any]]:
        """Every tool call recorded in this scope, oldest first."""
        return self._scopes.get_tool_calls(scope_id)

    def scope_ids(self) -> list[str]:
        """All known scope ids."""
        return self._scopes.scope_ids()

    def scopes_readable(self) -> bool:
        """Whether the scope file can currently be honoured.

        For diagnostics (`func builtin state show`) that report the fault
        instead of propagating it. Everything else lets the error travel.
        """
        return self._scopes.is_readable()

    # ------------------------------------------------------------------
    # History ring buffer (`func history`)
    # ------------------------------------------------------------------

    def append_history(self, record: dict[str, Any]) -> None:
        """Append a run record, trimming to :data:`HISTORY_LIMIT` (newest last)."""

        def _apply(state: dict[str, Any]) -> None:
            history = state["history"]
            history.append(record)
            if len(history) > HISTORY_LIMIT:
                del history[: len(history) - HISTORY_LIMIT]

        self._mutate(_apply)

    def get_history(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return run history newest-first, optionally capped at ``limit``."""
        history = list(reversed(self._read()["history"]))
        return history[:limit] if limit is not None else history

    # ------------------------------------------------------------------
    # Session-scoped precondition cache
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

    def clear(self, *, scopes: bool = False) -> Path | None:
        """Reset derived runtime state. Keeps workflow scopes unless asked.

        Fingerprints, history and the session cache are derived — clearing them
        costs a rebuild. A scope is a run somebody is waiting on, so clearing it
        is a separate decision that has to be made deliberately. It used to be
        made for you: this method reset everything, under help text naming only
        "fingerprints, history".

        Never touches the discovery cache — the two have different lifecycles.

        Args:
            scopes: Also discard persisted workflow scopes.

        Returns:
            Where the scope file was moved, or None if scopes were kept or
            there were none. Scopes are moved aside rather than deleted, so a
            run discarded by mistake is still recoverable.
        """
        with state_lock(self._path):
            save_state(self._path, empty_state())
        return self._scopes.clear() if scopes else None
