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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from functualize._primitives.state_store import StateStore

__all__ = ["END", "FrontierWalk", "GraphModel", "WalkState"]

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
    """

    entry: str
    edges: Mapping[str, Sequence[str]] = field(default_factory=dict)
    conditional: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def is_conditional(self, node: str) -> bool:
        return node in self.conditional

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


class FrontierWalk:
    """Expands a graph's frontier at runtime, persisting position and records.

    Args:
        graph: The graph to walk.
        store: State store for §D.7c/§D.7d persistence.
        scope_id: The scope these records belong to.
    """

    def __init__(self, graph: GraphModel, store: StateStore, scope_id: str) -> None:
        self._graph = graph
        self._store = store
        self._scope_id = scope_id

    # ------------------------------------------------------------------
    # Walk control
    # ------------------------------------------------------------------

    def start(self, workflow: str | None = None) -> list[str]:
        """Begin (or resume) the walk, returning the nodes now runnable.

        Resuming is *replay*: a scope with a persisted position resumes there
        rather than re-entering at the graph entry.
        """
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
        status: str = "success",
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
        """
        record = self._store.get_step(self._scope_id, step_key(node, args_hash))
        return bool(record and record.get("status") == "success")

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
