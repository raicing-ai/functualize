"""Typed accessors over the workflow-scope envelope.

``ScopeStore`` is the only thing that reads or writes scope records. It sits on
:mod:`functualize._primitives.scope_format`, which owns the file format,
locking, atomic write, and the fail-closed read.

**Why this is a separate class from ``StateStore``.** They hold different kinds
of data with opposite discard rules — derived state is safe to throw away, a
record of an in-flight run is not — and a store's read behaviour is the thing
most easily got wrong by a reader who assumes the neighbouring rule applies.
Splitting the classes gives the fail-closed read exactly one owner. ``StateStore``
still presents one façade over both, so no caller outside ``_primitives`` has to
know which file a section lives in.

**Write discipline.** Every mutation is a locked read-modify-write, so two
concurrent runs touching *different* scope ids merge rather than clobber
(last-writer-wins per scope, not per file). A walk that makes several mutations
for one node takes the lock once with :meth:`ScopeStore.batch`.

**Record shape is unchanged** from when these records lived in ``state.json``.
Every section is a flat ``{str: record}`` mapping, which is what the
``StateBackend`` KV protocol (``get``/``set``/``delete``/``keys``) addresses, so
``functualize-state-sqlite`` can back this store later without a record-format
change. That seam is preserved, not built.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.scope_format import (
    SCOPES_FILENAME,
    clear_scopes,
    load_scopes,
    resolve_scopes_path,
    save_scopes,
    scopes_lock,
    update_scopes,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def _now() -> str:
    """UTC timestamp for a draft edit.

    Draft records carry one because a draft is *collaborative* — two actors may
    fill different fields of the same gate — so "when was this last touched"
    is a question somebody will ask. Step and gate records already carry their
    own; this does not change what the scope record itself holds.
    """
    return datetime.now(UTC).isoformat()


def _blank_scope() -> dict[str, Any]:
    """A scope record with every sub-section present."""
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


class ScopeStore:
    """Typed read/write access to ``.functualize/scopes.json``.

    Args:
        path: The scope file. Use :meth:`for_project` to resolve it as the
            sibling of the runtime state file.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._batch: dict[str, Any] | None = None

    @classmethod
    def for_project(cls, start: Path | str) -> ScopeStore:
        """Build a store at the project's resolved scope path."""
        return cls(resolve_scopes_path(Path(start)))

    @classmethod
    def beside_state(cls, state_path: Path | str) -> ScopeStore:
        """Build a store beside a given state file.

        The sibling rule, applied to an explicit path rather than a project
        root — so ``StateStore(tmp / "state.json")`` in a test finds
        ``tmp / "scopes.json"`` with no extra wiring, and the two files cannot
        land in different directories.
        """
        return cls(Path(state_path).with_name(SCOPES_FILENAME))

    @property
    def path(self) -> Path:
        """The scope file this store reads and writes."""
        return self._path

    # ------------------------------------------------------------------
    # Read / write plumbing
    # ------------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        """Current envelope — the open batch if one is active, else the file.

        Raises:
            ScopeStoreUnreadableError: propagated from ``load_scopes``. Reading
                scopes never degrades to "none".
        """
        if self._batch is not None:
            return self._batch
        return load_scopes(self._path)

    def _mutate(self, mutate: Any) -> None:
        """Apply ``mutate`` to the envelope, honoring an open batch."""
        if self._batch is not None:
            mutate(self._batch)
            return
        update_scopes(self._path, mutate)

    @contextmanager
    def batch(self) -> Iterator[ScopeStore]:
        """Hold the lock for many mutations, writing once at the end.

        Without this, a walk that records a step, sets the position and sets the
        status does three locked read-modify-writes of the whole file for one
        node.

        Writes on clean exit only: an exception inside the block discards the
        block's mutations rather than persisting some of them. For a walk that
        makes a node's writes all-or-nothing, which is what a reader of the
        resulting record expects.
        """
        if self._batch is not None:  # already batching — reuse the outer one
            yield self
            return
        with scopes_lock(self._path):
            self._batch = load_scopes(self._path)
            try:
                yield self
                save_scopes(self._path, self._batch)
            finally:
                self._batch = None

    # ------------------------------------------------------------------
    # Scopes: steps, branches, gates, position, epilogue
    # ------------------------------------------------------------------

    def get_scope(self, scope_id: str) -> dict[str, Any] | None:
        """Return the scope record, or None if the scope is unknown."""
        record = self._read()["scopes"].get(scope_id)
        return record if isinstance(record, dict) else None

    def ensure_scope(self, scope_id: str, workflow: str | None = None) -> None:
        """Create the scope record if absent (idempotent)."""

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].setdefault(scope_id, _blank_scope())
            if workflow is not None:
                scope["workflow"] = workflow

        self._mutate(_apply)

    def set_scope_status(self, scope_id: str, status: str) -> None:
        """Set a scope's status (running/blocked/completed/failed/cancelled)."""

        def _apply(envelope: dict[str, Any]) -> None:
            envelope["scopes"].setdefault(scope_id, _blank_scope())["status"] = status

        self._mutate(_apply)

    def record_step(self, scope_id: str, step_key: str, record: dict[str, Any]) -> None:
        """Record a per-scope step result, keyed ``<job_name>::<args_hash>``.

        One record serves four consumers: replay-skip on resume, branch-choice
        stability, persistent run-once/when-changed dedupe, and epilogue
        ``FromJob[step]`` injection.
        """

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].setdefault(scope_id, _blank_scope())
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
        cannot change branches between pause and resume.
        """

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].setdefault(scope_id, _blank_scope())
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
        """Persist a blocked gate: model name, input schema, payload."""

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].setdefault(scope_id, _blank_scope())
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

        def _apply(envelope: dict[str, Any]) -> None:
            envelope["scopes"][scope_id]["gates"][gate_name]["payload"] = payload

        self._mutate(_apply)
        return True

    def get_gate_draft(self, scope_id: str, gate_name: str) -> dict[str, Any] | None:
        """The gate's accumulated draft, or None if nothing is drafted.

        A draft is *partial* input: what has been supplied so far, before it
        validates whole. The walker never reads it — the invariant that makes
        drafts safe is that ``payload`` is the only thing a walk consumes, and
        it is written only by a complete, successful validation.
        """
        record = self.get_gate(scope_id, gate_name)
        if record is None:
            return None
        draft = record.get("draft")
        return draft if isinstance(draft, dict) else None

    def put_gate_draft(
        self, scope_id: str, gate_name: str, values: dict[str, Any]
    ) -> bool:
        """Replace the gate's draft values. False if no such gate.

        Merging is the *caller's* decision, not this store's: whether new fields
        merge into or replace the draft is a verb-level choice
        (``answer --input`` versus ``--replace``), and a store that merged
        silently would make ``--replace`` unimplementable.
        """
        if self.get_gate(scope_id, gate_name) is None:
            return False

        def _apply(envelope: dict[str, Any]) -> None:
            envelope["scopes"][scope_id]["gates"][gate_name]["draft"] = {
                "values": dict(values),
                "updated_at": _now(),
            }

        self._mutate(_apply)
        return True

    def clear_gate_draft(self, scope_id: str, gate_name: str) -> bool:
        """Discard the gate's draft. False if no such gate.

        The key is *removed*, not set to None: absent and "no draft" are the
        same fact, and having two spellings for it is how a reader ends up
        checking only one.
        """
        if self.get_gate(scope_id, gate_name) is None:
            return False

        def _apply(envelope: dict[str, Any]) -> None:
            envelope["scopes"][scope_id]["gates"][gate_name].pop("draft", None)

        self._mutate(_apply)
        return True

    def reopen_gate(self, scope_id: str, gate_name: str) -> bool:
        """Move an answered gate's payload back into its draft.

        False when there is no such gate or nothing was answered.

        **No policy here.** Whether reopening is *allowed* depends on where the
        walk has got to — a scope past the gate has already consumed the answer,
        and reopening it would silently diverge the recorded results from the
        input that produced them. That judgement needs the graph, which this
        layer cannot see, so it lives in ``app/_workflow_answer.py``
        (``contributor/reference/pitfalls.md`` §22: a reader must not
        reconstruct what another layer computed).
        """
        record = self.get_gate(scope_id, gate_name)
        if record is None or record.get("payload") is None:
            return False

        def _apply(envelope: dict[str, Any]) -> None:
            gate = envelope["scopes"][scope_id]["gates"][gate_name]
            gate["draft"] = {"values": dict(gate["payload"]), "updated_at": _now()}
            gate["payload"] = None

        self._mutate(_apply)
        return True

    def delete_scope(self, scope_id: str) -> bool:
        """Remove a scope entirely. False if it was not there.

        Used only by ``builtin workflow purge``, which refuses live scopes —
        this is a hard delete with no backup, unlike :meth:`clear`, which moves
        the whole file aside.
        """
        if self.get_scope(scope_id) is None:
            return False

        def _apply(envelope: dict[str, Any]) -> None:
            envelope["scopes"].pop(scope_id, None)

        self._mutate(_apply)
        return True

    def set_position(self, scope_id: str, node: str | None) -> None:
        """Persist the blocked-walk position so a walk survives."""

        def _apply(envelope: dict[str, Any]) -> None:
            envelope["scopes"].setdefault(scope_id, _blank_scope())["position"] = node

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

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].setdefault(scope_id, _blank_scope())
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

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].setdefault(scope_id, _blank_scope())
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
    # Lifecycle (`func builtin state clear --scopes`)
    # ------------------------------------------------------------------

    def clear(self) -> Path | None:
        """Discard every scope, moving the file aside. Returns where it went.

        Moved rather than deleted: the runs inside may still be wanted, and this
        is the only escape hatch from a file the reader refuses. Never reads it.
        """
        return clear_scopes(self._path)
