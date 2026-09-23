"""The persistence vocabulary — capability, commands, outcomes, views.

FUN-17 (waves 0–1). One module, read as a unit: ``_types/commands.py`` is
already taken by the shell's runtime command tree, and putting ``ClaimWorkflow``
beside ``CommandNode`` would collide two unrelated meanings of "command" in one
module name, so the whole persistence contract lives here.

Zero logic, values only. Every dataclass here is frozen and made of plain
values — a command is data a recorder hands to a store, not a call, and being a
value is what lets a transaction accumulate commands in a list and apply them as
one unit on exit (the shape a backend with no ``BEGIN``, such as Cloudflare D1,
can implement at all). The ``Protocol`` surfaces at the end of the file add
method signatures and nothing that executes.

The ports that speak these values are specified in
``.spec/features/runtime-persistence-ports/contracts.md`` §1.5. The five writer
and three reader protocols are here (FUN-17 T4–T5); ``RuntimeStore`` and
``RuntimeTransaction`` land with T6, which is where the accumulating transaction
is documented. Nothing calls these ports yet — the production call paths arrive
with T7–T14, so a port existing is not yet a port being reachable.

This module lives in ``_types`` and therefore imports nothing internal, the
standard library only (import-linter contract "Types import nothing internal").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

__all__ = [
    "StoreProfile",
    # Commands
    "ClaimWorkflow",
    "CompleteStep",
    "SuspendAtGate",
    "ResumeWorkflow",
    "CancelWorkflow",
    "StateBatch",
    "StartAttempt",
    "FinishAttempt",
    # Outcomes
    "Claimed",
    "Conflict",
    "Resumed",
    "CancelResult",
    "Attempt",
    "InputRequest",
    # Views and queries
    "RunView",
    "WorkflowView",
    "EventView",
    "RunTree",
    "RunQuery",
    "WorkflowQuery",
    # Ports — writers, then readers
    "RunWriter",
    "WorkflowWriter",
    "InputWriter",
    "EventWriter",
    "EffectWriter",
    "RunReader",
    "WorkflowReader",
    "InputReader",
]


# ------------------------------------------------------------------
# Capability as data
# ------------------------------------------------------------------


@dataclass(frozen=True)
class StoreProfile:
    """What this store can actually promise. Checked at boot, never probed.

    The authority for every field's value across the eight measured backends is
    ``contributor/reference/substrate-capability-matrix.md``; nothing here is
    re-derived from vendor documentation. A feature declares what it needs and
    boot refuses rather than degrading — a silent downgrade is the failure mode
    this type exists to make impossible.
    """

    name: str
    #: Can two aggregates commit in one transaction that rolls back together?
    cross_aggregate_atomicity: bool
    #: "none" — writes are not fenced at all; "process-local" — fenced only
    #: within the object that holds the generation; "cross-process" — a stale
    #: writer cannot commit from any process. The three values are the probe's
    #: own (``tests/substrate_probe/harness.py`` keeps the same tuple); keep
    #: them identical so a probe reading and a shipped declaration are
    #: comparable without translation.
    fencing: Literal["none", "process-local", "cross-process"]
    #: Can two OS processes use this store at once without corrupting it?
    multi_process: bool
    #: Can two different machines?
    multi_machine: bool
    #: Does a committed state change and the record that it happened land
    #: together, surviving a crash between them?
    durable_outbox: bool
    #: Is there a schema version the store enforces on boot?
    versioned_migrations: bool
    #: Can a transaction hold statements open across a Python decision?
    #: Cloudflare D1 cannot: no BEGIN/COMMIT, one ``batch`` per atomic unit.
    interactive_transaction: bool
    #: Does every operation cross a network? Decides whether the engine may
    #: read-modify-write in a loop or must buffer and flush once.
    remote: bool
    #: Largest single document the backend accepts, as measured. ``None``
    #: means "nothing refused what was attempted" — the matrix's *unbounded*
    #: footnote — and is **not** a claim that no limit exists.
    max_document_bytes: int | None
    #: Does this store work with no network at all? The offline binary is the
    #: reason the binary exists (ADR-015), and today nothing states this.
    offline_capable: bool
    #: Free text for an operator: where the data is, what it costs.
    description: str = ""


# ------------------------------------------------------------------
# Commands — what a recorder hands a store. Values, never calls.
#
# Every command that mutates a scope already held carries the held
# ``generation``, so fencing is enforced in the store's predicate rather than
# remembered by a caller. ``ClaimWorkflow`` and ``ResumeWorkflow`` carry none
# because they *acquire* the generation — there is nothing to hold yet — and
# ``StartAttempt`` / ``FinishAttempt`` carry none because a run is a different
# aggregate from the scope lease, so there is no scope generation to fence it
# against.
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimWorkflow:
    """Take a workflow scope, fencing every later write this walk makes.

    A single-command transaction that commits on the spot, which is why
    ``claim`` is the one writer allowed to return something read back.
    """

    scope_id: str
    owner: str
    now: datetime
    lease_seconds: float
    #: Only for an explicit reclaim, where a human has decided the holder
    #: is gone.
    force: bool = False


@dataclass(frozen=True)
class CompleteStep:
    """One step's outcome, and the scope's advance to its next position.

    Mid-walk the scope stays ``running``; reaching END makes it ``completed``
    and a terminal failure makes it ``failed``. Which of those this is, is the
    engine's decision (ADR-025: the engine owns transition meaning, stores own
    durability) — the command carries the resulting scope status as a value so
    the store never has to contain the word "resume" in a conditional.
    """

    scope_id: str
    generation: int
    step_key: str
    now: datetime
    #: A loop revisits a step key; iteration distinguishes the visits and is
    #: 0 for the first pass (``_engine/loop_state`` counts from zero).
    iteration: int = 0
    #: One of the step markers — ``success``, ``failed``, ``timed_out``,
    #: ``cancelled`` — as the walk observed it.
    status: str = "success"
    #: The step's return value, opaque to the store.
    result: Any = None
    #: A branch choice made inside the step, recorded immutably when present:
    #: both fields are set together or neither is.
    decision_key: str | None = None
    chosen_target: str | None = None
    #: The scope's next position; ``None`` when the walk has no next node.
    position: str | None = None
    #: The scope's status after this step — ``running`` mid-walk,
    #: ``completed`` or ``failed`` when terminal.
    scope_status: str = "running"


@dataclass(frozen=True)
class SuspendAtGate:
    """Stop a scope at a gate and open the input request that pauses it.

    Applying this moves the scope to ``blocked``; collecting the human or
    agent input happens outside any transaction.
    """

    scope_id: str
    generation: int
    gate_name: str
    #: The node the scope stopped at.
    position: str
    now: datetime
    #: The input schema the gate asks with, opaque to the store.
    schema: Any = None
    #: The prompt presented to whoever answers, opaque to the store.
    prompt: Any = None


@dataclass(frozen=True)
class ResumeWorkflow:
    """Consume an accepted input request and reclaim the scope it paused.

    Resume is a claim at a **new** generation, one transaction — today the
    deposit and the claim are two locked writes in different call frames, and
    the window between them is why this command exists. Acquisition-shaped
    like ``ClaimWorkflow``: no held generation, because it takes one.
    """

    scope_id: str
    owner: str
    gate_name: str
    now: datetime
    lease_seconds: float
    force: bool = False


@dataclass(frozen=True)
class CancelWorkflow:
    """Move a non-terminal scope to ``cancelled``.

    The state machine's guard is "holds the current generation **or**
    explicit force" — the command carries both, so an unfenced cancel (the
    defect ``app/_workflow_control.py``'s bare ``except`` hides today) has no
    shape to arrive in. A terminal scope is refused on commit; it is never
    mutated.
    """

    scope_id: str
    generation: int
    now: datetime
    force: bool = False
    reason: str = ""


@dataclass(frozen=True)
class StateBatch:
    """Upsert and delete one scope's state keys under the fence.

    Every write carries the held generation in the store's predicate, which is
    what makes a stale writer's update match zero rows structurally rather
    than by a caller remembering to check. Arguments are hashes only, never
    values — argument content is a redaction and retention decision that
    belongs to someone else.
    """

    scope_id: str
    generation: int
    now: datetime
    upserts: Mapping[str, Any]
    deletes: Sequence[str] = ()


@dataclass(frozen=True)
class StartAttempt:
    """Open a run and its first attempt as one transition.

    ``start_attempt`` and not ``start_run``: an attempt is one execution of a
    job body, a run is the logical unit the user asked for, and a retry
    inserts the next attempt rather than overwriting — which is what makes
    "how many times did this fail before it worked" answerable. The store
    mints the run and attempt identity; this port does not hand it back, since
    every writer but ``claim`` returns ``None`` (``contracts.md`` §1.3).
    """

    job: str
    surface: str
    now: datetime
    scope_id: str | None = None
    parent_run_id: str | None = None
    invoke_depth: int = 0
    #: A hash of the arguments, never the arguments.
    args_hash: str | None = None


@dataclass(frozen=True)
class FinishAttempt:
    """Record how one attempt ended, and the run's outcome when terminal.

    The attempt's own outcome is final here; the run's status is derived from
    its last attempt plus its cancellation flag, and the store settles both in
    the one commit. Rendering and EventBus notification run outside the
    transaction.
    """

    run_id: str
    attempt_no: int
    status: str
    now: datetime
    failure_code: str | None = None
    #: Structured failure detail, opaque to the store.
    failure_detail: Any = None


# ------------------------------------------------------------------
# Outcomes — values a caller branches on. Losing a claim is an
# expected outcome of a concurrent system, not an error (ADR-025's
# vocabulary; the exception form it replaces is `LeaseHeldError`).
# ------------------------------------------------------------------


@dataclass(frozen=True)
class Claimed:
    """The claim succeeded: this walk now holds the generation."""

    scope_id: str
    generation: int
    expires_at: datetime


@dataclass(frozen=True)
class Conflict:
    """The claim was refused: someone else holds the scope.

    A value, never an exception. Names the holder and the held generation —
    the reader's question on hitting it is always *who, and how stale am I*.
    """

    scope_id: str
    held_by: str
    held_generation: int


@dataclass(frozen=True)
class Resumed:
    """The resume succeeded: the request was consumed and a new generation
    taken, so writes from the suspended walk are now fenced out."""

    scope_id: str
    generation: int
    expires_at: datetime


@dataclass(frozen=True)
class CancelResult:
    """The cancel succeeded: the scope is terminal as of ``terminal_at``."""

    scope_id: str
    generation: int
    terminal_at: datetime


@dataclass(frozen=True)
class Attempt:
    """One execution of a job body, identified inside its run.

    Vocabulary only in this wave — nothing renders it yet, and what a failed
    twice-then-succeeded run shows a user is D-6's to decide. A retry never
    mutates a terminal attempt; it inserts the next one, same ``run_id``.
    """

    run_id: str
    attempt_no: int
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    failure_code: str | None = None
    failure_detail: Any = None


@dataclass(frozen=True)
class InputRequest:
    """A gate's question, and where its answer stands.

    One OPEN request per scope, gate and generation. Consumption is a write
    (``consumed``, not a silent read): a replayed read is idempotent, but the
    moment an agent rather than a human can deposit a second candidate, "was
    this answer used?" stops being benign to leave unrecorded.
    """

    scope_id: str
    gate_name: str
    generation: int
    #: ``open``, ``accepted``, ``consumed``, ``cancelled`` or ``expired``.
    status: str
    created_at: datetime
    schema: Any = None
    prompt: Any = None
    resolved_at: datetime | None = None


# ------------------------------------------------------------------
# Views and queries — the read side. Readers are named for questions,
# not get/list/find; these are the values they answer with.
# ------------------------------------------------------------------


@dataclass(frozen=True)
class RunView:
    """A run as history sees it: identity, placement and outcome.

    Derived display states (``stalled``, ``abandoned`` and friends) are
    functions of the lease clock and are never stored or carried here.
    """

    run_id: str
    job: str
    surface: str
    status: str
    started_at: datetime
    scope_id: str | None = None
    parent_run_id: str | None = None
    invoke_depth: int = 0
    args_hash: str | None = None
    ended_at: datetime | None = None


@dataclass(frozen=True)
class WorkflowView:
    """A workflow scope as a reader finds it, lease included.

    ``generation`` is ``None`` when the scope has never been claimed. The
    stored status is one of the state machine's four; everything a user
    sees beyond them is derived at render time.
    """

    scope_id: str
    workflow: str
    status: str
    position: str | None = None
    generation: int | None = None
    owner: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    terminal_at: datetime | None = None


@dataclass(frozen=True)
class EventView:
    """One append-only event, at its sequence number.

    Events answer "what happened after point N" — the sequence is the
    contract, and no event is ever rewritten.
    """

    seq: int
    type: str
    occurred_at: datetime
    payload: Any = None
    #: The run whose step produced this event, when one did.
    run_id: str | None = None


@dataclass(frozen=True)
class RunTree:
    """A run and everything it invoked, nested as it was invoked."""

    run: RunView
    children: tuple[RunTree, ...] = ()


@dataclass(frozen=True)
class RunQuery:
    """Filters for "what ran recently". ``None`` means "do not filter"."""

    job: str | None = None
    status: str | None = None
    scope_id: str | None = None
    parent_run_id: str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class WorkflowQuery:
    """Filters for "what can I resume". ``None`` means "do not filter"."""

    workflow: str | None = None
    status: str | None = None
    limit: int | None = None


# ------------------------------------------------------------------
# The writer ports — what a transaction hands commands to.
#
# A writer takes a command value and returns ``None``: at the moment a
# buffered writer is called nothing has been written yet, so there is nothing
# to read back (``contracts.md`` §1.3). ``WorkflowWriter.claim`` is the one
# exception, specified as a single-command transaction that commits on the
# spot — losing a claim is an expected outcome of a concurrent system, so it
# answers with a value instead of raising.
# ------------------------------------------------------------------


@runtime_checkable
class RunWriter(Protocol):
    """The runs-and-attempts aggregate, written.

    Two commands, both issued by a recorder (``_engine/recording/``, T9): a run
    is opened once and attempts are appended to it, never mutated in place.
    """

    def start_attempt(self, cmd: StartAttempt) -> None: ...

    def finish_attempt(self, cmd: FinishAttempt) -> None: ...


@runtime_checkable
class WorkflowWriter(Protocol):
    """The workflow scope aggregate, written.

    ``claim`` is the only method in the whole writer contract that answers with
    something read back; everything else returns ``None``.
    """

    def claim(self, cmd: ClaimWorkflow) -> Claimed | Conflict: ...

    def complete_step(self, cmd: CompleteStep) -> None: ...

    def suspend(self, cmd: SuspendAtGate) -> None: ...

    def resume(self, cmd: ResumeWorkflow) -> None: ...

    def cancel(self, cmd: CancelWorkflow) -> None: ...

    def write_state(self, cmd: StateBatch) -> None: ...


@runtime_checkable
class InputWriter(Protocol):
    """The inputs aggregate, appended to.

    Append-only in fact, not only in shape: a second candidate never overwrites
    the first (``06-data-model.md`` §2.4 — today's overwrite is the defect it
    names). The request row itself is opened by ``SuspendAtGate``, and
    accepting a candidate is ``WorkflowWriter.resume``'s job; neither is this
    port's.
    """

    def append(self, request_id: str, source: str, payload: Any = None) -> None: ...


@runtime_checkable
class EventWriter(Protocol):
    """The append-only event streams, appended to.

    Scope events and run events share this shape, which is why ``run_id`` is
    optional: it names the run whose step produced the event when one did. The
    store assigns ``seq`` and nothing rewrites a row, which is what makes "what
    happened after point N" answerable.
    """

    def append(
        self, type: str, payload: Any = None, run_id: str | None = None
    ) -> None: ...


@runtime_checkable
class EffectWriter(Protocol):
    """The outbox, appended to — an intent to reach the outside world.

    Recording the intent is all that happens inside the transaction: claiming a
    row, calling the provider and acknowledging the result run outside it
    (``06-data-model.md`` §4), which is the difference between an outbox and a
    retry loop. ``idempotency_key`` is optional because the column is unique
    only *where present*.
    """

    def append(
        self,
        namespace: str,
        topic: str,
        payload: Any = None,
        idempotency_key: str | None = None,
    ) -> None: ...


# ------------------------------------------------------------------
# The reader ports — questions, never get/list/find.
#
# A caller asks a question and a backend answers it however it can: an index, a
# document read, a network round trip. Naming them for questions is what keeps
# a caller from discovering *how* it was answered with ``hasattr``, which is how
# a port degrades back into a capability probe.
# ------------------------------------------------------------------


@runtime_checkable
class RunReader(Protocol):
    """Questions about runs and their attempts."""

    def run(self, run_id: str) -> RunView | None: ...

    def recent(self, query: RunQuery) -> Sequence[RunView]: ...

    def tree(self, root_run_id: str) -> RunTree: ...


@runtime_checkable
class WorkflowReader(Protocol):
    """Questions about scopes: what can I resume, and what happened since."""

    def workflow(self, scope_id: str) -> WorkflowView | None: ...

    def resumable(self, query: WorkflowQuery) -> Sequence[WorkflowView]: ...

    def events_after(self, scope_id: str, seq: int) -> Sequence[EventView]: ...


@runtime_checkable
class InputReader(Protocol):
    """Questions about gates waiting on an answer.

    ``open_for`` is the blocked walk asking about its own gate; ``awaiting`` is
    the workspace-wide question a human-facing surface asks ("what is waiting on
    me"). One OPEN request per scope, gate and generation is the invariant both
    read against.
    """

    def open_for(self, scope_id: str) -> InputRequest | None: ...

    def awaiting(self) -> Sequence[InputRequest]: ...
