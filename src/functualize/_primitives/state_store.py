"""Typed accessors over the runtime state envelope (schema.md §1, Part F).

``StateStore`` is the only thing that reads or writes runtime state records —
fingerprints, per-scope workflow records, run history, and the session-scoped
precondition cache. It sits on :mod:`functualize._primitives.state_format`,
which owns the file format, locking, and atomic write.

**Write discipline.** Every mutation is a locked read-modify-write, so two
concurrent runs touching *different* job keys merge rather than clobber
(Part F: last-writer-wins per key, not per file). A run that makes many
mutations should use :meth:`StateStore.batch` to take the lock once.

**Relationship to ``functualize-state`` (Part F).** Every section here is a
flat ``{str: record}`` mapping, which is exactly the shape the plugin's
``StateBackend`` KV protocol addresses (``get``/``set``/``delete``/``keys``).
That correspondence is deliberate so ``functualize-state-sqlite`` can back this
store later without a record-format change. The backend indirection itself is
not built here — there is no second backend to serve yet, and a swap seam with
one implementation is speculation, not design.

Lives in ``_primitives/`` (stdlib-only) because both the engine and the CLI
(`func history`, `func state clear`) read it.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


def _blank_scope() -> dict[str, Any]:
    """A scope record with every §D.7 sub-section present."""
    return {
        "workflow": None,
        "status": "running",
        "steps": {},
        "branches": {},
        "gates": {},
        "position": None,
        "epilogue": None,
        "tool_calls": [],
    }


class StateStore:
    """Typed read/write access to ``.functualize/state.json``.

    Args:
        path: The state file. Use :meth:`for_project` to resolve it the same
            way the discovery cache is resolved.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._batch: dict[str, Any] | None = None

    @classmethod
    def for_project(cls, start: Path | str) -> StateStore:
        """Build a store at the project's resolved state path."""
        return cls(resolve_state_path(Path(start)))

    @property
    def path(self) -> Path:
        """The state file this store reads and writes."""
        return self._path

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
    def batch(self) -> Iterator[StateStore]:
        """Hold the lock for many mutations, writing once at the end.

        Without this, a run that records N fingerprints does N locked
        read-modify-writes of the whole file.
        """
        if self._batch is not None:  # already batching — reuse the outer one
            yield self
            return
        with state_lock(self._path):
            self._batch = load_state(self._path)
            try:
                yield self
                save_state(self._path, self._batch)
            finally:
                self._batch = None

    # ------------------------------------------------------------------
    # Fingerprints (§D.3)
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
    # Scopes: steps, branches, gates, position, epilogue (§D.7c/§D.7d)
    # ------------------------------------------------------------------

    def get_scope(self, scope_id: str) -> dict[str, Any] | None:
        """Return the scope record, or None if the scope is unknown."""
        record = self._read()["scopes"].get(scope_id)
        return record if isinstance(record, dict) else None

    def ensure_scope(self, scope_id: str, workflow: str | None = None) -> None:
        """Create the scope record if absent (idempotent)."""

        def _apply(state: dict[str, Any]) -> None:
            scope = state["scopes"].setdefault(scope_id, _blank_scope())
            if workflow is not None:
                scope["workflow"] = workflow

        self._mutate(_apply)

    def set_scope_status(self, scope_id: str, status: str) -> None:
        """Set a scope's status (running/blocked/completed/failed/cancelled)."""

        def _apply(state: dict[str, Any]) -> None:
            state["scopes"].setdefault(scope_id, _blank_scope())["status"] = status

        self._mutate(_apply)

    def record_step(self, scope_id: str, step_key: str, record: dict[str, Any]) -> None:
        """Record a per-scope step result, keyed ``<job_name>::<args_hash>``.

        One record serves four consumers (§D.7d): replay-skip on resume,
        branch-choice stability, persistent run-once/when-changed dedupe, and
        epilogue ``FromJob[step]`` injection.
        """

        def _apply(state: dict[str, Any]) -> None:
            scope = state["scopes"].setdefault(scope_id, _blank_scope())
            scope["steps"][step_key] = record

        self._mutate(_apply)

    def get_step(self, scope_id: str, step_key: str) -> dict[str, Any] | None:
        """Return a recorded step result for this scope, or None."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return None
        record = scope.get("steps", {}).get(step_key)
        return record if isinstance(record, dict) else None

    def record_branch(self, scope_id: str, source: str, target: str) -> None:
        """Record a chosen ``ConditionalEdge`` target on first evaluation.

        Read (never re-evaluated) on replay, so a non-deterministic condition
        cannot change branches between pause and resume (§D.7d).
        """

        def _apply(state: dict[str, Any]) -> None:
            scope = state["scopes"].setdefault(scope_id, _blank_scope())
            scope["branches"][source] = target

        self._mutate(_apply)

    def get_branch(self, scope_id: str, source: str) -> str | None:
        """Return the branch target recorded for ``source``, or None."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return None
        target = scope.get("branches", {}).get(source)
        return target if isinstance(target, str) else None

    def put_gate(self, scope_id: str, gate_name: str, record: dict[str, Any]) -> None:
        """Persist a blocked gate: model name, input schema, payload (§D.7c)."""

        def _apply(state: dict[str, Any]) -> None:
            scope = state["scopes"].setdefault(scope_id, _blank_scope())
            scope["gates"][gate_name] = record

        self._mutate(_apply)

    def get_gate(self, scope_id: str, gate_name: str) -> dict[str, Any] | None:
        """Return a persisted gate record, or None."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return None
        record = scope.get("gates", {}).get(gate_name)
        return record if isinstance(record, dict) else None

    def deposit_gate_payload(self, scope_id: str, gate_name: str, payload: Any) -> bool:
        """Deposit resolved input for a blocked gate. False if no such gate."""
        if self.get_gate(scope_id, gate_name) is None:
            return False

        def _apply(state: dict[str, Any]) -> None:
            state["scopes"][scope_id]["gates"][gate_name]["payload"] = payload

        self._mutate(_apply)
        return True

    def set_position(self, scope_id: str, node: str | None) -> None:
        """Persist the blocked-walk position so a walk survives (§D.7c)."""

        def _apply(state: dict[str, Any]) -> None:
            state["scopes"].setdefault(scope_id, _blank_scope())["position"] = node

        self._mutate(_apply)

    def get_position(self, scope_id: str) -> str | None:
        """Return the persisted walk position, or None."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return None
        node = scope.get("position")
        return node if isinstance(node, str) else None

    def record_epilogue(self, scope_id: str, record: dict[str, Any]) -> None:
        """Record the once-per-scope epilogue body result."""

        def _apply(state: dict[str, Any]) -> None:
            scope = state["scopes"].setdefault(scope_id, _blank_scope())
            scope["epilogue"] = record

        self._mutate(_apply)

    def get_epilogue(self, scope_id: str) -> dict[str, Any] | None:
        """Return the epilogue record, or None if it has not run."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return None
        record = scope.get("epilogue")
        return record if isinstance(record, dict) else None

    def record_tool_call(self, scope_id: str, record: dict[str, Any]) -> None:
        """Append a gate-tool invocation to this scope's audit log.

        Deliberately **append-only and never memoized**, unlike step records.
        A step is part of the plan and must not run twice on replay; a tool
        call is exploration, and an agent that calls ``check_inventory`` three
        times before deciding meant to. Replaying a scope must therefore not
        skip a call, and the third call must not silently return the first
        one's answer.

        Recorded all the same, because "which tools did the agent use before
        approving this refund?" is exactly the question an auditor asks, and
        the answer lives nowhere else — the agent's own context is gone.
        """

        def _apply(state: dict[str, Any]) -> None:
            scope = state["scopes"].setdefault(scope_id, _blank_scope())
            scope.setdefault("tool_calls", []).append(record)

        self._mutate(_apply)

    def get_tool_calls(self, scope_id: str) -> list[dict[str, Any]]:
        """Every tool call recorded in this scope, oldest first."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return []
        calls = scope.get("tool_calls", [])
        return (
            [c for c in calls if isinstance(c, dict)] if isinstance(calls, list) else []
        )

    def scope_ids(self) -> list[str]:
        """All known scope ids."""
        return sorted(self._read()["scopes"])

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
    # Session-scoped precondition cache (§D.2)
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
    # Lifecycle (`func state clear`)
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset all runtime state. Never touches the discovery cache (§D.3
        Fix 2) — the two stores have different lifecycles."""
        with state_lock(self._path):
            save_state(self._path, empty_state())
