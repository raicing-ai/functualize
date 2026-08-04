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

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from functualize._engine.frontier import END as _FRONTIER_END
from functualize._engine.frontier import FrontierWalk, GraphModel, WalkState, step_key
from functualize._primitives.graph import descendants
from functualize._types.workflow import ConditionalEdge, Gate

if TYPE_CHECKING:
    from collections.abc import Callable

    from functualize._primitives.state_store import StateStore
    from functualize._types.workflow import WorkflowDeclaration, _EndSentinel

__all__ = [
    "StepBlocked",
    "StepOutcome",
    "WalkOutcome",
    "WalkReport",
    "WorkflowWalker",
    "graph_model_of",
]


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

    @property
    def ok(self) -> bool:
        """True only when the walk reached ``END``."""
        return self.outcome is WalkOutcome.COMPLETED


def graph_model_of(declaration: WorkflowDeclaration) -> GraphModel:
    """Compile a declaration into the shared graph model (§A.7 one-engine rule).

    ``Deps`` and ``@workflow`` are two vocabularies over one representation, so
    the walker never sees `Step`/`Gate`/`Edge` — it sees the same `GraphModel`
    the dependency scheduler does, with `END` flattened to the frontier's
    terminal marker.
    """
    edges: dict[str, list[str]] = {}
    conditional: dict[str, dict[str, str]] = {}

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
        workflow_name: Job name recorded on the scope, for observers.
        gate_registry: Resolution dispatch for gates. When None (default),
            gates always block.
        prompt_gates: When True, gates without an explicit strategy attempt
            prompt-before-block resolution.
    """

    def __init__(
        self,
        declaration: WorkflowDeclaration,
        store: StateStore,
        scope_id: str,
        *,
        run_step: Callable[[str], Any],
        workflow_name: str | None = None,
        gate_registry: Any = None,
        prompt_gates: bool = False,
    ) -> None:
        self._declaration = declaration
        self._store = store
        self._scope_id = scope_id
        self._run_step = run_step
        self._workflow_name = workflow_name
        self._graph = graph_model_of(declaration)
        self._predecessors = self._build_predecessors(declaration)
        self._walk = FrontierWalk(self._graph, store, scope_id)
        self._gate_registry = gate_registry
        self._prompt_gates = prompt_gates

    def run(self) -> WalkReport:
        """Walk to `END`, to a gate with no input, or to a failure."""
        self._walk.start(self._workflow_name)

        entry = self._declaration.entry
        if entry is None:  # an empty graph is already at its end
            self._store.set_scope_status(self._scope_id, WalkState.COMPLETED)
            return WalkReport(WalkOutcome.COMPLETED, self._scope_id)

        pending: deque[str] = deque([entry])
        visited: set[str] = set()
        executed: list[str] = []
        replayed: list[str] = []
        results: dict[str, Any] = {}

        step_inputs: dict[str, dict[str, Any]] = {}
        deferrals = 0
        while pending:
            name = pending.popleft()
            # A diamond join is reached once per branch but must run once.
            if name in visited:
                continue
            if deferrals <= len(pending) and not self._ready(name, pending):
                # A join whose other branch is still in flight. Breadth-first
                # order is not a topological order — on an asymmetric diamond
                # (a→b→c→join vs d→join) the short branch would otherwise run
                # the join before the long one finished.
                #
                # The counter bounds this: once every queued node has been
                # deferred once with nothing running in between, they are
                # waiting on each other (a cycle), and one edge out of order
                # beats spinning forever.
                pending.append(name)
                deferrals += 1
                continue
            deferrals = 0
            visited.add(name)

            node = self._declaration.node(name)
            if node is None:
                # Boot validation resolves every edge target, so this means the
                # declaration changed under a live scope rather than a typo.
                return self._fail(name, f"unknown node {name!r} in the graph")

            if isinstance(node, Gate):
                payload = self._walk.gate_payload(node.name)
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
                            self._store.deposit_gate_payload(
                                self._scope_id, node.name, payload
                            )
                        except GateResolutionError:
                            pass
                if payload is None:
                    self._block(node)
                    return WalkReport(
                        WalkOutcome.BLOCKED,
                        self._scope_id,
                        tuple(executed),
                        tuple(replayed),
                        blocked_on=node.name,
                        results=results,
                    )
                value: Any = payload
                replayed.append(name)
            else:
                record = self._store.get_step(self._scope_id, _key(name))
                if record is not None and record.get("status") == "success":
                    value = record.get("return_value")
                    replayed.append(name)
                else:
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
                            tuple(executed),
                            tuple(replayed),
                            blocked_on=blocked.blocked_on,
                            results=results,
                        )
                    except Exception as exc:  # a step failure stops the walk
                        return self._fail(name, f"{type(exc).__name__}: {exc}")
                    if isinstance(outcome, StepOutcome):
                        value, step_inputs[name] = outcome.value, outcome.inputs
                    else:
                        value = outcome
                    executed.append(name)

            results[name] = value
            pending.extend(self._advance(name, value, step_inputs.get(name, {})))

        self._store.set_scope_status(self._scope_id, WalkState.COMPLETED)
        return WalkReport(
            WalkOutcome.COMPLETED,
            self._scope_id,
            tuple(executed),
            tuple(replayed),
            results=results,
        )

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

    def _fail(self, node: str, error: str) -> WalkReport:
        """Record a failed node and stop the walk."""
        self._store.record_step(
            self._scope_id,
            _key(node),
            {"status": "failed", "return_value": None, "completed_at": _now()},
        )
        self._store.set_position(self._scope_id, node)
        self._store.set_scope_status(self._scope_id, "failed")
        return WalkReport(
            WalkOutcome.FAILED,
            self._scope_id,
            failed_node=node,
            error=error,
        )


def _key(name: str) -> str:
    """Step-record key for a node.

    The args hash is empty because a `Step` takes no arguments — it names a
    registered job and that job's own declaration supplies everything else
    (§A.7). Matrix instances differ by *name*, not by args.
    """
    return step_key(name, "")


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
