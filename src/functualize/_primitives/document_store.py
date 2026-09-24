"""The document backend behind the runtime ports — and an honest profile.

FUN-17/T7. `DocumentRuntimeStore` is the `RuntimeStore` implementation over
today's three JSON document stores: `ScopeStore` (`.functualize/scopes.json`),
`RunStore` (`.functualize/runs.json`) and `ScopeStateStore`
(`.functualize/scope-state/<id>.json`, reached through `ScopeStore`'s state
seam so the memoized instance and its open batch are the ones written).

It lives in `_primitives` because that is where the three stores it wraps
live. Putting it in `_engine` would place storage adaptation in the layer that
owns lifecycle meaning — the line `plan.md` draws when it rejects Candidate C.

**It is a declared middle man and it is temporary.** The class carries
`# TRANSITIONAL(FUN-17/T7)`: it forwards to three existing stores and adds no
behaviour of its own beyond the profile, the buffering transaction and the
cross-aggregate refusal (T8). The standard answer to middle man — remove it —
is what FUN-19's `SqliteRuntimeStore` does, and this file goes with it.

## The profile is what this store may be selected for

`DOCUMENT_PROFILE` declares ten capabilities and boot refuses rather than
degrades when a feature needs one this store does not have
(`_types/persistence.py` → `StoreProfile`; the check itself is T13's). Two of
the ten are deliberately **stricter than the capability matrix's filesystem
column**, and the reason is that this profile describes *these three stores*,
not a generic filesystem probe — see `DOCUMENT_PROFILE` for the field-by-field
note.

`interactive_transaction=True` **is** the filesystem column's measured value
(`contributor/reference/substrate-capability-matrix.md`, `interactive_transaction`
row, `yes · real`): here a unit is a local `flock` over a file, not a wire
protocol. That is a fact about this store and changes nothing about the port —
acceptance criterion 1's accumulation rule binds `RuntimeTransaction` itself,
because the rule exists so the port stays implementable on a backend that has
no interactive transaction at all (Cloudflare D1, measured `no · real`). A
store that happens to have one still accumulates.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from functualize._primitives.lease import LeaseHeldError
from functualize._primitives.run_store import RunStore
from functualize._primitives.scope_store import ScopeStore
from functualize._types.errors import CrossAggregateRefusedError
from functualize._types.persistence import (
    CancelWorkflow,
    Claimed,
    ClaimWorkflow,
    CompleteStep,
    Conflict,
    EffectWriter,
    EventView,
    EventWriter,
    FinishAttempt,
    InputReader,
    InputRequest,
    InputWriter,
    ResumeWorkflow,
    RunQuery,
    RunReader,
    RuntimeTransaction,
    RunTree,
    RunView,
    RunWriter,
    StartAttempt,
    StateBatch,
    StoreProfile,
    SuspendAtGate,
    WorkflowQuery,
    WorkflowReader,
    WorkflowView,
    WorkflowWriter,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from functualize._types.protocols import StoreSubstrate

__all__ = ["DOCUMENT_PROFILE", "DocumentRuntimeStore"]


#: What the three document stores can actually promise.
#:
#: Nine of the ten values are the filesystem column of
#: `contributor/reference/substrate-capability-matrix.md` (`:79-88`), which is
#: the authority for every capability in this wave. **One is deliberately
#: weaker than that row**, because the matrix measures a *substrate* and this
#: profile describes what `ScopeStore` / `RunStore` / `ScopeStateStore` do on
#: one — and for one field the weakest of the three decides.
#:
#: - `fencing` is `"cross-process"`, matching the matrix (`:80`). An earlier
#:   draft declared `"process-local"` on the grounds that the hold supplying
#:   the generation lives on the store object (`ScopeStore.hold`,
#:   `_generations`), so a writer in another process "carries no hold and
#:   nothing refuses it". The hold is real, and the conclusion does not follow.
#:   The generation it is compared *against* is read off disk inside the lock —
#:   `check_generation(scope_id, read_lease(envelope["scopes"].get(scope_id)),
#:   held)` (`scope_store.py:278-285`), where `envelope` came from
#:   `_load_with_revision()`. So a stale lease holder **in any process** is
#:   refused: its in-memory generation loses to the lease on disk. And the
#:   write is a compare-and-swap regardless of any hold —
#:   `write(..., expect=revision)` inside the `_WRITE_ATTEMPTS` loop
#:   (`scope_store.py:294-305`), which `scope_store.py:271` states outright:
#:   "Compare-and-swap backs up the advisory lock." A caller with *no* hold is
#:   not a fencing gap but the documented intent — `ScopeStore.hold` says a
#:   store not driving a walk "has no lease and must not be refused". The
#:   two-documents point is true and belongs to `cross_aggregate_atomicity`,
#:   which is already `False`; spending it twice would state it once as a claim
#:   about the fence's *reach*, which is what this field measures.
#: - `multi_process` is `False` while the matrix reads `yes · real` (`:81`),
#:   and this is the one place the matrix is not the authority. It measured
#:   `JsonFileSubstrate`, whose CAS is genuinely cross-process. This profile
#:   covers three stores, and **`RunStore` does not compare-and-swap**:
#:   `_mutate` is a locked read-modify-write ending in
#:   `write(self._key, stamp_runs(envelope))` with no `expect=`
#:   (`run_store.py:189-192`), as is `batch` (`:204-208`). Its only protection
#:   against a second process is the advisory lock, which proceeds unlocked
#:   after ten seconds and is a no-op without `fcntl` or `msvcrt`. So two
#:   processes *can* lose a run record — deliberately, since a run record "is
#:   history, not an in-flight run: losing it costs a `func builtin history`
#:   entry, not somebody's approval" (`run_store.py:162-164`). One value covers
#:   all three stores, so it takes the weakest, and the weakest is `RunStore`.
#:   `ScopeStore` and `ScopeStateStore` would each support `True` alone.
#:
#: Neither value is an apology and neither is re-derived from vendor
#: documentation: both are what the code in this package does today, and
#: `multi_process=False` is what makes T13 refuse a feature that needs more
#: rather than silently degrade.
DOCUMENT_PROFILE = StoreProfile(
    name="documents",
    cross_aggregate_atomicity=False,
    fencing="cross-process",
    multi_process=False,
    multi_machine=False,
    durable_outbox=False,
    versioned_migrations=False,
    interactive_transaction=True,
    remote=False,
    max_document_bytes=None,
    offline_capable=True,
    description=(
        "JSON documents on the project's StoreSubstrate — the filesystem by "
        "default, and the only store that works with no network. Values are "
        "the matrix's filesystem column; a stronger substrate is "
        "under-declared, never over-declared."
    ),
)


def _parse(value: Any) -> datetime | None:
    """An ISO timestamp from a document, or None when it is absent or junk.

    Tolerant on purpose: these fields are read to *render history*, and a
    record whose timestamp cannot be parsed is still a record that happened.
    Refusing here would make one bad row hide every good one beside it.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _at(value: Any) -> datetime:
    """As `_parse`, for a field a view declares non-optional."""
    return _parse(value) or datetime.fromtimestamp(0, UTC)


def _iso(when: datetime) -> str:
    return when.isoformat()


# ------------------------------------------------------------------
# The read side. Questions, answered off the documents.
# ------------------------------------------------------------------


class _DocumentRunReader:
    """`RunReader` over `RunStore`."""

    def __init__(self, runs: RunStore) -> None:
        self._runs = runs

    def run(self, run_id: str) -> RunView | None:
        record = self._runs.get_run(run_id)
        return None if record is None else _run_view(run_id, record)

    def recent(self, query: RunQuery) -> Sequence[RunView]:
        """The newest runs matching every set filter, newest first.

        Filtered after the read rather than in a predicate, which is what
        `remote=False` buys: the whole document is already in memory. A
        network store answers this with a `WHERE` clause and an index.
        """
        limit = query.limit if query.limit is not None else 20
        views: list[RunView] = []
        # Over-read, because `recent_runs` caps before filtering and a filtered
        # answer must still be able to reach `limit`.
        for record in self._runs.recent_runs(limit=max(limit * 8, limit)):
            run_id = str(record.get("run_id", ""))
            if query.job is not None and record.get("job") != query.job:
                continue
            if query.status is not None and record.get("status") != query.status:
                continue
            if query.scope_id is not None and record.get("scope_id") != query.scope_id:
                continue
            if (
                query.parent_run_id is not None
                and record.get("parent_run_id") != query.parent_run_id
            ):
                continue
            views.append(_run_view(run_id, record))
            if len(views) >= limit:
                break
        return tuple(views)

    def tree(self, root_run_id: str) -> RunTree:
        """A run and everything it invoked, nested as it was invoked.

        Raises:
            KeyError: there is no such run. A tree rooted at nothing is not an
                empty tree — it is a question about a run that never happened.
        """
        record = self._runs.get_run(root_run_id)
        if record is None:
            raise KeyError(root_run_id)
        return self._tree(root_run_id, record, seen={root_run_id})

    def _tree(self, run_id: str, record: dict[str, Any], *, seen: set[str]) -> RunTree:
        children = []
        for child in self._runs.children_of(run_id):
            child_id = str(child.get("run_id", ""))
            # A record whose `parent_run_id` points at an ancestor would
            # recurse forever. Documents are hand-editable, so this is a real
            # shape, not a defensive flourish.
            if not child_id or child_id in seen:
                continue
            seen.add(child_id)
            children.append(self._tree(child_id, child, seen=seen))
        return RunTree(run=_run_view(run_id, record), children=tuple(children))


def _run_view(run_id: str, record: dict[str, Any]) -> RunView:
    return RunView(
        run_id=run_id,
        job=str(record.get("job", "")),
        surface=str(record.get("surface", "")),
        status=str(record.get("status", "running")),
        started_at=_at(record.get("started_at")),
        scope_id=record.get("scope_id"),
        parent_run_id=record.get("parent_run_id"),
        invoke_depth=int(record.get("invoke_depth", 0) or 0),
        args_hash=record.get("args_hash"),
        ended_at=_parse(record.get("ended_at")),
    )


class _DocumentWorkflowReader:
    """`WorkflowReader` over `ScopeStore`."""

    def __init__(self, scopes: ScopeStore) -> None:
        self._scopes = scopes

    def workflow(self, scope_id: str) -> WorkflowView | None:
        record = self._scopes.get_scope(scope_id)
        return None if record is None else _workflow_view(scope_id, record)

    def resumable(self, query: WorkflowQuery) -> Sequence[WorkflowView]:
        views: list[WorkflowView] = []
        for scope_id in self._scopes.scope_ids():
            record = self._scopes.get_scope(scope_id)
            if record is None:
                continue
            if query.workflow is not None and record.get("workflow") != query.workflow:
                continue
            if query.status is not None and record.get("status") != query.status:
                continue
            views.append(_workflow_view(scope_id, record))
            if query.limit is not None and len(views) >= query.limit:
                break
        return tuple(views)

    def events_after(self, scope_id: str, seq: int) -> Sequence[EventView]:
        return tuple(
            EventView(
                seq=int(entry.get("seq", 0)),
                type=str(entry.get("type", "")),
                occurred_at=_at(entry.get("at") or entry.get("occurred_at")),
                payload=entry.get("payload"),
                run_id=entry.get("run_id"),
            )
            for entry in self._scopes.events_for(scope_id, after=seq)
        )


def _lease_record(record: dict[str, Any]) -> dict[str, Any]:
    """The lease sub-record, or an empty one when the scope was never claimed.

    A malformed lease reads as absent, exactly as `lease.read_lease` treats
    it: a scope nobody can ever evaluate is worse than one taken twice.
    """
    lease = record.get("lease")
    return lease if isinstance(lease, dict) else {}


def _workflow_view(scope_id: str, record: dict[str, Any]) -> WorkflowView:
    """A scope record as a `WorkflowView`.

    `created_at`, `updated_at` and `terminal_at` read as `None` unless the
    record carries them: the document schema has no such fields, and the
    columns arrive with FUN-19's tables (`06-data-model.md` §2). Inventing
    them from file mtimes would be a reader reconstructing what nothing
    recorded.
    """
    lease = _lease_record(record)
    return WorkflowView(
        scope_id=scope_id,
        workflow=str(record.get("workflow") or ""),
        status=str(record.get("status", "running")),
        position=record.get("position"),
        generation=lease.get("generation"),
        owner=lease.get("owner"),
        expires_at=_parse(lease.get("expires_at")),
        created_at=_parse(record.get("created_at")),
        updated_at=_parse(record.get("updated_at")),
        terminal_at=_parse(record.get("terminal_at")),
    )


class _DocumentInputReader:
    """`InputReader` over the gate records inside each scope.

    A gate record is this backend's input request: `SuspendAtGate` writes it
    and `ResumeWorkflow` consumes it. There is no `input_candidates` document,
    so a second deposit still overwrites the first here — defect B-2.4, which
    FUN-19's append-only table is what actually fixes.
    """

    def __init__(self, scopes: ScopeStore) -> None:
        self._scopes = scopes

    def open_for(self, scope_id: str) -> InputRequest | None:
        """The blocked walk's own gate — answered or not, but not yet consumed.

        `accepted` counts as open here and `consumed` does not, which is the
        difference between the two questions this port asks. A walk resuming
        needs to find the request *and* see that a candidate landed on it; a
        request whose answer has been walked past is finished, and returning
        it would let a resume consume the same answer twice.
        """
        for request in self._requests(scope_id):
            if request.status in ("open", "accepted"):
                return request
        return None

    def awaiting(self) -> Sequence[InputRequest]:
        """Every gate still waiting on a human or agent, workspace-wide.

        `open` only: once a candidate is deposited the request is no longer
        waiting on anybody, so listing it under "what is waiting on me" would
        ask for an answer that has already been given.
        """
        return tuple(
            request
            for scope_id in self._scopes.scope_ids()
            for request in self._requests(scope_id)
            if request.status == "open"
        )

    def _requests(self, scope_id: str) -> Sequence[InputRequest]:
        record = self._scopes.get_scope(scope_id)
        if record is None:
            return ()
        gates = record.get("gates")
        if not isinstance(gates, dict):
            return ()
        generation = int(_lease_record(record).get("generation", 0) or 0)
        return tuple(
            _input_request(scope_id, name, gate, generation)
            for name, gate in sorted(gates.items())
            if isinstance(gate, dict)
        )


def _input_request(
    scope_id: str, gate_name: str, gate: dict[str, Any], generation: int
) -> InputRequest:
    """One gate record as an `InputRequest`.

    Three of the five statuses are reachable here. `consumed` is written by
    `ResumeWorkflow`; `accepted` is a payload deposited and not yet walked
    past; everything else is `open`. `cancelled` and `expired` have no
    document shape and arrive with the request table.
    """
    if gate.get("consumed_at"):
        status = "consumed"
    elif gate.get("payload") is not None:
        status = "accepted"
    else:
        status = "open"
    return InputRequest(
        scope_id=scope_id,
        gate_name=gate_name,
        generation=generation,
        status=status,
        created_at=_at(gate.get("blocked_at")),
        schema=gate.get("input_schema"),
        prompt=gate.get("prompt"),
        resolved_at=_parse(gate.get("consumed_at")),
    )


# ------------------------------------------------------------------
# The write side. Every writer appends a value; nothing issues.
# ------------------------------------------------------------------


@dataclass(frozen=True)
class _AppendInput:
    """`InputWriter.append`, as a value — the port's one non-dataclass write."""

    request_id: str
    source: str
    payload: Any = None


@dataclass(frozen=True)
class _AppendEvent:
    """`EventWriter.append`, as a value."""

    type: str
    payload: Any = None
    run_id: str | None = None


@dataclass(frozen=True)
class _AppendEffect:
    """`EffectWriter.append`, as a value."""

    namespace: str
    topic: str
    payload: Any = None
    idempotency_key: str | None = None


class _DocumentRunWriter:
    """`RunWriter` — appends, never issues."""

    def __init__(self, txn: _DocumentTransaction) -> None:
        self._txn = txn

    def start_attempt(self, cmd: StartAttempt) -> None:
        self._txn.append(cmd)

    def finish_attempt(self, cmd: FinishAttempt) -> None:
        self._txn.append(cmd)


class _DocumentWorkflowWriter:
    """`WorkflowWriter` — appends, except `claim`.

    `claim` is specified as a single-command transaction that commits on the
    spot (`contracts.md` §1.3), which is what lets it answer with a value: a
    buffered claim could not, because at the moment it is called nothing has
    been written yet.
    """

    def __init__(self, txn: _DocumentTransaction) -> None:
        self._txn = txn

    def claim(self, cmd: ClaimWorkflow) -> Claimed | Conflict:
        """Take the scope now, and answer with the outcome.

        Losing is a value, never an exception: `ScopeStore.claim_scope` raises
        `LeaseHeldError`, and translating it here is the whole of acceptance
        criterion 6 at this store (the call sites move at T14).
        """
        scopes = self._txn.scopes
        scopes.ensure_scope(cmd.scope_id)
        try:
            lease = scopes.claim_scope(
                cmd.scope_id,
                owner=cmd.owner,
                seconds=cmd.lease_seconds,
                force=cmd.force,
                now=cmd.now,
            )
        except LeaseHeldError as held:
            current = scopes.get_lease(cmd.scope_id)
            return Conflict(
                scope_id=cmd.scope_id,
                held_by=held.owner,
                held_generation=current.generation if current else 0,
            )
        self._txn.touch(cmd.scope_id)
        return Claimed(
            scope_id=cmd.scope_id,
            generation=lease.generation,
            expires_at=_at(lease.expires_at),
        )

    def complete_step(self, cmd: CompleteStep) -> None:
        self._txn.append(cmd)

    def suspend(self, cmd: SuspendAtGate) -> None:
        self._txn.append(cmd)

    def resume(self, cmd: ResumeWorkflow) -> None:
        self._txn.append(cmd)

    def cancel(self, cmd: CancelWorkflow) -> None:
        self._txn.append(cmd)

    def write_state(self, cmd: StateBatch) -> None:
        self._txn.append(cmd)


class _DocumentInputWriter:
    """`InputWriter` — appends, never issues."""

    def __init__(self, txn: _DocumentTransaction) -> None:
        self._txn = txn

    def append(self, request_id: str, source: str, payload: Any = None) -> None:
        self._txn.append(_AppendInput(request_id, source, payload))


class _DocumentEventWriter:
    """`EventWriter` — appends, never issues."""

    def __init__(self, txn: _DocumentTransaction) -> None:
        self._txn = txn

    def append(self, type: str, payload: Any = None, run_id: str | None = None) -> None:
        self._txn.append(_AppendEvent(type, payload, run_id))


class _DocumentEffectWriter:
    """`EffectWriter` — appends, and refuses on commit.

    There is no outbox document in this backend, which is what
    `durable_outbox=False` declares and what keeps this store from being
    selected by a feature that needs one at all (`05-the-design.md` §5: "a
    store that declares `durable_outbox=False` does not run the outbox suite
    and does not get to be selected by a feature that needs one"). Reaching
    this writer therefore means the capability check at boot (T13) did not
    run or did not hold, and dropping the intent silently would lose the one
    record that says a side effect was intended.
    """

    def __init__(self, txn: _DocumentTransaction) -> None:
        self._txn = txn

    def append(
        self,
        namespace: str,
        topic: str,
        payload: Any = None,
        idempotency_key: str | None = None,
    ) -> None:
        self._txn.append(_AppendEffect(namespace, topic, payload, idempotency_key))


# ------------------------------------------------------------------
# The transaction. Accumulates, applies once on a clean exit.
# ------------------------------------------------------------------


class _DocumentTransaction:
    """`RuntimeTransaction` over the document stores.

    Writers append command values and issue nothing; `apply` runs once, from
    `DocumentRuntimeStore.transaction`'s clean exit, and an exception inside
    the block discards the whole batch without touching a file.

    **One aggregate per unit.** `DOCUMENT_PROFILE.cross_aggregate_atomicity`
    is `False` because two documents have two locks and cannot roll back
    together. The refusal that enforces it — raised on commit, naming every
    aggregate the unit spanned, having applied none — is `_refuse_spanning_units`,
    and `scopes_touched` is the evidence it reads.
    """

    def __init__(self, store: DocumentRuntimeStore) -> None:
        self._store = store
        self._commands: list[Any] = []
        self.scopes_touched: set[str] = set()
        self.runs: RunWriter = _DocumentRunWriter(self)
        self.workflows: WorkflowWriter = _DocumentWorkflowWriter(self)
        self.inputs: InputWriter = _DocumentInputWriter(self)
        self.events: EventWriter = _DocumentEventWriter(self)
        self.effects: EffectWriter = _DocumentEffectWriter(self)

    @property
    def scopes(self) -> ScopeStore:
        return self._store.scope_store

    @property
    def run_store(self) -> RunStore:
        return self._store.run_store

    def append(self, command: Any) -> None:
        self._commands.append(command)
        scope_id = getattr(command, "scope_id", None)
        if isinstance(scope_id, str):
            self.touch(scope_id)

    def touch(self, scope_id: str) -> None:
        self.scopes_touched.add(scope_id)

    # -- applying ---------------------------------------------------

    def apply(self) -> None:
        """Write every accumulated command, in the order it was issued.

        Each document is opened at most once, lazily: a unit that only touches
        runs never takes the scopes lock. Both batches write on their own
        clean exit, so a refusal raised part-way discards everything that
        document had accumulated.
        """
        if not self._commands:
            return
        self._refuse_spanning_units()
        with ExitStack() as stack:
            opened: dict[str, Any] = {}

            def scopes() -> ScopeStore:
                if "scopes" not in opened:
                    opened["scopes"] = stack.enter_context(self.scopes.batch())
                return self.scopes

            def runs() -> RunStore:
                if "runs" not in opened:
                    opened["runs"] = stack.enter_context(self.run_store.batch())
                return self.run_store

            for command in self._commands:
                self._apply_one(command, scopes, runs)

    def _refuse_spanning_units(self) -> None:
        """Refuse a unit spanning two aggregates before anything is applied.

        Acceptance criterion 2 (T8). `scopes_touched` is the evidence — the
        same set the event-append cardinality check reads — and the refusal
        runs here, at commit, rather than in `append`: a check at append time
        would have to fire after some commands were already buffered, and the
        criterion exists so that no ordering of a spanning unit can leave one
        aggregate written and the other not. Applying it in parts is defect
        B3 with a new name.

        Claims are exempt because they are not part of a batch at all: each
        commits on the spot as a single-command transaction, which is what
        lets `claim` answer with a value. A unit whose only writes were
        claims carries no commands and never reaches this check.
        """
        if self._store.profile.cross_aggregate_atomicity:
            return
        if len(self.scopes_touched) < 2:
            return
        raise CrossAggregateRefusedError(sorted(self.scopes_touched))

    def _apply_one(self, command: Any, scopes: Any, runs: Any) -> None:
        if isinstance(command, CompleteStep):
            self._complete_step(command, scopes())
        elif isinstance(command, SuspendAtGate):
            self._suspend(command, scopes())
        elif isinstance(command, ResumeWorkflow):
            self._resume(command, scopes())
        elif isinstance(command, CancelWorkflow):
            self._cancel(command, scopes())
        elif isinstance(command, StateBatch):
            self._write_state(command, scopes())
        elif isinstance(command, StartAttempt):
            self._start_attempt(command, runs())
        elif isinstance(command, FinishAttempt):
            self._finish_attempt(command, runs())
        elif isinstance(command, _AppendInput):
            self._append_input(command, scopes())
        elif isinstance(command, _AppendEvent):
            self._append_event(command, scopes, runs)
        elif isinstance(command, _AppendEffect):
            raise NotImplementedError(
                f"{DOCUMENT_PROFILE.name!r} has no outbox, so the effect "
                f"{command.namespace}/{command.topic} cannot be recorded "
                f"durably. This store declares durable_outbox=False; a "
                f"feature needing one must select a store that has one "
                f"(FUN-19). Refused rather than dropped: an unrecorded "
                f"intent is a side effect nobody can replay."
            )
        else:  # pragma: no cover - the union above is closed
            raise TypeError(f"unknown command {type(command).__name__}")

    @contextmanager
    def _held(
        self, scopes: ScopeStore, scope_id: str, generation: int
    ) -> Iterator[None]:
        """Fence this store's writes to `scope_id` for the duration.

        `ScopeStore` enforces fencing from a hold kept on the store object
        (`_mutate`, `_fenced_state`), so a command carrying a generation has to
        install it rather than pass it. Restored afterwards: the store outlives
        this transaction and a hold left behind would fence the next caller —
        including a CLI read that holds nothing and must never be refused.
        """
        previous = scopes.generation_for(scope_id)
        scopes.hold(scope_id, generation)
        try:
            yield
        finally:
            scopes.hold(scope_id, previous)

    def _complete_step(self, cmd: CompleteStep, scopes: ScopeStore) -> None:
        with self._held(scopes, cmd.scope_id, cmd.generation):
            scopes.record_step(
                cmd.scope_id,
                cmd.step_key,
                {
                    "status": cmd.status,
                    "result": cmd.result,
                    "iteration": cmd.iteration,
                    "at": _iso(cmd.now),
                },
            )
            if cmd.decision_key is not None and cmd.chosen_target is not None:
                scopes.record_branch(cmd.scope_id, cmd.decision_key, cmd.chosen_target)
            scopes.set_position(cmd.scope_id, cmd.position)
            scopes.set_scope_status(cmd.scope_id, cmd.scope_status)

    def _suspend(self, cmd: SuspendAtGate, scopes: ScopeStore) -> None:
        with self._held(scopes, cmd.scope_id, cmd.generation):
            scopes.put_gate(
                cmd.scope_id,
                cmd.gate_name,
                {
                    "input_schema": cmd.schema,
                    "prompt": cmd.prompt,
                    "payload": None,
                    "blocked_at": _iso(cmd.now),
                },
            )
            scopes.set_position(cmd.scope_id, cmd.position)
            scopes.set_scope_status(cmd.scope_id, "blocked")

    def _resume(self, cmd: ResumeWorkflow, scopes: ScopeStore) -> None:
        """Consume the accepted request and reclaim at a **new** generation.

        One unit, which is the point of the command: today the deposit
        (`app/_workflow_answer.py`) and the claim (`_engine/frontier.py`)
        are two locked writes in different call frames (`06-data-model.md`
        §4). `claim_scope` still raises here rather than answering —
        `resume` returns `None` by the port, so there is no value to answer
        with.
        """
        gate = scopes.get_gate(cmd.scope_id, cmd.gate_name)
        if gate is not None:
            scopes.put_gate(
                cmd.scope_id,
                cmd.gate_name,
                {**gate, "consumed_at": _iso(cmd.now)},
            )
        scopes.claim_scope(
            cmd.scope_id,
            owner=cmd.owner,
            seconds=cmd.lease_seconds,
            force=cmd.force,
            now=cmd.now,
        )
        scopes.set_scope_status(cmd.scope_id, "running")

    def _cancel(self, cmd: CancelWorkflow, scopes: ScopeStore) -> None:
        """Move a non-terminal scope to `cancelled`.

        The guard is "holds the current generation **or** explicit force", and
        `force` is what skips the hold — an operator cancelling a scope whose
        runner is gone holds nothing.
        """
        with self._held(scopes, cmd.scope_id, 0 if cmd.force else cmd.generation):
            if cmd.force:
                scopes.hold(cmd.scope_id, None)
            scopes.set_scope_status(cmd.scope_id, "cancelled")
            scopes.append_event(
                cmd.scope_id,
                {
                    "type": "workflow.cancelled",
                    "at": _iso(cmd.now),
                    "payload": {"reason": cmd.reason} if cmd.reason else None,
                },
            )

    def _write_state(self, cmd: StateBatch, scopes: ScopeStore) -> None:
        """Upsert and delete one scope's state keys under the fence.

        `ScopeStore.state_batch` checks the hold on entry and again at the exit
        write, so a claim that lands mid-block discards the block rather than
        committing state the new holder has already invalidated.
        """
        with (
            self._held(scopes, cmd.scope_id, cmd.generation),
            scopes.state_batch(cmd.scope_id) as state,
        ):
            for key, value in cmd.upserts.items():
                state.set(key, value)
            for key in cmd.deletes:
                state.delete(key)

    def _start_attempt(self, cmd: StartAttempt, runs: RunStore) -> None:
        """Open a run and its first attempt as one transition.

        The store mints the identity and this port does not hand it back —
        every writer but `claim` returns `None` (`contracts.md` §1.3), so a
        recorder that needs the id supplies it another way. `attempts` is a
        list on the run record: a retry appends rather than overwriting, which
        is what makes "how many times did this fail before it worked"
        answerable at all on documents.
        """
        runs.open_run(
            {
                "job": cmd.job,
                "surface": cmd.surface,
                "scope_id": cmd.scope_id,
                "parent_run_id": cmd.parent_run_id,
                "invoke_depth": cmd.invoke_depth,
                "args_hash": cmd.args_hash,
                "started_at": _iso(cmd.now),
                "attempts": [
                    {
                        "attempt_no": 1,
                        "status": "running",
                        "started_at": _iso(cmd.now),
                    }
                ],
            }
        )

    def _finish_attempt(self, cmd: FinishAttempt, runs: RunStore) -> None:
        """Record how one attempt ended, and the run's outcome when terminal.

        A run this store never opened is ignored, exactly as `close_run` does:
        the log is an observation, and raising would turn a lost observation
        into a failed run.
        """
        record = runs.get_run(cmd.run_id)
        if record is None:
            return
        attempts = [
            dict(entry)
            for entry in record.get("attempts", [])
            if isinstance(entry, dict)
        ]
        for entry in attempts:
            if entry.get("attempt_no") == cmd.attempt_no:
                entry.update(
                    status=cmd.status,
                    ended_at=_iso(cmd.now),
                    failure_code=cmd.failure_code,
                    failure_detail=cmd.failure_detail,
                )
                break
        else:
            attempts.append(
                {
                    "attempt_no": cmd.attempt_no,
                    "status": cmd.status,
                    "started_at": _iso(cmd.now),
                    "ended_at": _iso(cmd.now),
                    "failure_code": cmd.failure_code,
                    "failure_detail": cmd.failure_detail,
                }
            )
        # `ended_at` is passed rather than left to `close_run`, which stamps
        # its own wall clock: the command carries the moment the engine
        # observed, and the engine owns transition meaning (ADR-025).
        runs.close_run(
            cmd.run_id,
            cmd.status,
            ended_at=_iso(cmd.now),
            attempts=attempts,
            failure_code=cmd.failure_code,
        )

    def _append_input(self, cmd: _AppendInput, scopes: ScopeStore) -> None:
        """Deposit a candidate against an open gate.

        `request_id` is `<scope_id>::<gate_name>` here, because the document
        backend has no request table to mint an id in — the gate record *is*
        the request. `source` is recorded beside the payload rather than
        dropped: who answered is the question an audit asks first.
        """
        scope_id, _, gate_name = cmd.request_id.partition("::")
        gate = scopes.get_gate(scope_id, gate_name)
        if gate is None:
            raise KeyError(cmd.request_id)
        scopes.put_gate(
            scope_id,
            gate_name,
            {**gate, "payload": cmd.payload, "source": cmd.source},
        )

    def _append_event(self, cmd: _AppendEvent, scopes: Any, runs: Any) -> None:
        """Append to the run log when the event names a run, else the scope's.

        The port's `run_id` is optional because scope events and run events
        share one shape. Which log an event without a run belongs to is
        therefore decided by what this unit is about — and a unit is about one
        scope, which is what `cross_aggregate_atomicity=False` already says.

        Raises:
            ValueError: no run named and no scope touched, so there is no log
                this event belongs to.
        """
        entry = {"type": cmd.type, "payload": cmd.payload, "at": _iso(_utcnow())}
        if cmd.run_id is not None:
            runs().append_event(cmd.run_id, entry)
            return
        if len(self.scopes_touched) != 1:
            raise ValueError(
                f"event {cmd.type!r} names no run and this transaction touched "
                f"{sorted(self.scopes_touched)} — there is no single log it "
                f"belongs to."
            )
        (scope_id,) = self.scopes_touched
        scopes().append_event(scope_id, {**entry, "run_id": cmd.run_id})


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------
# The store.
# ------------------------------------------------------------------


# TRANSITIONAL(FUN-17/T7): a declared middle man over the three document
# stores, so this wave can land without FUN-19's `SqliteRuntimeStore`. It
# forwards and adds no behaviour of its own beyond the profile, the buffering
# transaction and T8's refusal. FUN-19 removes it, and this file with it.
class DocumentRuntimeStore:
    """`RuntimeStore` over `ScopeStore`, `RunStore` and `ScopeStateStore`.

    Constructed once, by `_app`, after config resolves (ADR-027, wired at
    T11). It owns the three document stores it wraps and hands out readers
    that answer questions off them and transactions that accumulate commands
    and apply them on a clean exit.

    `profile` is `DOCUMENT_PROFILE` and is the only place a capability is
    declared: nothing here probes, and boot refuses rather than degrades when
    a feature needs a capability this store does not have (T13).
    """

    profile: StoreProfile = DOCUMENT_PROFILE

    def __init__(self, substrate: StoreSubstrate) -> None:
        self.scope_store = ScopeStore(substrate)
        self.run_store = RunStore(substrate)
        self.runs: RunReader = _DocumentRunReader(self.run_store)
        self.workflows: WorkflowReader = _DocumentWorkflowReader(self.scope_store)
        self.inputs: InputReader = _DocumentInputReader(self.scope_store)

    @contextmanager
    def transaction(self) -> Iterator[RuntimeTransaction]:
        """One short transition, applied once on a clean exit.

        NEVER wrap a job body, a prompt or a network effect in this: user code
        may run for hours, and the documents' locks are held for the whole
        `apply`.
        """
        txn = _DocumentTransaction(self)
        yield txn
        txn.apply()

    def close(self) -> None:
        """Release what this store holds — which here is nothing.

        Not a stub standing in for missing work: the document substrate opens
        a file per operation and closes it, so there is no cached handle to
        release. The method exists because the *port* needs the lifecycle —
        `SQLiteSubstrate` caches one connection per thread in
        `threading.local()` and nothing closes them, and FUN-19's store is
        where that finally has an answer.
        """
        return
