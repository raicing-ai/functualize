"""Runtime frontier expansion — push mode over the shared graph (§D.7a).

The engine needs **two modes over one graph model**, which is why this ships in
S3 rather than being retrofitted when the S4 walker arrives:

- **Pull mode** (:mod:`functualize._engine.scheduler`) — schedule the whole DAG
  up front. Dependencies know their full shape at registration.
- **Push mode** (this module) — expand the frontier as nodes complete. A
  ``ConditionalEdge``'s target is *unknowable* until its source returns, so
  upfront scheduling is impossible for workflows.

Three more §D.7 constraints are honored here rather than bolted on later:

- **(b)** A node can be ``BLOCKED`` awaiting input, joining the guard states.
- **(c)** Walk position and gate payloads persist in the state store, so a
  blocked walk survives the process that created it.
- **(d)** Per-scope step records key ``(scope_id, job_name, args_hash)``, and a
  **branch choice is recorded on first evaluation and read on replay** — a
  non-deterministic condition must not send a resumed walk down a different
  branch than the one it paused on.

The walker itself lands in S4; this is the engine it will sit on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from functualize._engine.recording import InputRecorder
from functualize._types.gate_resolution import (
    EvaluationOutcome,
    GateResolution,
)

# At runtime, not under TYPE_CHECKING: `claim` branches on it with
# `isinstance`, so a type-only import would be a NameError on every claim.
from functualize._types.persistence import (
    CompleteStep,
    Conflict,
    MoveScope,
    RecordBranch,
    RecordStep,
    ReleaseLease,
    RenewLease,
    StartWalk,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from functualize._types.gate_resolution import GateCandidate
    from functualize._types.persistence import (
        Claimed,
        RuntimeStore,
        StepView,
        WorkflowView,
    )

__all__ = [
    "END",
    "TERMINAL_SUCCESS",
    "FrontierWalk",
    "GraphModel",
    "StepStatus",
    "WalkState",
]

# Terminal sentinel: an edge to END finishes the walk rather than naming a node.
END = "__end__"


@dataclass(frozen=True)
class GraphModel:
    """A workflow graph in the shape both modes consume.

    Attributes:
        entry: The node the walk starts at.
        edges: ``{source: [targets]}`` — unconditional successors.
        conditional: ``{source: {choice_key: target}}`` — successors chosen at
            runtime from the source's result.
        effecting: Node names declared `Step(..., effecting=True)`. A set, not
            a flag on each node, because that is the question the walk asks:
            *is this one of them?*
    """

    entry: str
    edges: Mapping[str, Sequence[str]] = field(default_factory=dict)
    conditional: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    effecting: frozenset[str] = field(default_factory=frozenset)

    def is_conditional(self, node: str) -> bool:
        return node in self.conditional

    def is_effecting(self, node: str) -> bool:
        """Does ``node`` do something the world remembers?

        An effecting step must run exactly once across a crash and a resume;
        a pure one is replayed. The default is pure, because the framework
        cannot tell them apart by looking and guessing wrong in that direction
        re-runs a refund.
        """
        return node in self.effecting

    def successors(self, node: str, choice: str | None = None) -> list[str]:
        """Successors of ``node``; ``choice`` selects a conditional target."""
        if self.is_conditional(node):
            if choice is None:
                return []
            target = self.conditional[node].get(choice)
            return [] if target is None else [target]
        return [t for t in self.edges.get(node, ())]


class WalkState:
    """Outcome markers for a frontier walk."""

    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class StepStatus:
    """Outcome markers for one **step record**.

    A third vocabulary, deliberately: `WalkState` says what a *scope* is doing
    and `RunStatus` says how a *job run* ended. A step is neither. Collapsing
    any two of them would make the widest one win, and the three answer
    different questions to different readers.

    `timed_out` and `cancelled` are copied from pi-workflows rather than
    invented (decision **L3**). Both already happened before this existed and
    both were written down as `failed`, which is how someone ends up debugging
    a job that did nothing wrong.
    """

    SUCCESS = "success"
    FAILED = "failed"
    #: The scope went claimable while this step still held it. There is no
    #: preemption anywhere in this codebase — `_engine/exec_policy` refused
    #: every mechanism that could deliver one — so a step's only budget is its
    #: lease, and the only party that can record the expiry is whoever takes
    #: the scope over. See `FrontierWalk._note_the_step_that_went_silent`.
    TIMED_OUT = "timed_out"
    #: A human stopped it. Terminal by design and **not** a failure: recorded
    #: as one, it invites exactly the retry that can never succeed.
    CANCELLED = "cancelled"


#: The outcomes a replay may skip over.
#:
#: A *set*, not the literal `"success"`, so that adding an outcome is a
#: decision taken here rather than one that falls out of a string comparison
#: nobody re-read (spec AC-9). With one member the two spellings agree on every
#: input that exists today, which is the point: the difference appears on the
#: day it matters, and by then the comparison is already right.
TERMINAL_SUCCESS: frozenset[str] = frozenset({StepStatus.SUCCESS})


logger = logging.getLogger(__name__)


class FrontierWalk:
    """Expands a graph's frontier at runtime, persisting position and records.

    Args:
        graph: The graph to walk.
        store: State store for §D.7c/§D.7d persistence.
        scope_id: The scope these records belong to.
        runtime_store: The port this walk claims through (FUN-17/T14,
            R-14.1). Required and keyword-only, like every storage argument
            since T12's tripwire: a walk that could be built without one
            would be a walk that claims nowhere.
    """

    def __init__(
        self,
        graph: GraphModel,
        scope_id: str,
        *,
        runtime_store: RuntimeStore,
    ) -> None:
        self._graph = graph
        self._scope_id = scope_id
        self._runtime_store = runtime_store
        #: Builds the input commands this walk issues — the id minter.
        self._inputs = InputRecorder()
        #: The lease generation this walk holds, or None if it never claimed.
        #: Set by `claim`; every scope write it makes carries it (T6).
        self._generation: int | None = None

    # ------------------------------------------------------------------
    # The lease (`durable-run-layer`/T5, T6)
    # ------------------------------------------------------------------

    def claim(
        self, *, owner: str | None = None, force: bool = False
    ) -> Claimed | Conflict:
        """Take the scope through the port, fencing every write this walk makes.

        Returns the outcome (FUN-17/T14): ``Claimed`` — this walk holds the
        generation, and a write from any other holder of the scope is refused,
        which is what closes the concurrent-`resume` limitation — or
        ``Conflict``, someone else's name for the same moment. Losing a claim
        is an outcome the caller branches on, never an exception.

        On ``Claimed`` the walk keeps the generation it was handed, and every
        command it issues afterwards carries it, so the store's fence refuses
        a write from a walk whose claim was taken over.
        """
        from datetime import UTC, datetime

        from functualize._engine.recording import WorkflowRecorder
        from functualize._primitives.lease import DEFAULT_LEASE_SECONDS
        from functualize._primitives.run_store import runner_identity

        # Read before claiming, write after. The question is about the state
        # the *previous* holder left, and claiming overwrites the lease that
        # answers it; the write waits until this walk holds the generation
        # that fences it.
        silent = self._step_that_went_silent()
        command = WorkflowRecorder().claimed(
            scope_id=self._scope_id,
            owner=owner or runner_identity(),
            now=datetime.now(UTC),
            lease_seconds=DEFAULT_LEASE_SECONDS,
            force=force,
        )
        with self._runtime_store.transaction() as tx:
            outcome = tx.workflows.claim(command)
        if isinstance(outcome, Conflict):
            return outcome
        self._generation = outcome.generation
        if silent is not None:
            self._record_timed_out(silent)
        return outcome

    def _step_that_went_silent(self) -> str | None:
        """The node this scope was on when its holder stopped reporting.

        None unless the scope is **abandoned**, which is two facts and not one:
        the status still says `running`, and the lease has expired. Both are
        needed. `lease.release` expires a lease *in place* rather than deleting
        it — deleting would reset the generation and hand out the fence it
        exists to raise — so "the lease is expired" is true of every scope that
        ever finished, and a check reading only that would call the gate node
        of every resumed workflow timed out. A walk that stopped cleanly
        stamped `blocked`, `completed` or `failed` first; only one that stopped
        without stamping anything leaves `running` behind.

        These are the same two facts `_workflow_view.derived_state` already
        joins to report `abandoned`, read here rather than a third rule
        invented beside them.

        A step that already reported is left alone: `failed` is that step's own
        account of itself, and replacing it with `timed_out` would swap the
        reason for the observation that it stopped — which is true of every
        failure ever recorded.
        """
        view = self.view()
        if view is None or view.status != WalkState.RUNNING:
            return None
        if view.expires_at is None or view.expires_at > datetime.now(UTC):
            return None
        position = view.position
        if not isinstance(position, str) or not position:
            return None
        if self.step(step_key(position, "")) is not None:
            return None
        return position

    def _record_timed_out(self, node: str) -> None:
        """Write the one thing a taken-over scope can honestly say.

        Nothing preempts a running step — `_engine/exec_policy` researched and
        rejected every mechanism that could, and
        `tests/engine/test_timeout_is_lease_expiry` holds this codebase to it.
        So a step's only budget is its lease, expiring is the only way it can
        be exceeded, and the runner that overran is by definition not the one
        that can write it down.

        Recorded at the iteration-0 key. A step that went silent on a later
        loop pass is under a different key and gets no record, which is an
        under-report rather than a wrong one: the pass is re-run either way,
        because nothing about it is terminal-success.
        """
        # The runner that overran never finished, so there is no completion
        # time to record (ruling R-2): the store keeps it empty, not stamped.
        self.record(step_key(node, ""), StepStatus.TIMED_OUT, completed_at=None)

    def renew(self) -> None:
        """Extend this walk's claim. The generation does not move.

        **The heartbeat, and without it the lease is a step time limit.** A walk
        claims once and the lease runs for `DEFAULT_LEASE_SECONDS`; any step
        slower than that would see its scope become claimable while it was
        still working, and another runner could take it. Renewing between nodes
        says "still here" — so the lease measures *silence*, not duration.

        Moving the generation on renewal would be the opposite of the point: it
        would fence this walk's own in-flight writes, so every heartbeat would
        invalidate the work it exists to protect.

        Best-effort. A renewal that fails means the scope has been taken, and
        the next write will say so with the holder named — raising here would
        report it in the middle of a step that is still running fine.
        """
        if self._generation is None:
            return
        from functualize._primitives.lease import DEFAULT_LEASE_SECONDS
        from functualize._primitives.run_store import runner_identity

        try:
            with self._runtime_store.transaction() as tx:
                tx.workflows.renew(
                    RenewLease(
                        self._scope_id,
                        self._generation,
                        runner_identity(),
                        datetime.now(UTC),
                        DEFAULT_LEASE_SECONDS,
                    )
                )
        except Exception:  # noqa: BLE001 - the next write reports it properly
            logger.debug("could not renew the scope lease", exc_info=True)

    def release(self) -> None:
        """Give up the claim, leaving the scope immediately claimable.

        Best-effort: a walk that ends by raising must not turn a failed step
        into a second, more confusing failure about a lease.
        """
        if self._generation is None:
            return
        try:
            with self._runtime_store.transaction() as tx:
                tx.workflows.release(
                    ReleaseLease(self._scope_id, self._generation, datetime.now(UTC))
                )
        except Exception:  # noqa: BLE001 - releasing is never worth a failure
            logger.debug("could not release the scope lease", exc_info=True)
        finally:
            self._generation = None

    # ------------------------------------------------------------------
    # Walk control
    # ------------------------------------------------------------------

    def start(
        self, workflow: str | None = None, *, graph_digest: str = ""
    ) -> list[str]:
        """Begin (or resume) the walk, returning the nodes now runnable.

        Resuming is *replay*: a scope with a persisted position resumes there
        rather than re-entering at the graph entry.

        Either way the scope says ``running`` from the moment this walk owns it
        (D2 = 1). It used to be stamped only on first entry, so a resumed walk
        kept whatever it had stopped as — ``blocked`` after a gate, ``failed``
        after a step raised — for the whole walk, and three readers depend on
        the stamp: ``app/_workflow_view.list_scopes`` shows ``running`` rather
        than a parked-looking ``blocked``; ``app/_workflow_control``'s
        ``advanceable_scopes`` lists a scope resumed from ``failed`` (it
        qualifies on ``running``; ``blocked`` was already live); and
        :meth:`_step_that_went_silent`, which will not diagnose a lapsed lease
        unless the scope reads ``running``, can see a resumed walk at all.

        The caller is expected to have refused a scope that must not run: the
        stamp overwrites whatever is stored, and ``WorkflowRunner.prelude``
        refuses a cancelled scope before calling this.
        """
        # D2 = 1: every entry, first or resumed, stamps `running`; the store
        # keeps a persisted position and only a fresh scope takes the entry.
        with self._runtime_store.transaction() as tx:
            tx.workflows.start(
                StartWalk(
                    self._scope_id,
                    self._generation or 0,
                    workflow or "",
                    self._graph.entry,
                    graph_digest,
                    datetime.now(UTC),
                )
            )
        view = self.view()
        position = view.position if view is not None else None
        return [position] if position is not None else [self._graph.entry]

    def complete(
        self,
        node: str,
        *,
        choice: str | None = None,
        args_hash: str = "",
        return_value: Any = None,
        inputs: Mapping[str, Any] | None = None,
        status: str = StepStatus.SUCCESS,
        completed_at: str = "",
    ) -> list[str]:
        """Record ``node`` as finished and expand the frontier past it.

        For a conditional source, ``choice`` selects the branch — but a choice
        already recorded for this scope **wins**, so replay follows the branch
        the walk originally took (§D.7d).
        """
        # Classify before writing, exactly as `make_record` does for
        # fingerprints. Writing the value raw crashed the walk on
        # `json.dump` — after the step had already succeeded — for anything
        # without a JSON form, and a step returning a live handle is a
        # legitimate thing to do. The record is still written so the walk's
        # position and status survive; only the value is dropped, and a
        # reader is told why.
        from functualize._primitives.fingerprint import classify_return_value

        reusable, kind, type_name, stored = classify_return_value(return_value)

        # The branch is resolved before the write: a choice already recorded
        # for this scope wins, so replay follows the branch the walk took
        # (§D.7d), and only a first evaluation is recorded.
        decision: str | None = None
        if self._graph.is_conditional(node):
            recorded = self.branch(node)
            if recorded is not None:
                choice = recorded
            elif choice is not None:
                decision = node

        successors = self._graph.successors(node, choice)
        runnable = [n for n in successors if n != END]
        finished = not successors or successors == [END]

        # One unit for the node: its record, its branch, and the scope's
        # advance land together or not at all.
        now = (
            datetime.fromisoformat(completed_at) if completed_at else datetime.now(UTC)
        )
        with self._runtime_store.transaction() as tx:
            if decision is not None and choice is not None:
                tx.workflows.record_branch(
                    RecordBranch(self._scope_id, self.generation, decision, choice, now)
                )
            tx.workflows.complete_step(
                CompleteStep(
                    scope_id=self._scope_id,
                    generation=self._generation or 0,
                    step_key=step_key(node, args_hash),
                    now=now,
                    status=status,
                    result=stored if reusable else None,
                    position=None if finished else (runnable[0] if runnable else None),
                    scope_status=WalkState.COMPLETED if finished else WalkState.RUNNING,
                    reusable=reusable,
                    result_kind=kind,
                    result_type=type_name,
                    inputs=dict(inputs or {}),
                    # Recorded on the step, not looked up from the declaration
                    # on resume (`durable-run-layer`/T9): a resume may meet a
                    # declaration that has since changed.
                    effecting=self._graph.is_effecting(node),
                )
            )
        return [] if finished else runnable

    def block(
        self,
        node: str,
        gate_name: str,
        *,
        model: str = "",
        input_schema: Mapping[str, Any] | None = None,
        tools: Sequence[Mapping[str, Any]] = (),
        blocked_at: str = "",
    ) -> None:
        """Persist a BLOCKED position and open its gate's request (§D.7b/c).

        The walk stops here until input is deposited; because position and
        request both persist, a different process can observe and resume it.
        Now one port transaction — :meth:`open_request` — rather than three
        direct writes, so the gate record this leaves is a request with its
        own identity, and ``tools`` and ``model`` persist beside the schema
        for an agent that finds the gate without the declaring module.
        """
        when = datetime.fromisoformat(blocked_at) if blocked_at else datetime.now(UTC)
        self.open_request(
            gate_name,
            position=node,
            schema=dict(input_schema or {}),
            prompt=None,
            model=model,
            tools=tools,
            when=when,
        )

    def gate_payload(self, gate_name: str) -> Any:
        """The answer this gate holds, or None while still blocked.

        The accepted candidate's payload when the request recorded one;
        otherwise the answer an older path deposited on the record — the
        read-only projection that keeps pre-change files answering gates.
        """
        resolution = self.resolution(gate_name)
        if resolution is not None and resolution.accepted_id is not None:
            for candidate in resolution.candidates:
                if candidate.candidate_id == resolution.accepted_id:
                    return candidate.payload
            return None
        # TRANSITIONAL(FUN-21): legacy deposits still answer from the document record.
        # TRANSITIONAL(FUN-21): the legacy deposit path, read through the port
        # (ruling R-1) — an accepted candidate first, the deposited answer second.
        return self._runtime_store.inputs.deposited_answer(self._scope_id, gate_name)

    # ------------------------------------------------------------------
    # Gate requests — the input port, one transaction unit per verb
    # ------------------------------------------------------------------

    @property
    def scope_id(self) -> str:
        """The scope this walk's records belong to."""
        return self._scope_id

    def open_request(
        self,
        gate_name: str,
        *,
        position: str,
        schema: Any,
        prompt: Any,
        model: str = "",
        tools: Sequence[Mapping[str, Any]] = (),
        when: datetime | None = None,
        scope_status: str = WalkState.BLOCKED,
    ) -> str:
        """Open (or rejoin) the gate request through the runtime port.

        One transaction unit: the request record, position and lifecycle
        status land together, and a request already live for
        the gate is rejoined under its own id — which is what keeps a
        request's identity stable across the resumes that re-enter it.

        Returns the minted request id. The store may have reused a live
        request's id instead; :meth:`resolution` reads the effective one
        back off the record.
        """
        command = self._inputs.opened(
            scope_id=self._scope_id,
            generation=self._generation or 0,
            gate_name=gate_name,
            position=position,
            now=when or datetime.now(UTC),
            schema=schema,
            prompt=prompt,
            model=model,
            tools=tuple(tools),
            scope_status=scope_status,
        )
        with self._runtime_store.transaction() as tx:
            tx.workflows.suspend(command)
        return command.request_id

    def record_candidates(self, candidates: Sequence[GateCandidate]) -> None:
        """Record proposed answers against their request — one unit.

        Appending is refused for a request that is no longer open, with
        nothing from the unit applied, so a second writer's answer cannot
        overwrite a recorded one.
        """
        with self._runtime_store.transaction() as tx:
            for candidate in candidates:
                tx.inputs.append(candidate)

    def consume(self, request_id: str) -> None:
        """Retire the request the walk is moving past — its single writer.

        Idempotent: consuming an already-consumed request is a no-op, so a
        replayed resume is a legitimate caller.
        """
        command = self._inputs.consumed(
            scope_id=self._scope_id,
            generation=self._generation or 0,
            request_id=request_id,
            now=datetime.now(UTC),
        )
        with self._runtime_store.transaction() as tx:
            tx.inputs.consume(command)

    def resolution(self, gate_name: str) -> GateResolution | None:
        """The gate's request and its recorded candidates, through the port.

        The request is found by the id its record owns — falling back to the
        id a legacy record projects to — and the candidates come back with
        the evaluations they were recorded with, never re-validated.
        """
        request = self._runtime_store.inputs.request(self._request_id_for(gate_name))
        if request is None:
            return None
        candidates = self._runtime_store.inputs.candidates_for(request.request_id)
        accepted = next(
            (
                candidate
                for candidate in candidates
                if candidate.evaluation.outcome is EvaluationOutcome.ACCEPTED
            ),
            None,
        )
        return GateResolution(
            request=request,
            candidates=tuple(candidates),
            accepted_id=accepted.candidate_id if accepted is not None else None,
        )

    def _request_id_for(self, gate_name: str) -> str:
        """The request id this gate's record owns, or its legacy derivation.

        Reads identity, not answers: which request this gate's record was
        opened as. The status and the candidates it holds are the reader
        port's business; this is only how the question is addressed.
        """
        request = self._runtime_store.inputs.for_gate(self._scope_id, gate_name)
        if request is not None:
            return request.request_id
        return f"{self._scope_id}::{gate_name}"

    def is_blocked(self) -> bool:
        view = self.view()
        return view is not None and view.status == WalkState.BLOCKED

    def completed_steps(self) -> dict[str, StepView]:
        """Every step recorded in this scope, by key (drives replay-skip)."""
        return {view.step_key: view for view in self.steps()}

    def should_replay_skip(self, node: str, args_hash: str = "") -> bool:
        """True when this step already completed in this scope (§D.7d).

        Resume re-invokes the workflow; a step that already succeeded here must
        not run twice.

        Asks :data:`TERMINAL_SUCCESS` rather than comparing the string, so a
        step recorded `failed`, `timed_out` or `cancelled` runs again — and so
        that the day a second success-like outcome exists, it becomes
        replayable by a decision instead of by a comparison nobody re-read.
        """
        record = self.step(step_key(node, args_hash))
        return record is not None and record.status in TERMINAL_SUCCESS

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # The walk's other reads and writes, through the port
    #
    # The walker and the runner write through these rather than reaching for a
    # store: each command carries this walk's held generation, so the store's
    # fence — not the caller — is what refuses a walk whose claim was taken.
    # ------------------------------------------------------------------

    @property
    def generation(self) -> int:
        """The generation this walk holds, or 0 (fences nothing) before a claim."""
        return self._generation or 0

    def view(self) -> WorkflowView | None:
        """The scope as a reader finds it — status, position, lease, digest."""
        return self._runtime_store.workflows.workflow(self._scope_id)

    def step(self, key: str) -> StepView | None:
        """One step record of this scope, by its key."""
        return self._runtime_store.workflows.step(self._scope_id, key)

    def steps(self) -> Sequence[StepView]:
        """Every step record of this scope."""
        return self._runtime_store.workflows.steps(self._scope_id)

    def branch(self, decision_key: str) -> str | None:
        """The target recorded for ``decision_key``, or None."""
        return self._runtime_store.workflows.branch(self._scope_id, decision_key)

    def record_branch(self, decision_key: str, target: str) -> None:
        """Record an immutable decision; the same target again is a replay."""
        with self._runtime_store.transaction() as tx:
            tx.workflows.record_branch(
                RecordBranch(
                    self._scope_id,
                    self.generation,
                    decision_key,
                    target,
                    datetime.now(UTC),
                )
            )

    def record(
        self,
        key: str,
        status: str,
        *,
        completed_at: datetime | None,
        result: Any = None,
        reusable: bool = False,
        result_kind: str | None = None,
        result_type: str | None = None,
        inputs: Mapping[str, Any] | None = None,
    ) -> None:
        """A step record that moves neither position nor status.

        ``completed_at`` is required (ruling R-2): ``None`` for a step that
        never finished, so the store records no completion time for it.
        """
        with self._runtime_store.transaction() as tx:
            tx.workflows.record_step(
                RecordStep(
                    self._scope_id,
                    self.generation,
                    key,
                    datetime.now(UTC),
                    completed_at,
                    status=status,
                    result=result if reusable else None,
                    reusable=reusable,
                    result_kind=result_kind,
                    result_type=result_type,
                    inputs=inputs,
                )
            )

    def move(self, status: str, position: str | None) -> None:
        """Set the scope's status and position with no step: a nested gate's
        block, or END reached without a node completing."""
        with self._runtime_store.transaction() as tx:
            tx.workflows.move(
                MoveScope(
                    self._scope_id, self.generation, status, position, datetime.now(UTC)
                )
            )


def step_key(job_name: str, args_hash: str = "") -> str:
    """Per-scope step-record key: ``<job_name>::<args_hash>`` (§D.7d)."""
    return f"{job_name}::{args_hash}"
