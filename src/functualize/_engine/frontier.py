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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from functualize._primitives.scope_store import ScopeStore

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
    """

    def __init__(self, graph: GraphModel, store: ScopeStore, scope_id: str) -> None:
        self._graph = graph
        self._store = store
        self._scope_id = scope_id
        #: The lease generation this walk holds, or None if it never claimed.
        #: Set by `claim`; every scope write it makes carries it (T6).
        self._generation: int | None = None

    # ------------------------------------------------------------------
    # The lease (`durable-run-layer`/T5, T6)
    # ------------------------------------------------------------------

    def claim(self, *, owner: str | None = None, force: bool = False) -> int:
        """Take the scope, and fence every write this walk makes.

        Returns the generation claimed. After this, a write from *any* other
        holder of this scope is refused — which is what closes the
        concurrent-`resume` limitation: the second walk's writes stop, rather
        than interleaving with the first's into a record neither would
        recognise.

        Raises:
            LeaseHeldError: Another runner holds it and has not expired. Pass
                ``force`` only for an explicit reclaim, where a human has
                decided the holder is gone.
        """
        from functualize._primitives.lease import DEFAULT_LEASE_SECONDS
        from functualize._primitives.run_store import runner_identity

        self._store.ensure_scope(self._scope_id)
        # Read before claiming, write after. The question is about the state
        # the *previous* holder left, and claiming overwrites the lease that
        # answers it; the write waits until this walk holds the generation
        # that fences it.
        silent = self._step_that_went_silent()
        lease = self._store.claim_scope(
            self._scope_id,
            owner=owner or runner_identity(),
            seconds=DEFAULT_LEASE_SECONDS,
            force=force,
        )
        self._generation = int(lease.generation)
        self._store.hold(self._scope_id, lease.generation)
        if silent is not None:
            self._record_timed_out(silent)
        return int(lease.generation)

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
        from datetime import UTC, datetime

        from functualize._primitives.lease import is_expired, read_lease

        scope = self._store.get_scope(self._scope_id)
        if not scope or scope.get("status") != WalkState.RUNNING:
            return None
        lease = read_lease(scope)
        if lease is None or not is_expired(lease, datetime.now(UTC)):
            return None
        position = scope.get("position")
        if not isinstance(position, str) or not position:
            return None
        if self._store.get_step(self._scope_id, step_key(position, "")) is not None:
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
        self._store.record_step(
            self._scope_id,
            step_key(node, ""),
            {
                "status": StepStatus.TIMED_OUT,
                "return_value": None,
                "return_value_reusable": False,
                "completed_at": "",
            },
        )

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
        from functualize._primitives.run_store import runner_identity

        try:
            self._store.renew_scope(
                self._scope_id, owner=runner_identity(), generation=self._generation
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
            self._store.release_scope(self._scope_id, generation=self._generation)
        except Exception:  # noqa: BLE001 - releasing is never worth a failure
            logger.debug("could not release the scope lease", exc_info=True)
        finally:
            self._generation = None
            self._store.hold(self._scope_id, None)

    # ------------------------------------------------------------------
    # Walk control
    # ------------------------------------------------------------------

    def start(self, workflow: str | None = None) -> list[str]:
        """Begin (or resume) the walk, returning the nodes now runnable.

        Resuming is *replay*: a scope with a persisted position resumes there
        rather than re-entering at the graph entry.
        """
        with self._store.batch():
            self._store.ensure_scope(self._scope_id, workflow)
            position = self._store.get_position(self._scope_id)
            if position is not None:
                return [position]
            self._store.set_scope_status(self._scope_id, WalkState.RUNNING)
            self._store.set_position(self._scope_id, self._graph.entry)
        return [self._graph.entry]

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
        # One locked write for the node, not three. Everything inside is
        # in-memory — `classify_return_value` and the graph lookups touch no
        # disk — so the lock is held for microseconds. An exception in here
        # discards the node's writes rather than leaving two of three applied.
        with self._store.batch():
            self._store.record_step(
                self._scope_id,
                step_key(node, args_hash),
                {
                    "status": status,
                    "return_value": stored if reusable else None,
                    "return_value_reusable": reusable,
                    "return_value_kind": kind,
                    "return_value_type": type_name,
                    "inputs": dict(inputs or {}),
                    "completed_at": completed_at,
                    # Recorded on the step, not looked up from the declaration
                    # on resume (`durable-run-layer`/T9). A resume may happen in
                    # another process against a declaration that has since
                    # changed; what mattered is what the step *was* when it ran.
                    # The record is the only witness to that.
                    "effecting": self._graph.is_effecting(node),
                },
            )

            if self._graph.is_conditional(node):
                choice = self._resolve_branch(node, choice)

            successors = self._graph.successors(node, choice)
            runnable = [n for n in successors if n != END]

            if not successors or successors == [END]:
                self._store.set_position(self._scope_id, None)
                self._store.set_scope_status(self._scope_id, WalkState.COMPLETED)
                return []

            self._store.set_position(self._scope_id, runnable[0] if runnable else None)
        return runnable

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
        """Persist a BLOCKED position and its gate payload slot (§D.7b/c).

        The walk stops here until input is deposited; because position and gate
        both persist, a different process can observe and resume it.

        ``tools`` is persisted alongside the schema so an agent that finds this
        gate over MCP learns what it may use to answer it without importing the
        declaring module — the same reason the schema itself is persisted.
        Each entry is ``{"tool": name, "bound": [param names]}``: the *names*
        of pinned parameters, never their values. Names are all a reader needs
        to strip them from the schema it publishes, and they are always
        JSON-safe, whereas a bound value is arbitrary. The values are read from
        the declaration at call time, which has to import it anyway to run the
        job.
        """
        with self._store.batch():
            self._store.set_position(self._scope_id, node)
            self._store.set_scope_status(self._scope_id, WalkState.BLOCKED)
            self._store.put_gate(
                self._scope_id,
                gate_name,
                {
                    "model": model,
                    "input_schema": dict(input_schema or {}),
                    "tools": [dict(entry) for entry in tools],
                    "payload": None,
                    "blocked_at": blocked_at,
                },
            )

    def gate_payload(self, gate_name: str) -> Any:
        """Deposited input for a gate, or None while still blocked."""
        gate = self._store.get_gate(self._scope_id, gate_name)
        return None if gate is None else gate.get("payload")

    def is_blocked(self) -> bool:
        scope = self._store.get_scope(self._scope_id)
        return bool(scope and scope.get("status") == WalkState.BLOCKED)

    def completed_steps(self) -> dict[str, Any]:
        """Every step recorded in this scope (drives replay-skip)."""
        scope = self._store.get_scope(self._scope_id)
        return dict(scope.get("steps", {})) if scope else {}

    def should_replay_skip(self, node: str, args_hash: str = "") -> bool:
        """True when this step already completed in this scope (§D.7d).

        Resume re-invokes the workflow; a step that already succeeded here must
        not run twice.

        Asks :data:`TERMINAL_SUCCESS` rather than comparing the string, so a
        step recorded `failed`, `timed_out` or `cancelled` runs again — and so
        that the day a second success-like outcome exists, it becomes
        replayable by a decision instead of by a comparison nobody re-read.
        """
        record = self._store.get_step(self._scope_id, step_key(node, args_hash))
        return bool(record and record.get("status") in TERMINAL_SUCCESS)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_branch(self, node: str, choice: str | None) -> str | None:
        """Return the branch to take, preferring the one already recorded.

        Recording on first evaluation and *reading* on replay is what stops a
        non-deterministic condition (a clock, a random, a changed file) from
        moving a resumed walk onto a different branch than it paused on.
        """
        recorded = self._store.get_branch(self._scope_id, node)
        if recorded is not None:
            return recorded
        if choice is not None:
            self._store.record_branch(self._scope_id, node, choice)
        return choice


def step_key(job_name: str, args_hash: str = "") -> str:
    """Per-scope step-record key: ``<job_name>::<args_hash>`` (§D.7d)."""
    return f"{job_name}::{args_hash}"
