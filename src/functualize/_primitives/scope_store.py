"""Typed accessors over the workflow-scope envelope.

``ScopeStore`` is the only thing that reads or writes scope records. It sits on
:mod:`functualize._primitives.scope_format`, which owns the file format,
locking, atomic write, and the fail-closed read.

**Why this is a separate class from ``FreshStore``.** They hold different kinds
of data with opposite discard rules — derived state is safe to throw away, a
record of an in-flight run is not — and a store's read behaviour is the thing
most easily got wrong by a reader who assumes the neighbouring rule applies.
Splitting the classes gives the fail-closed read exactly one owner. ``FreshStore``
still presents one façade over both, so no caller outside ``_primitives`` has to
know which file a section lives in.

**Write discipline.** Every mutation is a locked read-modify-write, so two
concurrent runs touching *different* scope ids merge rather than clobber
(last-writer-wins per scope, not per file). A walk that makes several mutations
for one node takes the lock once with :meth:`ScopeStore.batch`.

**Record shape is unchanged** from when these records lived in ``fresh.json``.
Every section is a flat ``{str: record}`` mapping, which is what the
``StateBackend`` KV protocol (``get``/``set``/``delete``/``keys``) addresses, so
``functualize-state-sqlite`` can back this store later without a record-format
change. That seam is preserved, not built.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.lease import (
    DEFAULT_LEASE_SECONDS,
    Lease,
    StaleGenerationError,
    check_generation,
    claim,
    read_lease,
    release,
    renew,
    write_lease,
)
from functualize._primitives.scope_format import (
    SCOPES_FILENAME,
    clear_scopes,
    load_scopes,
    resolve_scopes_path,
    save_scopes,
    scopes_lock,
    update_scopes,
)
from functualize._primitives.scope_state_store import (
    ScopeStateStore,
    scope_state_path,
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
        #: Keys a *job body* wrote through `rc.state` / `state: State`.
        #:
        #: Here rather than in `fresh.json` by that file's own rule: this one
        #: holds records — not recomputable, refuse rather than discard — and
        #: what a job stored is a record by that test. `fresh.json` may throw
        #: its contents away on a bad read, which for job state is the silent
        #: data loss this section exists to avoid.
        #:
        #: Namespaced under the scope, so two runs of one workflow share
        #: nothing and a resumed run finds what its earlier half wrote.
        "state": {},
    }


class ScopeStore:
    """Typed read/write access to ``.functualize/scopes.json``.

    Args:
        path: The scope file. Use :meth:`for_project` to resolve it as the
            sibling of the runtime state file.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        #: The open batch, **per thread**.
        #:
        #: It was one attribute on the instance, which was correct while one
        #: run owned one store. It is not any more: `invoke_parallel` gives all
        #: 32 workers the same `WorkflowScope`, so they share one `ScopeStore`
        #: and shared one `_batch` — and `_mutate` folds *any* write on the
        #: instance into whatever batch happens to be open. A sibling thread's
        #: `set_state` therefore joined another thread's transaction, returned
        #: successfully, and vanished if that transaction raised. Reproduced by
        #: an external review before this was fixed:
        #:
        #:     clean batch exit : {"main": 1, "sibling": 2}
        #:     batch raises     : {}
        #:
        #: Thread-local, so a batch is a transaction for the thread that opened
        #: it and nobody else's writes ride on it. The file lock still
        #: serialises the *commit* across threads and processes alike.
        self._local = threading.local()
        #: Scopes whose record this instance has already ensured — see
        #: `_state_store`. Process-local and advisory: a miss costs one
        #: redundant idempotent write, never a wrong answer.
        self._ensured: set[str] = set()
        #: One `ScopeStateStore` per scope, because `batch()` keeps its open
        #: payload on the instance. A fresh object per call would make a batch
        #: block invisible to the writes inside it.
        self._state_stores: dict[str, ScopeStateStore] = {}
        #: The generation each *claimed scope*'s writes must carry. Keyed by
        #: scope id, not one value for the store: a nested workflow claims its
        #: own scope through the **same** store object, and a single value made
        #: the parent's hold fence the child's writes to a different scope —
        #: the child could not even create its record. See `hold`.
        self._generations: dict[str, int] = {}

    @property
    def _batch(self) -> dict[str, Any] | None:
        return getattr(self._local, "batch", None)

    @_batch.setter
    def _batch(self, value: dict[str, Any] | None) -> None:
        self._local.batch = value

    @classmethod
    def for_project(cls, start: Path | str) -> ScopeStore:
        """Build a store at the project's resolved scope path."""
        return cls(resolve_scopes_path(Path(start)))

    @classmethod
    def beside_fresh(cls, state_path: Path | str) -> ScopeStore:
        """Build a store beside a given state file.

        The sibling rule, applied to an explicit path rather than a project
        root — so ``FreshStore(tmp / "fresh.json")`` in a test finds
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

    def _mutate(self, mutate: Any, *, scope_id: str | None = None) -> None:
        """Apply ``mutate`` to the envelope, honoring an open batch.

        **Where fencing happens** (`durable-run-layer`/T6). Putting the check
        on each of the eleven write methods would fence them all today and miss
        the twelfth, added next month by someone who did not know the rule —
        the same failure mode the capability tripwire exists for. One check
        here means a write path added tomorrow is fenced the day it is written.

        The check runs **inside the lock**, against the envelope this call is
        about to modify, so a claim that landed between the caller's last read
        and this write is seen. Checking beforehand would leave exactly that
        window open.
        """

        def _guarded(envelope: dict[str, Any]) -> None:
            held = self._generations.get(scope_id) if scope_id is not None else None
            if held is not None and scope_id is not None:
                check_generation(
                    scope_id,
                    read_lease(envelope["scopes"].get(scope_id)),
                    held,
                )
            mutate(envelope)

        if self._batch is not None:
            _guarded(self._batch)
            return
        update_scopes(self._path, _guarded)

    def hold(self, scope_id: str, generation: int | None) -> None:
        """Fence writes **to ``scope_id``** on this store to ``generation``.

        Set by a walk once it has claimed that scope. `None` forgets the hold,
        which is the state every scope starts in: a store not driving a walk —
        the CLI reading records, a purge, a plugin — has no lease and must not
        be refused.

        **Per scope, not per store.** A single value looked simpler and was
        wrong: a nested workflow claims its own scope through the *same* store
        object, so the parent's hold fenced every write the child made to a
        different scope — the child could not create its own record at all.
        Caught by `test_a_nested_workflow_still_owns_its_own_scope`.
        """
        if generation is None:
            self._generations.pop(scope_id, None)
        else:
            self._generations[scope_id] = generation

    def generation_for(self, scope_id: str) -> int | None:
        """The generation this store's writes to ``scope_id`` carry, or None."""
        return self._generations.get(scope_id)

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

        self._mutate(_apply, scope_id=scope_id)

    def set_graph_digest(self, scope_id: str, digest: str) -> None:
        """Record which graph this scope's walk was started against (T11).

        Written once, on first entry, and never overwritten: the question a
        resume asks is *"is the loaded graph the one this walk started with"*,
        and a digest that followed the current declaration would always agree
        with itself.
        """

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].setdefault(scope_id, _blank_scope())
            scope.setdefault("graph_digest", digest)

        self._mutate(_apply, scope_id=scope_id)

    def get_graph_digest(self, scope_id: str) -> str:
        """The graph this scope was started against, or `""` if unrecorded.

        `""` for a scope written before T11, which is the legacy-mapping path
        AC-17 asks for: an unrecorded digest compares equal to anything, so an
        existing parked walk resumes rather than being refused by a check that
        did not exist when it was parked.
        """
        scope = self.get_scope(scope_id)
        digest = scope.get("graph_digest") if scope else None
        return digest if isinstance(digest, str) else ""

    def set_scope_status(self, scope_id: str, status: str) -> None:
        """Set a scope's status (running/blocked/completed/failed/cancelled)."""

        def _apply(envelope: dict[str, Any]) -> None:
            envelope["scopes"].setdefault(scope_id, _blank_scope())["status"] = status

        self._mutate(_apply, scope_id=scope_id)

    def record_step(self, scope_id: str, step_key: str, record: dict[str, Any]) -> None:
        """Record a per-scope step result, keyed ``<job_name>::<args_hash>``.

        One record serves four consumers: replay-skip on resume, branch-choice
        stability, persistent run-once/when-changed dedupe, and epilogue
        ``FromJob[step]`` injection.
        """

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].setdefault(scope_id, _blank_scope())
            scope["steps"][step_key] = record

        self._mutate(_apply, scope_id=scope_id)

    def get_step(self, scope_id: str, step_key: str) -> dict[str, Any] | None:
        """Return a recorded step result for this scope, or None."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return None
        record = scope.get("steps", {}).get(step_key)
        return record if isinstance(record, dict) else None

    # ------------------------------------------------------------------
    # Scopes: job state
    #
    # **Not in `scopes.json`.** Every method below delegates to a per-scope
    # file (`scope-record-lifecycle`/T3). The state used to be a section of the
    # scope record, which made one `set` parse and rewrite every record the
    # project had ever made: 116x slower than an empty store at 2,001 records,
    # and 58 ms per write on a real project's file. A per-run value belongs in
    # a per-run file. It also gives each run its own lock, so two jobs sharing
    # nothing no longer serialize on every write.
    #
    # These stay on `ScopeStore` rather than moving to the caller because the
    # scope id is what names the file, and `ScopeStore` is what owns the
    # mapping from an id to where its data lives.
    # ------------------------------------------------------------------

    def _state_store(self, scope_id: str, *, ensure: bool = True) -> ScopeStateStore:
        """This scope's state file. Cheap: no read of ``scopes.json``.

        **There is deliberately no migration of the old inline section.** The
        first version of this read the scope record when the per-scope file was
        absent, to carry forward state written before T3 — and that read cost
        the whole envelope, leaving `set` at 17x instead of the 1.2x `get`
        reached. A compatibility probe in the hot path reintroduced exactly the
        cost this task removes.

        The Pre-Release Stance (`.spec/CONSTITUTION.md`) is what makes dropping
        it right rather than merely convenient: delete rather than shim. The
        cost is real and bounded — a run that was *in flight* across this
        change resumes with its state empty. Its step records, gates and
        position are untouched, because those never moved.

        **The record is ensured once per scope per process, and only for a
        write.** State and records are separate files now, and the old
        `set_state` created the record as a side effect of `setdefault`. Losing
        that silently orphaned every state file: `purge_scopes` walks
        *records*, so state with no record is state nothing can ever collect.
        Ensuring it costs one whole-envelope write, so it happens on the first
        *write* to a scope and never again — the memo keeps it off the hot
        path, and ``ensure=False`` keeps a read of a scope that never ran from
        minting one.

        **The instance is cached**, which batching depends on: `_batch` lives
        on the store object, so handing out a fresh one per call would mean a
        `state_batch` block never saw its own writes.
        """
        if ensure and scope_id not in self._ensured:
            # Idempotent, so a race between two threads writes the same record
            # twice rather than two different ones. Marked before the call so a
            # second thread does not queue behind the first to redo it.
            self._ensured.add(scope_id)
            self.ensure_scope(scope_id)
        # `setdefault`, not get-then-set: two threads reaching a new scope id
        # together both built a store and the loser's object was returned to
        # its caller but never cached, so a batch opened on it was invisible to
        # every later accessor — and two `ScopeStateStore` objects over one
        # path self-deadlock on `flock` (review Q1.5, Q2.2).
        return self._state_stores.setdefault(
            scope_id, ScopeStateStore(scope_state_path(self._path, scope_id))
        )

    def get_state(self, scope_id: str, key: str, default: Any = None) -> Any:
        """A value a job stored in this scope, or ``default``."""
        return self._state_store(scope_id, ensure=False).get(key, default)

    def set_state(self, scope_id: str, key: str, value: Any) -> None:
        """Store one value in this scope.

        Re-reads inside the scope's own lock, so two jobs writing different
        keys merge rather than clobber. A job writing many keys should hold
        :meth:`state_batch` — every call here is one lock-read-write cycle.
        """
        self._state_store(scope_id).set(key, value)

    def delete_state(self, scope_id: str, key: str) -> bool:
        """Remove one key. True when it was there."""
        return self._state_store(scope_id).delete(key)

    def state_snapshot(self, scope_id: str) -> dict[str, Any]:
        """Every key this scope holds, as a plain dict."""
        return self._state_store(scope_id, ensure=False).snapshot()

    def clear_state(self, scope_id: str) -> None:
        """Drop every key in this scope, leaving the scope itself."""
        self._state_store(scope_id).clear()

    def state_batch(self, scope_id: str) -> Any:
        """Hold this scope's state lock across many writes.

        Separate from :meth:`batch`, which batches *records*. The two files
        have separate locks now, which is the point — batching one must not
        hold the other.
        """
        return self._state_store(scope_id).batch()

    def discard_state(self, scope_id: str) -> bool:
        """Delete this scope's state file. True if there was one.

        Called when the record is purged. Ordering matters and belongs to the
        caller: the **record** goes first. The reverse leaves a record pointing
        at state that is gone, which reads as corruption; this order leaves a
        file nothing references, which reads as nothing at all.
        """
        # Through the cache, never a fresh object: a second `ScopeStateStore`
        # over one path cannot see an open batch and deadlocks against the
        # first on `flock` (review Q1.1, Q2.2). `ensure=False` so purging a
        # scope cannot recreate the record purge just deleted.
        return self._state_store(scope_id, ensure=False).discard()

    def record_branch(self, scope_id: str, source: str, target: str) -> None:
        """Record a chosen ``ConditionalEdge`` target on first evaluation.

        Read (never re-evaluated) on replay, so a non-deterministic condition
        cannot change branches between pause and resume.
        """

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].setdefault(scope_id, _blank_scope())
            scope["branches"][source] = target

        self._mutate(_apply, scope_id=scope_id)

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

        self._mutate(_apply, scope_id=scope_id)

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

        self._mutate(_apply, scope_id=scope_id)
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

        self._mutate(_apply, scope_id=scope_id)
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

        self._mutate(_apply, scope_id=scope_id)
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

        self._mutate(_apply, scope_id=scope_id)
        return True

    def _forget(self, scope_id: str) -> None:
        """Drop cached knowledge of a scope whose record no longer exists.

        `_ensured` says "this instance has already written this scope's
        record". After `delete_scope` that is false, and leaving it set meant a
        later `set_state` wrote a state file with **no record** — which
        `purge_scopes` can never find, because it walks records (review Q1.4).
        """
        self._ensured.discard(scope_id)

    # ------------------------------------------------------------------
    # The lease (`durable-run-layer`/T5)
    #
    # Stored inside the scope record (schema §4), additive, no version bump —
    # the same judgement 0.3.0 made for `draft`. The *rules* live in
    # `_primitives/lease.py` as pure functions; this applies them under the
    # file lock so a claim is read-modify-written atomically where locking
    # works. **The lock is an optimisation, not the mechanism**: the fencing
    # check is a comparison of a recorded integer and holds without it.
    # ------------------------------------------------------------------

    def get_lease(self, scope_id: str) -> Lease | None:
        """The lease on this scope, or None if nobody has claimed it."""
        return read_lease(self.get_scope(scope_id))

    def claim_scope(
        self,
        scope_id: str,
        *,
        owner: str,
        seconds: float = DEFAULT_LEASE_SECONDS,
        force: bool = False,
        now: datetime | None = None,
    ) -> Lease:
        """Take the scope. Returns the lease at its **new** generation.

        Raises:
            LeaseHeldError: Someone else holds it and has not expired.
        """
        when = now or datetime.now(UTC)
        taken: list[Lease] = []

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].setdefault(scope_id, _blank_scope())
            # Re-read *inside* the lock: two runners racing to claim an expired
            # lease must not both see generation 6 and both write 7. Where
            # locking works this makes the claim atomic; where it does not, the
            # loser's later writes are still fenced, which is the guarantee
            # that does not depend on the filesystem.
            fresh = claim(
                scope_id,
                read_lease(scope),
                owner=owner,
                now=when,
                seconds=seconds,
                force=force,
            )
            write_lease(scope, fresh)
            taken.append(fresh)

        self._mutate(_apply)
        return taken[0]

    def renew_scope(
        self,
        scope_id: str,
        *,
        owner: str,
        generation: int,
        seconds: float = DEFAULT_LEASE_SECONDS,
        now: datetime | None = None,
    ) -> Lease:
        """Extend a claim you hold. The generation does not move.

        Raises:
            StaleGenerationError: Someone claimed the scope after you did.
        """
        when = now or datetime.now(UTC)
        renewed: list[Lease] = []

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].get(scope_id)
            if scope is None:
                raise StaleGenerationError(
                    scope_id, held=0, offered=generation, owner="nobody"
                )
            fresh = renew(
                scope_id,
                read_lease(scope),
                owner=owner,
                generation=generation,
                now=when,
                seconds=seconds,
            )
            write_lease(scope, fresh)
            renewed.append(fresh)

        self._mutate(_apply)
        return renewed[0]

    def release_scope(
        self, scope_id: str, *, generation: int, now: datetime | None = None
    ) -> None:
        """Give up a claim you hold, leaving the scope immediately claimable.

        The lease is **expired, not deleted** — see `lease.release`. Deleting
        would reset the generation, so this runner's own in-flight writes would
        be accepted by the next holder.

        Raises:
            StaleGenerationError: Someone else holds it now, so there is
                nothing of yours to release — and clearing theirs would hand
                the scope to a third runner mid-walk.
        """
        when = now or datetime.now(UTC)

        def _apply(envelope: dict[str, Any]) -> None:
            scope = envelope["scopes"].get(scope_id)
            if scope is None:
                raise StaleGenerationError(
                    scope_id, held=0, offered=generation, owner="nobody"
                )
            write_lease(
                scope,
                release(scope_id, read_lease(scope), generation=generation, now=when),
            )

        self._mutate(_apply)

    def check_scope_generation(self, scope_id: str, generation: int) -> None:
        """Raise unless ``generation`` currently holds this scope.

        The read half of fencing, for a caller that wants to fail before doing
        work rather than after. Every fenced *write* checks this itself.
        """
        check_generation(scope_id, self.get_lease(scope_id), generation)

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

        self._mutate(_apply, scope_id=scope_id)
        self._forget(scope_id)
        return True

    def set_position(self, scope_id: str, node: str | None) -> None:
        """Persist the blocked-walk position so a walk survives."""

        def _apply(envelope: dict[str, Any]) -> None:
            envelope["scopes"].setdefault(scope_id, _blank_scope())["position"] = node

        self._mutate(_apply, scope_id=scope_id)

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

        self._mutate(_apply, scope_id=scope_id)

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

        self._mutate(_apply, scope_id=scope_id)

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
