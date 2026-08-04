"""Workflow graph vocabulary — Step, Gate, Edge, ConditionalEdge, END.

The declarative building blocks of a workflow graph. A workflow is **topology
only**: nodes name things that already exist (registered jobs) or things the
walker knows how to do (gates), and edges wire them together. Anything that
would make the graph a second, parallel way of *writing* logic was deliberately
left out — that is what the decorated function's epilogue body is for.

Two node kinds:

- :class:`Step` wraps a reference to a registered job. It carries no behavior
  of its own; the job's own ``@job`` declaration (deps, guards, caching) is
  what runs. A `Step` is therefore a generalized dependency edge with a
  position in a graph.
- :class:`Gate` is a first-class pause: the walker blocks, publishes the
  awaited schema, and resumes when input is deposited. Gates used to be a
  ``Step(awaits_input=...)`` flag, which made "a node that runs a job" and "a
  node that waits for a human" the same type with mutually exclusive fields.

Node identity is the node's ``name``: for a `Step` the referenced job name, for
a `Gate` its declared name. Edges reference nodes by that name.

Lives in ``_types`` (not the public ``functualize.workflow`` package) for the
same reason ``JobDeclaration`` does: boot and discovery must read declarations,
and internal layers may not import the public surface. ``functualize.workflow``
re-exports these as the user-facing facade.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from functualize._types.job_declaration import _ref_name

if TYPE_CHECKING:
    from pydantic import BaseModel

__all__ = [
    "END",
    "ConditionalEdge",
    "Edge",
    "Gate",
    "Step",
    "Tool",
    "ToolRef",
    "WorkflowDeclaration",
    "WorkflowEdgeShape",
    "WorkflowNodeShape",
    "WorkflowShape",
    "_EndSentinel",
    "workflow_shape_of",
]


class _EndSentinel:
    """Sentinel marking workflow termination.

    A singleton instance is exposed as ``END`` and can be used as a target
    in Edge or ConditionalEdge to indicate that the workflow should terminate.
    Reaching ``END`` is what triggers the epilogue body.
    """

    _instance: _EndSentinel | None = None

    def __new__(cls) -> _EndSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "END"


END: _EndSentinel = _EndSentinel()


def _job_ref_name(job: str | Callable[..., Any]) -> str:
    """Resolve a job reference to the name that identifies it in the graph.

    Delegates to :func:`~functualize._types.job_declaration._ref_name`, which
    is what `Deps` and the dependency graph already use.

    This used to be its own resolver, and it dropped the group: a `Step` naming
    a grouped job by callable produced the bare ``compile_it`` while the job
    registered as ``build.compile_it``, so the workflow node matched nothing.
    That is the same divergence that shipped once through the dependency
    resolvers — one fact, several implementations, discovered in production.
    Boot-time resolution against the registry stays a separate concern; this
    only has to produce a graph key, but it must be *the same* key.
    """
    if isinstance(job, str):
        # The walk marker is a reserved sentinel, not an address. Normalizing
        # it would strip the underscores that make it unmistakable and collide
        # it with any job named `end`.
        if job == "__end__":
            return job
        return _ref_name(job)
    if not isinstance(getattr(job, "__name__", None), str) or not job.__name__:
        raise TypeError(
            f"Step job reference must be a string or a named callable, got {job!r}"
        )
    return _ref_name(job)


@dataclass(frozen=True)
class Step:
    """A workflow node that runs a registered job.

    Attributes:
        job: The job to run — its registered name, or the decorated function
            itself. Nothing else: a step does not define behavior, it points
            at behavior that is already declared and independently runnable.
    """

    job: str | Callable[..., Any]

    def __post_init__(self) -> None:
        if isinstance(self.job, str):
            if not self.job.strip():
                raise ValueError("Step job reference must not be empty")
            return
        if not callable(self.job):
            raise TypeError(
                f"Step job must be a registered job name or a callable, "
                f"got {type(self.job).__name__}"
            )

    @property
    def name(self) -> str:
        """The graph key for this node (the referenced job's name)."""
        return _job_ref_name(self.job)


class Tool:
    """A job offered at a gate, with some of its arguments fixed by the gate.

    A tool *is* a registered job — there is no second kind of callable thing in
    this framework. What a `Tool` adds is **narrowing**: arguments pinned here
    are removed from the schema the agent is shown, so a forbidden call is not
    merely refused, it is inexpressible::

        Gate(
            name="approval",
            awaits=RefundDecision,
            tools=[order_history, Tool(issue_refund, cap_cents=5_000)],
        )

    The agent sees `issue_refund(order_id, amount_cents)` and never learns
    `cap_cents` exists. Passing it anyway is an error rather than a silent
    override: an agent that believes it set a value and did not is worse off
    than one told no.

    This has to live at the gate rather than on the job, because it is a
    property of the *usage*. The same `issue_refund` may be capped at $50 in a
    self-serve workflow and uncapped in a supervisor one, and its signature
    cannot know which workflow is calling.

    A bare job reference stays legal wherever no narrowing is wanted —
    `tools=[order_history]` is not worth a wrapper.

    Args:
        job: The job to offer — its registered name or the decorated function.
            Positional-only, so a job with a parameter named ``job`` can still
            have it bound.
        **bound: Arguments fixed by this gate.
    """

    __slots__ = ("_bound", "_job")

    # Annotations only — no assignment, so they coexist with __slots__ while
    # giving the type checker something better than Any to work with.
    _job: str | Callable[..., Any]
    _bound: dict[str, Any]

    def __init__(self, job: str | Callable[..., Any], /, **bound: Any) -> None:
        if isinstance(job, str):
            if not job.strip():
                raise ValueError("Tool job reference must not be empty")
        elif not callable(job):
            raise TypeError(
                f"Tool job must be a registered job name or a callable, "
                f"got {type(job).__name__}"
            )
        from functualize._types.from_job import FromJob

        for arg, value in bound.items():
            if isinstance(value, FromJob):
                raise TypeError(
                    f"Tool({_job_ref_name(job)!r}, {arg}=FromJob(...)) is not "
                    f"valid — use FromStep({value.name!r}) instead. A gate "
                    f"tool's argument is read from this walk's recorded "
                    f"results and can never trigger a job: the agent calls "
                    f"the tool on demand, outside the graph's ordering, and "
                    f"the step has already run because the graph ordered it "
                    f"before the gate."
                )
        object.__setattr__(self, "_job", job)
        object.__setattr__(self, "_bound", dict(bound))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Tool is immutable")

    @property
    def job(self) -> str | Callable[..., Any]:
        """The referenced job."""
        return self._job

    @property
    def bound(self) -> dict[str, Any]:
        """Arguments this gate fixes, as a copy."""
        return dict(self._bound)

    @property
    def name(self) -> str:
        """The referenced job's name."""
        return _job_ref_name(self.job)

    def __repr__(self) -> str:
        if not self._bound:
            return f"Tool({self.name!r})"
        pinned = ", ".join(f"{k}={v!r}" for k, v in self._bound.items())
        return f"Tool({self.name!r}, {pinned})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Tool):
            return NotImplemented
        return self.name == other.name and self.bound == other.bound

    def __hash__(self) -> int:
        return hash((self.name, tuple(sorted(self._bound))))


ToolRef = str | Callable[..., Any] | Tool


def _as_tool(ref: ToolRef) -> Tool:
    """Normalize any accepted tool reference to a `Tool`."""
    return ref if isinstance(ref, Tool) else Tool(ref)


_VALID_GATE_STRATEGIES: frozenset[str] = frozenset(
    {"resolve", "prompt", "ai_inbound", "ai_outbound"}
)


@dataclass(frozen=True)
class Gate:
    """A workflow node that pauses for input.

    When the walker reaches a gate it records a BLOCKED position, publishes
    ``awaits``'s JSON schema, and stops. Depositing valid input resumes the
    walk; the deposited payload is available to the epilogue body.

    Attributes:
        name: Graph key for this node, and the address used to resume it.
        awaits: Pydantic model describing the input the gate requires.
        tools: Jobs an external agent may run while resolving this gate — a
            permission, not a hint, enforced at MCP dispatch. Each entry is a
            job name, a decorated function, or a :class:`Tool` when the gate
            needs to pin some of that job's arguments. Capped at 50: a longer
            list is a sign the gate is being used as a general-purpose agent
            handoff rather than an input request. An empty list asks for no
            restriction.
        strategy: Preferred resolution strategy. One of ``"resolve"``
            (config chain), ``"prompt"`` (interactive surface), ``"ai_inbound"``
            (LLM generation), or ``"ai_outbound"`` (external AI via MCP).
            ``None`` (default) defers to the walker's policy (block unless a
            CLI flag overrides).
    """

    name: str
    awaits: type[BaseModel]
    tools: Sequence[ToolRef] = ()
    strategy: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Gate name must be a non-empty string")
        # A gate name is a node address — the string used to resume it — so it
        # canonicalizes like every other address.
        object.__setattr__(self, "name", _job_ref_name(self.name))
        if self.strategy is not None and self.strategy not in _VALID_GATE_STRATEGIES:
            raise ValueError(
                f"Gate strategy must be one of {sorted(_VALID_GATE_STRATEGIES)}, "
                f"got {self.strategy!r}"
            )
        if len(self.tools) > 50:
            raise ValueError(
                f"Gate tools must have at most 50 entries, got {len(self.tools)}"
            )
        object.__setattr__(self, "tools", tuple(self.tools))
        names = [_as_tool(ref).name for ref in self.tools]
        duplicated = {name for name in names if names.count(name) > 1}
        if duplicated:
            # Two entries for one job cannot both be honored — the second's
            # bindings would silently lose to the first at call time.
            raise ValueError(
                f"Gate '{self.name}' lists these tools more than once: "
                f"{', '.join(sorted(duplicated))}"
            )
        from pydantic import BaseModel as _BaseModel

        if not (isinstance(self.awaits, type) and issubclass(self.awaits, _BaseModel)):
            raise TypeError(
                f"Gate awaits must be a BaseModel subclass, got {self.awaits!r}"
            )

    def tool_specs(self) -> tuple[Tool, ...]:
        """Every offered tool, normalized to :class:`Tool`."""
        return tuple(_as_tool(ref) for ref in self.tools)


@dataclass(frozen=True)
class Edge:
    """Unconditional directed connection between two workflow nodes.

    Attributes:
        source: Name of the source node.
        target: Name of the target node, or ``END`` to terminate the walk.
    """

    source: str
    target: str | _EndSentinel = field(default_factory=lambda: END)

    def __post_init__(self) -> None:
        # Endpoints name nodes, and node names are canonical — so an edge
        # written `Edge("travel_plan", "book")` must land on the same strings
        # `Step.name` produces, or validation rejects a graph that is correct.
        object.__setattr__(self, "source", _job_ref_name(self.source))
        if isinstance(self.target, str):
            object.__setattr__(self, "target", _job_ref_name(self.target))


@dataclass(frozen=True)
class ConditionalEdge:
    """Branching connection where the target depends on a runtime condition.

    The chosen key is recorded per scope on first evaluation and replayed on
    resume, so a walk that pauses cannot resume down a different branch than
    the one it paused on (§D.7).

    Attributes:
        source: Name of the source node.
        condition: Callable returning a key into ``targets``.
        targets: Mapping of condition keys to node names or ``END``.
    """

    source: str
    condition: Callable[..., str]
    targets: dict[str, str | _EndSentinel]

    def __post_init__(self) -> None:
        # Same reason as `Edge`: every endpoint here names a node, and node
        # names are canonical.
        object.__setattr__(self, "source", _job_ref_name(self.source))
        object.__setattr__(
            self,
            "targets",
            {
                key: _job_ref_name(target) if isinstance(target, str) else target
                for key, target in self.targets.items()
            },
        )


def workflow_shape_of(func: Any) -> WorkflowShape | None:
    """Project a decorated function's ``@workflow`` graph to its cached shape.

    Returns None for anything that is not a workflow, so discovery can call it
    unconditionally at every extraction site.
    """
    declaration = getattr(func, "__functualize_workflow__", None)
    if not isinstance(declaration, WorkflowDeclaration):
        return None
    return declaration.shape()


@dataclass(frozen=True)
class WorkflowNodeShape:
    """One node of a cached graph: its key, its kind, and (gates) its model.

    ``model`` is the awaited model's *class name*, not the class — resolving it
    back needs the defining module, which is exactly the import warm boot
    avoids. Callers that need the JSON schema materialize the job first.
    """

    name: str
    kind: str  # "step" | "gate"
    model: str | None = None


@dataclass(frozen=True)
class WorkflowEdgeShape:
    """One edge of a cached graph.

    ``None`` as a target means ``END`` — it terminates the walk and is not a
    node. Conditional edges keep every branch target but not the condition
    itself, which is a callable and cannot survive a JSON round-trip.
    """

    source: str
    target: str | None = None
    conditional: bool = False
    targets: tuple[tuple[str, str | None], ...] = ()


@dataclass(frozen=True)
class WorkflowShape:
    """The cache-serializable projection of a :class:`WorkflowDeclaration`.

    A deliberately *different* type, not a lossy `WorkflowDeclaration`. The
    declaration holds live objects — condition callables, `BaseModel`
    subclasses — that cannot be JSON round-tripped, and reconstructing a
    declaration-shaped value from cached names would produce something that
    looks callable and is not. What survives is the topology: node names,
    node kinds, edges, branch targets. Anything else materializes on demand,
    which is what keeps warm boot import-free (§A.7, schema §2).
    """

    nodes: tuple[WorkflowNodeShape, ...] = ()
    edges: tuple[WorkflowEdgeShape, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))

    @property
    def entry(self) -> str | None:
        """The node the walk starts from — the first declared node."""
        return self.nodes[0].name if self.nodes else None

    def step_names(self) -> tuple[str, ...]:
        """Names of every `Step` node, in declaration order."""
        return tuple(n.name for n in self.nodes if n.kind == "step")

    def gate_names(self) -> tuple[str, ...]:
        """Names of every `Gate` node, in declaration order."""
        return tuple(n.name for n in self.nodes if n.kind == "gate")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the schema §2 ``workflow`` cache entry."""
        nodes: list[dict[str, Any]] = []
        for node in self.nodes:
            if node.kind == "gate":
                nodes.append({"gate": node.name, "model": node.model})
            else:
                nodes.append({"step": node.name})

        edges: list[dict[str, Any]] = []
        for edge in self.edges:
            if edge.conditional:
                edges.append(
                    {
                        "from": edge.source,
                        "conditional": True,
                        "targets": dict(edge.targets),
                    }
                )
            else:
                edges.append({"from": edge.source, "to": edge.target})

        return {"steps": nodes, "edges": edges}

    @classmethod
    def from_dict(cls, data: Any) -> WorkflowShape | None:
        """Rebuild from a cache entry, tolerating anything malformed.

        A corrupt or partial entry yields ``None`` (rebuild the cache) rather
        than a half-populated graph — a graph missing an edge would walk
        somewhere the author never declared.
        """
        if not isinstance(data, dict):
            return None

        nodes: list[WorkflowNodeShape] = []
        for raw in data.get("steps") or ():
            if not isinstance(raw, dict):
                return None
            if "gate" in raw:
                nodes.append(
                    WorkflowNodeShape(
                        name=str(raw["gate"]), kind="gate", model=raw.get("model")
                    )
                )
            elif "step" in raw:
                nodes.append(WorkflowNodeShape(name=str(raw["step"]), kind="step"))
            else:
                return None

        edges: list[WorkflowEdgeShape] = []
        for raw in data.get("edges") or ():
            if not isinstance(raw, dict) or "from" not in raw:
                return None
            if raw.get("conditional"):
                targets = raw.get("targets")
                if not isinstance(targets, dict):
                    return None
                edges.append(
                    WorkflowEdgeShape(
                        source=str(raw["from"]),
                        conditional=True,
                        targets=tuple((str(k), v) for k, v in targets.items()),
                    )
                )
            else:
                edges.append(
                    WorkflowEdgeShape(source=str(raw["from"]), target=raw.get("to"))
                )

        return cls(nodes=tuple(nodes), edges=tuple(edges))


@dataclass(frozen=True)
class WorkflowDeclaration:
    """The frozen graph attached by ``@workflow`` (mirrors ``JobDeclaration``).

    Holds the declared topology as written. Step refs are resolved against the
    registry at boot, not here — a declaration is readable without a live app,
    which is what lets discovery serialize the graph shape into the cache.
    """

    nodes: tuple[Step | Gate, ...] = ()
    edges: tuple[Edge | ConditionalEdge, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))

    @property
    def entry(self) -> str | None:
        """The node the walk starts from — the first declared node.

        Declaration order is the entry point rather than "the node with no
        inbound edge": a graph may legitimately loop back to its first node,
        which would leave that rule with no answer.
        """
        return self.nodes[0].name if self.nodes else None

    def node(self, name: str) -> Step | Gate | None:
        """Look up a node by its graph key."""
        for node in self.nodes:
            if node.name == name:
                return node
        return None

    def step_refs(self) -> tuple[str | Callable[..., Any], ...]:
        """Every `Step`'s job reference, in declaration order.

        Boot resolves these against the registry; gates have no job to resolve.
        """
        return tuple(node.job for node in self.nodes if isinstance(node, Step))

    def gates(self) -> tuple[Gate, ...]:
        """Every `Gate` node, in declaration order."""
        return tuple(node for node in self.nodes if isinstance(node, Gate))

    def outgoing(self, source: str) -> tuple[Edge | ConditionalEdge, ...]:
        """Every edge leaving ``source``."""
        return tuple(edge for edge in self.edges if edge.source == source)

    def successors(self, source: str) -> tuple[str, ...]:
        """Names of every node reachable in one hop from ``source``.

        ``END`` is not a node and is omitted. Conditional branches contribute
        all their possible targets, since which one is taken is a runtime fact.
        """
        out: list[str] = []
        for edge in self.outgoing(source):
            targets: Sequence[str | _EndSentinel] = (
                tuple(edge.targets.values())
                if isinstance(edge, ConditionalEdge)
                else (edge.target,)
            )
            out.extend(t for t in targets if isinstance(t, str))
        return tuple(out)

    def shape(self) -> WorkflowShape:
        """Project to the cache-serializable topology (schema §2).

        Drops the condition callables and gate model classes; keeps everything
        needed to describe, list, and route the graph without importing the
        module that declared it.
        """
        nodes = tuple(
            WorkflowNodeShape(
                name=node.name,
                kind="gate" if isinstance(node, Gate) else "step",
                model=(
                    getattr(node.awaits, "__name__", None)
                    if isinstance(node, Gate)
                    else None
                ),
            )
            for node in self.nodes
        )

        def _target(value: str | _EndSentinel) -> str | None:
            return value if isinstance(value, str) else None

        edges = tuple(
            WorkflowEdgeShape(
                source=edge.source,
                conditional=True,
                targets=tuple(
                    (key, _target(target)) for key, target in edge.targets.items()
                ),
            )
            if isinstance(edge, ConditionalEdge)
            else WorkflowEdgeShape(source=edge.source, target=_target(edge.target))
            for edge in self.edges
        )
        return WorkflowShape(nodes=nodes, edges=edges)
