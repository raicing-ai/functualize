"""The workflow walker — executes a ``@workflow`` graph (§A.7, §D.7).

This is push mode's consumer: :mod:`functualize._engine.frontier` expands the
frontier and persists it; the walker decides *what to do* at each node it is
handed, and is deliberately runner-agnostic — it takes a callable that runs one
job, so it is testable without the execution engine (same discipline as
:class:`~functualize._engine.scheduler.DepScheduler`).

**Resume is replay, not jump-to-position** (§D.7, "replay + memoization"). Every
invocation re-enters at the graph entry; a step already recorded in this scope
is skipped and its recorded return value reused, a branch already chosen is
read rather than re-evaluated, and a gate whose input was deposited passes
through. Nothing suspends and nothing continues — which is why a blocked walk
survives a process exit for free.

Note that this walker does not route on
:meth:`~functualize._engine.frontier.FrontierWalk.start`'s return value. That
method resumes *at the persisted position*, which coincides with a replay only
on a linear graph — on a fan-out it would silently drop the sibling branches
that had not run yet. The persisted position stays what §D.7c calls it: the
blocked-walk position, a fact for observers (MCP `current_position`) rather
than the resume mechanism.

The epilogue body — the decorated function's own code, running once the walk
reaches ``END`` — is not here; it belongs to the workflow *job*, not the walk.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from functualize._engine.frontier import END as _FRONTIER_END
from functualize._engine.frontier import (
    TERMINAL_SUCCESS,
    FrontierWalk,
    GraphModel,
    StepStatus,
    WalkState,
    step_key,
)
from functualize._engine.loop_state import current_iteration, iteration_step_key
from functualize._primitives.graph import descendants
from functualize._types.errors import ScopeCancelledError
from functualize._types.workflow import (
    END,
    AgentStep,
    ConditionalEdge,
    Gate,
    Loop,
    OnFailure,
    Step,
    _EndSentinel,
)

if TYPE_CHECKING:
    from functualize._primitives.scope_store import ScopeStore
    from functualize._types.protocols import AgentStepResult
    from functualize._types.workflow import WorkflowDeclaration

__all__ = [
    "StepBlocked",
    "StepOutcome",
    "WalkOutcome",
    "WalkReport",
    "WorkflowWalker",
    "graph_model_of",
]


logger = logging.getLogger(__name__)


class StepBlocked(Exception):  # noqa: N818 — deliberately not an "Error"
    """A step did not fail — it blocked, in a scope of its own.

    Named without the `Error` suffix on purpose. N818 asks for one; obeying it
    would assert the opposite of what this means, and the whole defect it
    fixes was a block being read as a failure.

    Raised by a `run_step` callback when the step is itself a workflow that
    stopped at a gate. The distinction is load-bearing: a nested gated
    workflow used to reach the parent as a plain exception, so the parent
    recorded the step ``failed`` and marked its own scope ``failed`` too.
    Resuming the child then left the parent permanently failed and the walk
    could never complete, which made nested gated workflows unusable.

    `BLOCKED` already exists as a distinct `GuardState` and `RunStatus`; this
    is what carries it across the walk boundary.

    Attributes:
        scope_id: The *child* scope an agent must resume.
        blocked_on: The gate the child stopped at.
    """

    def __init__(self, scope_id: str, blocked_on: str) -> None:
        self.scope_id = scope_id
        self.blocked_on = blocked_on
        super().__init__(f"blocked on {blocked_on!r} in scope {scope_id!r}")


@dataclass(frozen=True)
class StepOutcome:
    """What a step returned, plus what it was given.

    ``run_step`` may return a bare value — that is all a caller with nothing
    to say about inputs needs, and it keeps the callback trivial to write in a
    test. Returning a `StepOutcome` additionally records the resolved inputs
    on the step record, which is what makes a finished walk explicable rather
    than merely enumerable.
    """

    value: Any
    inputs: dict[str, Any] = field(default_factory=dict)


class WalkOutcome(Enum):
    """How one invocation of the walk ended."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    #: The scope was taken from this walk while it was running — cancelled, or
    #: reclaimed by another runner (`durable-run-layer`/T7). Distinct from
    #: FAILED, because nothing about the *work* went wrong: this walk simply no
    #: longer owns the scope, and reporting it as a failure would send someone
    #: looking for a bug in their job.
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class WalkReport:
    """What one invocation of the walk did.

    ``executed`` and ``replayed`` are split because they answer different
    questions: what this invocation actually did, versus what it inherited from
    an earlier one. Collapsing them would make a resume indistinguishable from
    a first run in the logs.
    """

    outcome: WalkOutcome
    scope_id: str
    executed: tuple[str, ...] = ()
    replayed: tuple[str, ...] = ()
    blocked_on: str | None = None
    failed_node: str | None = None
    error: str = ""
    results: dict[str, Any] = field(default_factory=dict)
    blocked_reason: str = ""
    """Why the gate could not be resolved, when there is something to say.

    Empty for the ordinary block — a gate with no strategy, waiting for a
    human. Populated when a strategy ladder was tried and every rung failed,
    which is the case an operator cannot diagnose from ``blocked_on`` alone:
    "blocked on triage" reads the same whether the gate is waiting by design
    or because ``functualize-ai`` is not installed.

    Additive and optional. Consumers reading ``blocked_on`` are unaffected.
    """

    @property
    def ok(self) -> bool:
        """True only when the walk reached ``END``."""
        return self.outcome is WalkOutcome.COMPLETED


@dataclass(frozen=True)
class _NodeRun:
    """What servicing one node produced, for the loop's common tail.

    A handler either returns one of these — the node ran (or replayed) and the
    walk continues past it — or a `WalkReport`, which means the node ended the
    walk. That is the whole contract between the loop and a node kind, and it
    is why adding a kind does not touch the loop.
    """

    value: Any
    inputs: dict[str, Any] | None = None
    replayed: bool = False
    #: Where a **failed** node's declared `OnFailure` sends the walk, or None.
    #:
    #: Carried on the run rather than routed inside the handler because the
    #: loop owns what goes on the queue — a handler that queued its own
    #: successor would be a second place deciding where the walk goes next.
    failure_route: str | None = None


@dataclass
class _Ledger:
    """The walk's running account: what ran, what replayed, what it produced.

    One object rather than three arguments, because a handler that ends the
    walk (a block, a nested block) has to carry the account *as it stands* into
    the report it builds. Handing over the lists themselves would make that a
    copy the loop could later diverge from.
    """

    executed: list[str] = field(default_factory=list)
    replayed: list[str] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)


def graph_model_of(declaration: WorkflowDeclaration) -> GraphModel:
    """Compile a declaration into the shared graph model (§A.7 one-engine rule).

    ``Deps`` and ``@workflow`` are two vocabularies over one representation, so
    the walker never sees `Step`/`Gate`/`Edge` — it sees the same `GraphModel`
    the dependency scheduler does, with `END` flattened to the frontier's
    terminal marker.
    """
    edges: dict[str, list[str]] = {}
    conditional: dict[str, dict[str, str]] = {}
    # Names only: the walk asks "is this one of them?", never "what kind of node
    # is this?" — the same reason the graph carries edges rather than `Step`s.
    effecting = frozenset(
        node.name for node in declaration.nodes if getattr(node, "effecting", False)
    )

    for edge in declaration.edges:
        if isinstance(edge, ConditionalEdge):
            conditional[edge.source] = {
                key: _target_name(target) for key, target in edge.targets.items()
            }
        else:
            edges.setdefault(edge.source, []).append(_target_name(edge.target))

    return GraphModel(
        entry=declaration.entry or "",
        edges=edges,
        conditional=conditional,
        effecting=effecting,
    )


def _target_name(target: str | _EndSentinel) -> str:
    """Flatten an edge target, mapping the `END` sentinel to the walk marker.

    A node target is always a `str`; anything else is `END`.
    """
    return target if isinstance(target, str) else _FRONTIER_END


class WorkflowWalker:
    """Executes one workflow declaration over a persisted scope.

    Args:
        declaration: The graph as written by ``@workflow``.
        store: State store holding this scope's records (§D.7c/d).
        scope_id: The scope this walk belongs to. Reusing a scope id is what
            makes an invocation a *resume*.
        run_step: Executes one `Step` by its node name and returns its value.
            Raising marks the step — and the walk — failed.
        run_agent_step: Executes one `AgentStep`. The *runner* supplies it,
            having already chosen and checked the executor against the step's
            requirements; a walker built without one refuses an agent step
            rather than recording a step that silently did nothing.
        workflow_name: Job name recorded on the scope, for observers.
        gate_registry: Resolution dispatch for gates. When None (default),
            gates always block.
        prompt_gates: When True, gates without an explicit strategy attempt
            prompt-before-block resolution.
    """

    def __init__(
        self,
        declaration: WorkflowDeclaration,
        store: ScopeStore,
        scope_id: str,
        *,
        run_step: Callable[[str], Any],
        run_agent_step: Callable[[AgentStep], AgentStepResult] | None = None,
        workflow_name: str | None = None,
        gate_registry: Any = None,
        prompt_gates: bool = False,
        max_workflow_depth: int | None = None,
    ) -> None:
        self._declaration = declaration
        self._store = store
        self._scope_id = scope_id
        self._run_step = run_step
        self._run_agent_step = run_agent_step
        self._workflow_name = workflow_name
        self._graph = graph_model_of(declaration)
        self._predecessors = self._build_predecessors(declaration)
        self._walk = FrontierWalk(self._graph, store, scope_id)
        self._gate_registry = gate_registry
        self._prompt_gates = prompt_gates
        #: None means "the default" — resolved in `workflow_validation` rather
        #: than here, so the number lives in one place.
        self._max_workflow_depth = max_workflow_depth
        #: Which pass of a `Loop` the walk is on. Zero for every graph
        #: that declares none, which is every graph before T2.
        self._iteration = 0

    def run(self) -> WalkReport:
        """Walk to `END`, to a gate with no input, or to a failure.

        **Holds a lease for the duration** (`durable-run-layer`/T7). Claiming is
        what closes the concurrent-`resume` limitation 0.3.0 shipped knowingly:
        a second walk on the same scope is refused here rather than advancing it
        in parallel, and even if it somehow got past this, every write it made
        would be fenced by its stale generation (T6).

        Released in a `finally`, so a scope is claimable again the moment the
        walk stops — including when it stops by raising. A walk that ended
        without releasing would hold the scope until its lease expired, which
        turns a crash into a five-minute wait for everyone else.
        """
        from functualize._primitives.lease import StaleGenerationError

        self._walk.claim()
        try:
            self._check_the_nesting_is_bounded()
            self._check_the_graph_has_not_changed()
            return self._run_walk()
        except StaleGenerationError:
            # Someone took the scope while this walk was running — `cancel`
            # does exactly that (AC-10). The walk stops where it is; it does
            # **not** stamp a terminal status, because the holder that took the
            # scope has already recorded what it wanted the scope to say.
            #
            # This is how cancel *wins* rather than merely arriving first. The
            # fence alone would not do it: this walk's generation is current
            # until something supersedes it, so its COMPLETED stamp would
            # happily overwrite the cancellation.
            logger.info(
                "workflow scope %s was taken while walking; stopping", self._scope_id
            )
            return WalkReport(WalkOutcome.SUPERSEDED, self._scope_id)
        finally:
            self._walk.release()

    def _check_the_nesting_is_bounded(self) -> None:
        """Refuse a workflow nested deeper than the limit (T12, AC-18).

        **Before the graph check and before any work**, because the cost this
        bounds is the scope itself: a workflow that names itself as a step
        type-checks, boots, and produces one scope per level until the disk
        runs out. Checking after the first node would already have written one.

        The depth is read from the scope id, where the nesting already lives —
        a nested workflow's scope is `f"{parent}::{step}"`, so the separators
        *are* the depth. A resumed walk in a fresh process has the id and
        nothing else, and a threaded counter could disagree with it.
        """
        from functualize._engine.workflow_validation import check_workflow_depth

        check_workflow_depth(self._scope_id, self._max_workflow_depth)

    def _check_the_graph_has_not_changed(self) -> None:
        """Refuse to advance a scope whose graph is not the one loaded (T11).

        On first entry the digest is *recorded*; on every later entry it is
        *compared*. Resuming against a changed graph would replay step records
        against a different shape — a node that no longer exists, an edge that
        now leads elsewhere, a gate whose answer has no step left to feed.

        The digest is of the **graph projection**, never the file (decision K3,
        risk R-g). A file digest refuses a resume when a docstring changes or an
        unrelated job in the same module is edited, which is not a safety
        property — it is a permanent annoyance that teaches people to bypass
        the check.

        Nothing is destroyed by the refusal: the records stay, the scope stays
        readable, and only *advancing* stops.
        """
        from functualize._engine.workflow_validation import (
            WorkflowGraphChangedError,
            graph_digest,
        )

        current = graph_digest(self._declaration)
        if not current:
            return
        recorded = self._store.get_graph_digest(self._scope_id)
        if not recorded:
            # First entry, or a scope parked before this check existed — the
            # legacy-mapping path (AC-17). Record and proceed; refusing here
            # would strand every walk that was already waiting.
            self._store.set_graph_digest(self._scope_id, current)
            return
        if recorded != current:
            raise WorkflowGraphChangedError(self._scope_id, recorded, current)

    def _run_walk(self) -> WalkReport:
        """The walk itself. See `run` for the lease that wraps it."""
        self._walk.start(self._workflow_name)

        entry = self._declaration.entry
        if entry is None:  # an empty graph is already at its end
            self._store.set_scope_status(self._scope_id, WalkState.COMPLETED)
            return WalkReport(WalkOutcome.COMPLETED, self._scope_id)

        # **Keyed by node and iteration**, not by node
        # (`workflow-graph-semantics`/T2). Both failure modes here are silent,
        # which is why the test asserts them in one body: keyed by node alone,
        # a loop's second pass is pruned and looks like a condition that was
        # false; keyed by iteration alone, a diamond join runs once per branch
        # and looks like a flaky step.
        # **The iteration travels with the queued work**, not as a cursor the
        # loop advances. A diamond join is queued once per branch, and a cursor
        # incremented when the loop's source finished would give the join's two
        # arrivals different iterations — so the second would not be pruned and
        # the join would run twice in one pass. Measured, not reasoned about:
        # that was the first version, and `test_the_loop_repeats_and_the_join_
        # still_runs_once_per_pass` caught it.
        start = self._resume_iteration()
        pending: deque[tuple[str, int]] = deque([(entry, start)])
        visited: set[tuple[str, int]] = set()
        ledger = _Ledger()

        deferrals = 0
        while pending:
            name, iteration = pending.popleft()
            self._iteration = iteration
            # A diamond join is reached once per branch but must run once —
            # *per iteration*. Two arrivals in one pass share an iteration and
            # the second is pruned; the next time round the loop the pair is
            # new and is not.
            if (name, iteration) in visited:
                continue
            if deferrals <= len(pending) and not self._ready(
                name, deque(queued for queued, _ in pending)
            ):
                # A join whose other branch is still in flight. Breadth-first
                # order is not a topological order — on an asymmetric diamond
                # (a→b→c→join vs d→join) the short branch would otherwise run
                # the join before the long one finished.
                #
                # The counter bounds this: once every queued node has been
                # deferred once with nothing running in between, they are
                # waiting on each other (a cycle), and one edge out of order
                # beats spinning forever.
                pending.append((name, iteration))
                deferrals += 1
                continue
            deferrals = 0
            visited.add((name, iteration))

            node = self._declaration.node(name)
            if node is None:
                # Boot validation resolves every edge target, so this means the
                # declaration changed under a live scope rather than a typo.
                return self._fail(name, f"unknown node {name!r} in the graph")

            # The table *is* the dispatch: the loop never asks what kind of
            # node it is holding, and a fourth kind is a handler registered in
            # `_NODE_HANDLERS` rather than an edit here. A kind with no handler
            # is refused by name, never run as whichever of the others it most
            # resembles.
            handler = _NODE_HANDLERS.get(type(node))
            if handler is None:
                return self._fail(
                    name, f"no handler for node kind {type(node).__name__!r}"
                )

            run = handler(self, node, name, ledger)
            if isinstance(run, WalkReport):
                return run
            if run.replayed:
                ledger.replayed.append(name)
            else:
                ledger.executed.append(name)
            ledger.results[name] = run.value
            # Say "still here" at every node boundary. Without this the lease
            # becomes a step time limit: a step slower than the lease would see
            # its own scope go claimable while it was still working.
            #
            # Between nodes rather than during one, because that is where the
            # walk is between two committed states — and because nothing here
            # can interrupt a step anyway (`exec_policy` §1).
            self._walk.renew()
            if run.failure_route is not None:
                # A routed failure does not advance the frontier: the node did
                # not succeed, so nothing downstream of it is unblocked. Only
                # the declared route is queued, and the step keeps its `failed`
                # record so a resume replays to the same place.
                self._record_routed_failure(name)
                if run.failure_route != _ROUTED_TO_END:
                    pending.append((run.failure_route, iteration))
                continue
            pending.extend(
                (nxt, iteration) for nxt in self._advance(name, run.value, run.inputs)
            )
            back = self._loop_back(name, run.value, iteration)
            if back is not None:
                pending.append((back, iteration + 1))

        self._store.set_scope_status(self._scope_id, WalkState.COMPLETED)
        return WalkReport(
            WalkOutcome.COMPLETED,
            self._scope_id,
            tuple(ledger.executed),
            tuple(ledger.replayed),
            results=ledger.results,
        )

    # ------------------------------------------------------------------
    # One handler per node kind
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Loops
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Failure routing
    # ------------------------------------------------------------------

    def _record_routed_failure(self, name: str) -> None:
        """Record the node as failed, without marking the scope failed.

        The step record still says `failed` — it is what happened, and a
        resume replays to exactly this node. What does *not* happen is the
        scope status change: the walk is continuing down a declared route, and
        a workflow that recovers is not a failed workflow.
        """
        self._store.record_step(
            self._scope_id,
            self._key(name),
            {
                "status": StepStatus.FAILED,
                "return_value": None,
                "completed_at": _now(),
            },
        )

    def _failure_route(self, name: str, exc: BaseException) -> str | None:
        """Where ``name``'s failure goes, or None to stop the walk.

        None is the answer for every node that declares no `OnFailure`, which
        is every node in every workflow written before this — and the comment
        on the `except` that calls this still reads *"a step failure stops the
        walk"*, because for them it does.

        **The chosen route is recorded and read back**, never re-evaluated.
        That is the property `_choice_for` already holds for `ConditionalEdge`,
        extended rather than reinvented, and the reason is sharper here: a
        failure predicate is exactly the kind that pages somebody, so calling
        it again on replay would page them again for a decision already made.

        Recorded under the node's name in the same branch record a conditional
        uses, so one resume reads one fact — a second store of routes would be
        a second thing to keep in agreement.

        Returns:
            The node to continue at; :data:`_ROUTED_TO_END` when the failure is
            routed to `END`; or None when nothing routed it and the walk should
            stop. **Three answers, not two** — "routed, and the route was to
            finish" and "no route" are different, and collapsing them made a
            declared `OnFailure(..., target=END)` fail the walk.
        """
        recorded = self._store.get_branch(self._scope_id, _failure_branch(name))
        if recorded is not None:
            return str(recorded)

        for edge in self._declaration.outgoing(name):
            if not isinstance(edge, OnFailure):
                continue
            if edge.when is not None and not edge.when(exc):
                continue
            target = _ROUTED_TO_END if _is_end(edge.target) else str(edge.target)
            self._store.record_branch(self._scope_id, _failure_branch(name), target)
            return target

        # Nothing routed it. **Not recorded**: a node with no `OnFailure` has
        # made no decision, and writing "no route" for it would put a fact in
        # the store that a later declaration change should be free to alter.
        return None

    def _key(self, name: str) -> str:
        """Step-record key for ``name`` on the pass the walk is currently on.

        Iteration 0 is the key this node has always had, so a graph with no
        `Loop` is byte-identical in the store.
        """
        return iteration_step_key(name, self._iteration)

    def _loops(self) -> tuple[Loop, ...]:
        """Every `Loop` edge in the declaration."""
        return tuple(e for e in self._declaration.edges if isinstance(e, Loop))

    def _resume_iteration(self) -> int:
        """The iteration this walk is entering, derived from the records.

        Derived rather than carried alongside — the same argument
        `workflow_depth` makes for reading nesting out of a scope id: a resumed
        walk in a fresh process has the records and nothing else, and two
        sources for one fact can disagree.

        **This is an optimization, not a correctness requirement**, and saying
        so is the honest version. Starting every resumed walk at 0 produces the
        same executions, because replay skips finished work anyway — measured:
        replacing this with `return 0` failed no test, which is what sent
        anyone to look. What it changes is how much replaying happens first: a
        loop resumed at iteration 900 of 1000 otherwise re-reads 900
        iterations' records before reaching live work, on every resume.

        The property that survives is therefore about *replay*, and that is
        what `test_a_resume_does_not_replay_iterations_it_has_finished` asserts
        — not that the loop continues, which replay guarantees on its own.

        Zero when the graph has no loop, which is every graph that existed
        before this feature.
        """
        loops = self._loops()
        if not loops:
            return 0
        # The furthest any loop has got. A graph with two loops sharing one
        # counter is a known simplification — see `_loop_back`.
        return max(
            current_iteration(
                self._store, self._scope_id, loop.target, loop.max_iterations
            )
            for loop in loops
        )

    def _loop_back(self, name: str, value: Any, iteration: int) -> str | None:
        """The node to return to, or None to carry on out of the loop.

        Three things stop a loop, and the order matters:

        1. **No `Loop` leaves this node** — nothing to decide.
        2. **The bound is reached.** Checked before the condition, so a
           runaway condition costs one extra pass rather than an outage, and
           so the bound means what a reader thinks it means: *at most* this
           many.
        3. **The condition says no.** Called with the source node's return
           value, exactly as `ConditionalEdge` is.

        **One counter for the whole walk**, which is a simplification worth
        naming: two loops in one graph advance the same iteration, so an inner
        loop's passes also count against an outer one's `visited` keys. It is
        correct — nothing runs twice with one key, and nothing legal is pruned
        — but the iteration numbers in the records will read oddly for nested
        loops. A per-loop counter is the honest fix and needs a second identity
        on the record; no shipped graph nests loops, so it is recorded rather
        than guessed at.
        """
        for loop in self._loops():
            if loop.source != name:
                continue
            if iteration + 1 >= loop.max_iterations:
                return None
            if loop.condition is not None and not loop.condition(value):
                return None
            return str(loop.target)
        return None

    def _service_gate(
        self,
        node: Gate,
        name: str,
        ledger: _Ledger,
    ) -> _NodeRun | WalkReport:
        """A gate: replay its deposited payload, resolve it, or block here."""
        payload = self._walk.gate_payload(node.name)
        blocked_reason = ""
        if payload is None:
            strategies = _gate_strategy_list(node, self._prompt_gates)
            if strategies is not None and self._gate_registry is not None:
                from functualize._types.errors import GateResolutionError

                try:
                    model = self._gate_registry.resolve_gate(
                        node.awaits,
                        gate_strategy=strategies,
                        gate_name=node.name,
                    )
                    payload = model.model_dump()
                    self._walk.block(
                        node.name,
                        node.name,
                        model=getattr(node.awaits, "__name__", ""),
                        input_schema=node.awaits.model_json_schema(),
                        tools=[
                            {"tool": spec.name, "bound": sorted(spec.bound)}
                            for spec in node.tool_specs()
                        ],
                        blocked_at=_now(),
                    )
                    self._store.deposit_gate_payload(self._scope_id, node.name, payload)
                except GateResolutionError as exc:
                    # Every rung of the ladder failed. That is a block,
                    # not a crash — but "blocked on triage" alone reads
                    # identically to a gate waiting by design, so carry
                    # the reason. `last_error` names the unregistered
                    # strategies and the package each one needs
                    # (`_gate/_strategy.STRATEGY_PROVIDERS`), which is
                    # the difference between "wait for a human" and
                    # "pip install functualize-ai".
                    blocked_reason = exc.last_error
        if payload is None:
            self._block(node)
            return WalkReport(
                WalkOutcome.BLOCKED,
                self._scope_id,
                tuple(ledger.executed),
                tuple(ledger.replayed),
                blocked_reason=blocked_reason,
                blocked_on=node.name,
                results=ledger.results,
            )
        return _NodeRun(payload, replayed=True)

    def _service_step(
        self,
        node: Step,
        name: str,
        ledger: _Ledger,
    ) -> _NodeRun | WalkReport:
        """A step: replay its recorded value, or run the job it names."""
        record = self._store.get_step(self._scope_id, self._key(name))
        if record is not None and record.get("status") in TERMINAL_SUCCESS:
            return _NodeRun(record.get("return_value"), replayed=True)
        try:
            outcome = self._run_step(name)
        except StepBlocked as blocked:
            # A nested workflow stopped at a gate. The parent
            # blocks *here*, without recording the step as
            # finished, so resuming the child and re-entering
            # replays up to this node and carries on.
            self._store.set_position(self._scope_id, name)
            self._store.set_scope_status(self._scope_id, WalkState.BLOCKED)
            return WalkReport(
                WalkOutcome.BLOCKED,
                self._scope_id,
                tuple(ledger.executed),
                tuple(ledger.replayed),
                blocked_on=blocked.blocked_on,
                results=ledger.results,
            )
        except ScopeCancelledError as stopped:
            # **Before** the broad arm, which is what keeps a cancellation out
            # of `OnFailure`'s reach. A declared route recovers from a failure;
            # a human stopping a workflow is not a failure to recover from, and
            # routing past it would let a graph walk on through the stop.
            return self._cancelled(name, stopped)
        except Exception as exc:  # a step failure stops the walk
            routed = self._failure_route(name, exc)
            if routed is None:
                return self._fail(name, f"{type(exc).__name__}: {exc}")
            return _NodeRun(None, failure_route=routed)
        if isinstance(outcome, StepOutcome):
            return _NodeRun(outcome.value, inputs=outcome.inputs)
        return _NodeRun(outcome)

    def _service_agent(
        self,
        node: AgentStep,
        name: str,
        ledger: _Ledger,
    ) -> _NodeRun | WalkReport:
        """An agent step: replay its recorded value, or delegate to an executor.

        The executor was chosen and checked against the step's requirements in
        ``WorkflowRunner.prelude``, before this walk started — so a missing
        executor cannot reach here, and nothing is resolved twice.
        """
        record = self._store.get_step(self._scope_id, self._key(name))
        if record is not None and record.get("status") in TERMINAL_SUCCESS:
            return _NodeRun(record.get("return_value"), replayed=True)
        if self._run_agent_step is None:
            # A walker built by hand with no executor door. Refused rather than
            # skipped: a step that silently records nothing is worse than one
            # that says why it did not run.
            return self._fail(
                name,
                "no agent step executor is reachable from this walk "
                "(WorkflowRunner supplies the registered one)",
            )
        try:
            result = self._run_agent_step(node)
        except ScopeCancelledError as stopped:
            return self._cancelled(name, stopped)
        except Exception as exc:  # an executor failure stops the walk
            return self._fail(name, f"{type(exc).__name__}: {exc}")
        return _NodeRun(result.value)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_predecessors(
        declaration: WorkflowDeclaration,
    ) -> dict[str, list[str]]:
        """``{node: {nodes with an edge into it}}``, END excluded.

        Conditional sources contribute to *every* branch target: which one is
        taken is a runtime fact, and readiness has to be decided before it is
        known.
        """
        preds: dict[str, list[str]] = {node.name: [] for node in declaration.nodes}
        for node in declaration.nodes:
            for target in declaration.successors(node.name):
                into = preds.setdefault(target, [])
                if node.name not in into:
                    into.append(node.name)
        return preds

    def _ready(self, name: str, pending: deque[str]) -> bool:
        """True when nothing still queued can reach a predecessor of ``name``.

        This is what makes a join wait for *both* branches. A predecessor that
        is unreachable from the queue is on a path this walk never took, so it
        is not something to wait for — waiting on it would deadlock the walk
        rather than order it.

        A cycle back to ``name`` makes a predecessor permanently reachable; the
        caller breaks that tie by running the node it has been deferring, since
        a loop that never advances is worse than one edge out of order.
        """
        preds = self._predecessors.get(name)
        if not preds or not pending:
            return True
        if all(node == name for node in pending):
            return True  # only self-deferrals left — break the tie
        upcoming = set(pending) | descendants(self._predecessors, list(pending))
        return not (set(preds) & upcoming)

    def _advance(
        self, name: str, value: Any, inputs: dict[str, Any] | None = None
    ) -> list[str]:
        """Record ``name`` as done and return the nodes it unblocks."""
        return self._walk.complete(
            name,
            choice=self._choice_for(name, value),
            args_hash=_iteration_hash(self._iteration),
            return_value=value,
            inputs=inputs,
            completed_at=_now(),
        )

    def _choice_for(self, name: str, value: Any) -> str | None:
        """Pick the branch out of ``name``, or None if it is unconditional.

        A branch already recorded for this scope is *read*, and the condition
        is not called at all — not merely overridden afterwards. Calling it and
        discarding the answer would still run whatever side effects it has, and
        would still pay for a condition that shells out or hits the network.
        """
        if not self._graph.is_conditional(name):
            return None
        recorded = self._store.get_branch(self._scope_id, name)
        if recorded is not None:
            return recorded
        for edge in self._declaration.outgoing(name):
            if isinstance(edge, ConditionalEdge):
                return edge.condition(value)
        return None

    def _block(self, gate: Gate) -> None:
        """Persist the gate's block, with the schema a resumer must satisfy."""
        self._walk.block(
            gate.name,
            gate.name,
            model=getattr(gate.awaits, "__name__", ""),
            input_schema=gate.awaits.model_json_schema(),
            tools=[
                {"tool": spec.name, "bound": sorted(spec.bound)}
                for spec in gate.tool_specs()
            ],
            blocked_at=_now(),
        )

    def _cancelled(self, node: str, stopped: ScopeCancelledError) -> WalkReport:
        """Stop because a human did, and say so on the record.

        A step reaches this when the workflow it names was cancelled —
        `WorkflowRunner.prelude` refuses a cancelled scope, and the orchestrator
        re-raises the step's own exception rather than a wrapper, so the
        refusal arrives here intact.

        Recorded as a failure it was indistinguishable from a bug in the job,
        and `ScopeCancelledError`'s own docstring says there is no `--force`
        and no un-cancel — so the retry it invited could never work.
        """
        return self._fail(node, str(stopped), status=StepStatus.CANCELLED)

    def _fail(
        self, node: str, error: str, *, status: str = StepStatus.FAILED
    ) -> WalkReport:
        """Record a stopped node and stop the walk.

        The step outcome and the scope status move together, through
        :data:`_SCOPE_STATUS_FOR`. They have to: a scope left `failed` because
        its child was cancelled is a scope someone will retry, and every retry
        re-enters the child and re-raises the same cancellation. An outcome
        with no scope meaning — `timed_out`, which is recorded by whoever takes
        a scope over and is not a verdict on the workflow — cannot reach here,
        and the mapping raises rather than inventing one.

        The `WalkOutcome` stays `FAILED` either way, and deliberately: the walk
        did not reach its end, which is what that enum reports, and every
        surface turns a non-completed walk into a non-zero run. *Why* it
        stopped is on the step and on the scope, which is where both a human
        and a resume look.
        """
        with self._store.batch():
            self._store.record_step(
                self._scope_id,
                self._key(node),
                {"status": status, "return_value": None, "completed_at": _now()},
            )
            self._store.set_position(self._scope_id, node)
            self._store.set_scope_status(self._scope_id, _SCOPE_STATUS_FOR[status])
        return WalkReport(
            WalkOutcome.FAILED,
            self._scope_id,
            failed_node=node,
            error=error,
        )


def _iteration_hash(iteration: int) -> str:
    """The args-hash component that separates one loop pass from the next.

    Empty at iteration 0, so a workflow with no `Loop` writes exactly the
    records it wrote before this feature and nothing is migrated.
    """
    return "" if iteration == 0 else f"loop{iteration}"


def _key(name: str) -> str:
    """Step-record key for a node on the first iteration.

    The args hash is empty because a `Step` takes no arguments — it names a
    registered job and that job's own declaration supplies everything else
    (§A.7). Matrix instances differ by *name*, not by args.

    Loop iterations differ by args hash, which is why
    :meth:`WorkflowWalker._key` exists beside this: the walk knows which pass
    it is on, and a module-level function cannot.
    """
    return step_key(name, "")


def _now() -> str:
    return datetime.now(UTC).isoformat()


#: One node kind's handler: the walker, the node, its graph key, the ledger.
#:
#: The node is ``Any`` because each handler narrows it to its own kind — the
#: table is keyed by class and the loop hands the node straight through.
_NodeHandler = Callable[[WorkflowWalker, Any, str, _Ledger], _NodeRun | WalkReport]

#: The node dispatch: node class → the handler that services it.
#:
#: This table replaced the type test that used to sit inside the walk loop,
#: asking whether each node was a gate and treating everything else as a step
#: (AC-10). The loop now looks a node's class up here and never asks what kind
#: it is holding, so a fourth node kind is a handler plus a row **here** — not
#: an edit to the walk's mechanics, which are load-bearing for diamond joins and
#: for resume. A class absent from the table is refused by name.
#:
#: "Here", not everywhere: two other places also enumerate the node kinds —
#: `workflow/_validation.py::_NODE_TYPES` and `_types/workflow.py::_node_kind`.
#: The claim above was written as though this table were the only one, which it
#: is not (asp A-1). What keeps the three from drifting is
#: `tests/workflow/test_node_kind_registries_agree.py`, which asserts they name
#: the same set in both directions, so a fourth kind added to one of them fails
#: until it reaches the other two.
_NODE_HANDLERS: dict[type, _NodeHandler] = {
    Gate: WorkflowWalker._service_gate,
    Step: WorkflowWalker._service_step,
    AgentStep: WorkflowWalker._service_agent,
}


def _gate_strategy_list(gate: Gate, prompt_gates: bool) -> list[str] | None:
    declared = gate.strategy if hasattr(gate, "strategy") else None
    if declared == "ai_outbound":
        return None  # always block for external AI
    if declared == "ai_inbound":
        return ["ai_inbound", "prompt", "resolve"]
    if declared == "prompt":
        return ["prompt", "resolve"] if prompt_gates else None
    if declared is not None:
        return [declared]  # unknown strategy → try it, fall through to block
    return ["prompt", "resolve"] if prompt_gates else None


#: Recorded when an `OnFailure` routes to `END`.
#:
#: A sentinel string rather than `None`, because the branch record has to tell
#: "this failure was routed, and the route was to finish" apart from "no route
#: was ever recorded" — and a resume reads that record instead of calling the
#: predicate again. Collapsing the two made a declared `OnFailure(target=END)`
#: fail the walk, which the test for it caught.
#:
#: A NUL prefix so it cannot collide with a node name: node names are
#: identifier-ish, and nothing that reaches a graph can contain one.
_ROUTED_TO_END = "\x00end"

#: The scope status a *stopped* step implies.
#:
#: A table rather than reusing the step outcome directly, even though these two
#: happen to be spelled the same in both vocabularies. `StepStatus` and the
#: scope's statuses are separate on purpose (`frontier.StepStatus`), and an
#: outcome with no scope meaning must raise here rather than quietly becoming
#: one — `timed_out` is recorded by whoever takes a scope over, which is not a
#: verdict on the workflow and has no business stamping it.
_SCOPE_STATUS_FOR: dict[str, str] = {
    StepStatus.FAILED: "failed",
    StepStatus.CANCELLED: "cancelled",
}


def _failure_branch(name: str) -> str:
    """The branch-record key a node's failure route is stored under.

    Namespaced away from the node's own name so a node that has *both* a
    `ConditionalEdge` and an `OnFailure` keeps two distinct records — one for
    which branch it took when it succeeded, one for where it went when it did
    not.
    """
    return f"{name}\x00onfailure"


def _is_end(target: str | _EndSentinel) -> bool:
    """True if a route target is the END sentinel rather than a node name."""
    return target is END or isinstance(target, _EndSentinel)
