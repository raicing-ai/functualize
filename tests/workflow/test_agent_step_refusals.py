"""Agent steps refuse before the walk — capability flags, and no executor.

The whole point of the port is *where* the refusal happens. A step whose
executor cannot honour what it declared must not run "with the constraint
quietly dropped", and it must not be refused halfway through a walk either:
by then the earlier nodes' side effects have happened for a step that was
never going to run. So every refusal here is asserted before the first node,
with the store still empty.

Nothing in this module asserts that an agent step *runs* — that is
``test_agent_step_walk.py`` (the port reaching a real walk), and the refusals
below are the other half of the same contract: what must never be reached by
running instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from functualize._engine.agent_step import AgentStepRegistry
from functualize._engine.workflow_runner import WorkflowRunner
from functualize._engine.workflow_walker import WalkOutcome
from functualize._primitives.state_store import StateStore
from functualize._types.errors import (
    AgentCapabilityRefusedError,
    AgentExecutorUnavailableError,
)
from functualize._types.protocols import (
    AgentCapability,
    AgentStepContext,
    AgentStepExecutor,
    AgentStepResult,
)
from functualize._types.run_request import RunRequest
from functualize._types.workflow import (
    END,
    AgentStep,
    Edge,
    Step,
    WorkflowDeclaration,
    workflow_shape_of,
)
from functualize.workflow import Gate
from functualize.workflow._decorator import workflow

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import BaseModel


class Approval(BaseModel):
    """Gate schema used where a graph mixes gates and agent steps."""

    granted: bool = True


class _Executor:
    """A minimal `AgentStepExecutor`: a name, the flags it declares, and a log.

    Declaring nothing is a legal executor — that is `cli-prompt`'s own shape —
    and it is what makes the refusal paths reachable without a plugin.
    """

    def __init__(
        self,
        name: str,
        capabilities: frozenset[AgentCapability] = frozenset(),
    ) -> None:
        self.name = name
        self.capabilities = capabilities
        self.calls: list[AgentStepContext] = []

    def execute(self, ctx: AgentStepContext) -> AgentStepResult:
        self.calls.append(ctx)
        return AgentStepResult(value=f"{ctx.step_name}-done")


class _Recorder:
    """A `run_step` that records what ran, so "nothing ran" is provable."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, name: str) -> Any:
        self.calls.append(name)
        return f"{name}-result"


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "state.json")


def _registry(*executors: _Executor) -> AgentStepRegistry:
    registry = AgentStepRegistry()
    for executor in executors:
        registry.register(executor)
    return registry


def _with_predecessor(agent_step: AgentStep) -> WorkflowDeclaration:
    """A graph where an ordinary step precedes ``agent_step``.

    The predecessor is the point: it proves the refusal happened *before* the
    walk rather than at the node. Decided at the node, `forecast` would have
    run first — and its side effects would be real.
    """
    return WorkflowDeclaration(
        nodes=(Step("forecast"), agent_step),
        edges=(
            Edge(source="forecast", target=agent_step.name),
            Edge(source=agent_step.name, target=END),
        ),
    )


def _declaration(*nodes: Any, edges: tuple[Edge, ...] = ()) -> WorkflowDeclaration:
    return WorkflowDeclaration(nodes=nodes, edges=edges)


# ─── The port itself ──────────────────────────────────────────────────────


class TestThePortIsAPort:
    """AC-1, executable: structural, never a base class to inherit from."""

    def test_the_executor_port_is_a_runtime_checkable_protocol_not_an_abc(self) -> None:
        """A plugin implements the port without importing it, and `isinstance`
        stays legal — which is what lets the registry refuse a half-declared
        executor instead of discovering it mid-walk."""
        assert getattr(AgentStepExecutor, "_is_protocol", False)
        assert getattr(AgentStepExecutor, "_is_runtime_protocol", False)
        assert not any(
            getattr(base, "__name__", "") in {"ABC", "ABCMeta"}
            for base in AgentStepExecutor.__mro__
        ), f"the port must not inherit an ABC: {AgentStepExecutor.__mro__}"


# ─── The declaration itself ───────────────────────────────────────────────


class TestTheDeclaration:
    """What an `AgentStep` says about itself, before any registry is involved."""

    def test_declaring_tools_implies_the_capability_that_enforces_them(self) -> None:
        """R-c, made concrete: the author's intent is folded into `requires`."""
        step = AgentStep(name="draft", instructions="draft it", tools=("deploy",))
        assert step.requires == frozenset({AgentCapability.ENFORCES_TOOL_ALLOWLIST})

    def test_a_time_budget_implies_the_capability_that_honours_it(self) -> None:
        step = AgentStep(name="draft", instructions="draft it", time_budget_s=30.0)
        assert step.requires == frozenset(
            {AgentCapability.PRESERVES_ACTIVE_TIME_BUDGET}
        )

    def test_an_explicit_requirement_is_widened_by_the_implied_one(self) -> None:
        """Explicitly widenable, never narrowed implicitly."""
        step = AgentStep(
            name="draft",
            instructions="draft it",
            tools=("deploy",),
            requires=frozenset({AgentCapability.SUPPORTS_VISIBLE_OUTPUT}),
        )
        assert step.requires == frozenset(
            {
                AgentCapability.ENFORCES_TOOL_ALLOWLIST,
                AgentCapability.SUPPORTS_VISIBLE_OUTPUT,
            }
        )

    def test_a_step_that_declares_nothing_requires_nothing(self) -> None:
        """An empty `tools` is not the same statement as "no tools allowed"."""
        step = AgentStep(name="draft", instructions="draft it")
        assert step.tools == ()
        assert step.requires == frozenset()

    def test_a_workflow_accepts_an_agent_step_beside_edges_and_gates(self) -> None:
        """AC-3's declaration half: the vocabulary is open, the graph unchanged."""

        @workflow(
            steps=[
                AgentStep(name="draft_migration", instructions="write it"),
                Gate(name="approval", awaits=Approval),
            ],
            edges=[
                Edge(source="draft_migration", target="approval"),
                Edge(source="approval", target=END),
            ],
        )
        def release() -> None:
            """Topology only."""

        declaration = release.__functualize_workflow__
        # The node name canonicalizes like every other address, so the edge
        # written from the author's spelling finds it.
        assert declaration.entry == "draft-migration"
        assert declaration.successors("draft-migration") == ("approval",)

    def test_the_cached_shape_keeps_an_agent_node_distinct_from_a_step(self) -> None:
        """A cached graph that called it a step would name a job nobody runs."""

        @workflow(
            steps=[
                Step("forecast"),
                AgentStep(name="draft", instructions="write it"),
            ],
            edges=[
                Edge(source="forecast", target="draft"),
                Edge(source="draft", target=END),
            ],
        )
        def flow() -> None:
            """Topology only."""

        shape = workflow_shape_of(flow)
        assert shape is not None
        assert shape.to_dict()["steps"] == [{"step": "forecast"}, {"agent": "draft"}]
        # And it survives the cache round-trip as the same kind.
        assert [node.kind for node in shape.from_dict(shape.to_dict()).nodes] == [
            "step",
            "agent",
        ]
        assert shape.step_names() == ("forecast",)


# ─── A registered executor that cannot honour the step ────────────────────


class TestAnExecutorThatCannotHonourTheStepIsRefused:
    """AC-5 and AC-6: refuse at validation, and say which capability."""

    def test_tools_against_an_executor_with_no_capabilities(
        self, store: StateStore
    ) -> None:
        executor = _Executor("cli-prompt")
        recorder = _Recorder()
        declaration = _with_predecessor(
            AgentStep(
                name="draft-migration", instructions="write it", tools=("deploy",)
            )
        )

        runner = WorkflowRunner(
            store,
            run_step=recorder,
            agent_step_registry=_registry(executor),
        )
        with pytest.raises(AgentCapabilityRefusedError) as caught:
            runner.prelude("release", declaration)

        assert caught.value.capability is AgentCapability.ENFORCES_TOOL_ALLOWLIST
        assert caught.value.executor == "cli-prompt"
        assert "enforces_tool_allowlist" in str(caught.value)
        # Nothing ran: the refusal is a property of the declaration, not of the
        # point in the walk where the node sits.
        assert recorder.calls == []
        assert executor.calls == []
        assert store.get_scope(runner.scope_id) is None

    def test_a_budget_against_an_executor_that_cannot_preserve_it(
        self, store: StateStore
    ) -> None:
        executor = _Executor("ai", frozenset({AgentCapability.ENFORCES_TOOL_ALLOWLIST}))
        runner = WorkflowRunner(
            store,
            run_step=_Recorder(),
            agent_step_registry=_registry(executor),
        )

        with pytest.raises(AgentCapabilityRefusedError) as caught:
            runner.prelude(
                "release",
                _declaration(
                    AgentStep(
                        name="draft",
                        instructions="write it",
                        executor="ai",
                        time_budget_s=60.0,
                    )
                ),
            )

        assert caught.value.capability is AgentCapability.PRESERVES_ACTIVE_TIME_BUDGET
        assert caught.value.declared == (AgentCapability.ENFORCES_TOOL_ALLOWLIST,)
        assert store.get_scope(runner.scope_id) is None

    def test_the_declared_capability_is_enough(self, store: StateStore) -> None:
        """The control for both refusals: declaring it is not refused here."""
        registry = _registry(
            _Executor("ai", frozenset({AgentCapability.ENFORCES_TOOL_ALLOWLIST}))
        )
        registry.check(
            _declaration(
                AgentStep(
                    name="draft",
                    instructions="write it",
                    executor="ai",
                    tools=("deploy",),
                )
            )
        )


# ─── No executor at all ───────────────────────────────────────────────────


class TestAStepWithNoExecutorIsRefused:
    """AC-7: name the package, and never substitute someone else."""

    def test_a_named_executor_nobody_registered_names_its_package(
        self, store: StateStore
    ) -> None:
        runner = WorkflowRunner(
            store,
            run_step=_Recorder(),
            agent_step_registry=_registry(_Executor("cli-prompt")),
        )
        with pytest.raises(AgentExecutorUnavailableError) as caught:
            runner.prelude(
                "release",
                _declaration(
                    AgentStep(name="draft", instructions="write it", executor="ai")
                ),
            )

        assert caught.value.executor == "ai"
        assert caught.value.hint == "install functualize-ai to register it"
        assert "functualize-ai" in str(caught.value)
        assert store.get_scope(runner.scope_id) is None

    def test_a_registered_executor_the_step_did_not_name_is_not_substituted(
        self, store: StateStore
    ) -> None:
        """The refusal is not answered by the executor that *is* registered.

        `cli-prompt` would answer this step by asking a human, which is exactly
        the fallback the spec forbids: it changes who answers the step.
        """
        cli_prompt = _Executor("cli-prompt")
        runner = WorkflowRunner(
            store,
            run_step=_Recorder(),
            agent_step_registry=_registry(cli_prompt),
        )

        with pytest.raises(AgentExecutorUnavailableError):
            runner.prelude(
                "release",
                _declaration(
                    AgentStep(name="draft", instructions="write it", executor="ai")
                ),
            )

        assert cli_prompt.calls == []

    def test_no_executor_registered_at_all_refuses(self, store: StateStore) -> None:
        runner = WorkflowRunner(
            store, run_step=_Recorder(), agent_step_registry=_registry()
        )
        with pytest.raises(AgentExecutorUnavailableError) as caught:
            runner.prelude(
                "release",
                _declaration(AgentStep(name="draft", instructions="write it")),
            )

        assert caught.value.executor is None
        assert caught.value.registered == ()
        # A core name gets no install hint: if `cli-prompt` is missing, the
        # answer is not "install something", it is that the registry was built
        # by hand.
        assert caught.value.hint == ""

    def test_no_executor_named_where_two_are_registered_is_refused(
        self, store: StateStore
    ) -> None:
        """ "The single registered one" is a unique answer, or it is a refusal."""
        runner = WorkflowRunner(
            store,
            run_step=_Recorder(),
            agent_step_registry=_registry(_Executor("cli-prompt"), _Executor("ai")),
        )
        with pytest.raises(AgentExecutorUnavailableError) as caught:
            runner.prelude(
                "release",
                _declaration(AgentStep(name="draft", instructions="write it")),
            )

        assert caught.value.registered == ("ai", "cli-prompt")
        # The message, not only the payload. This assertion was missing, and
        # the sentence underneath it read "has no executor registered for it
        # (registered: ai, cli-prompt)" — a contradiction in eleven words, on
        # the case a user is most likely to hit (asp M-1). One `_message()`
        # branch was covering two situations that need different sentences.
        message = str(caught.value)
        assert "names no executor and 2 are registered" in message, message
        assert "has no executor registered for it" not in message, message

    def test_the_only_registered_executor_is_what_none_resolves_to(self) -> None:
        """The single-executor case is the *only* thing `None` is allowed to mean."""
        registry = _registry(_Executor("cli-prompt"))
        step = AgentStep(name="draft", instructions="write it")
        assert registry.resolve(step).name == "cli-prompt"


# ─── Registration is a door, not a formality ──────────────────────────────


class TestRegistration:
    """AC-11's first half: a forgotten declaration fails where it is declared."""

    def test_an_object_without_capabilities_cannot_be_registered(self) -> None:
        """A missing `capabilities` is a startup failure, not a mid-walk one."""

        class HalfExecutor:
            name = "half"

            def execute(self, ctx: AgentStepContext) -> AgentStepResult:
                return AgentStepResult(value=None)

        registry = AgentStepRegistry()
        with pytest.raises(TypeError, match="AgentStepExecutor"):
            registry.register(HalfExecutor())  # type: ignore[arg-type]

    def test_a_name_cannot_be_registered_twice(self) -> None:
        """Two implementations of one name would make resolution arbitrary."""
        registry = _registry(_Executor("ai"))
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_Executor("ai"))


# ─── Parity test 4: a checkpoint already answered grants nothing ──────────


class TestAPreviouslyAnsweredCheckpoint:
    """pi-workflows parity test 4, in this framework's vocabulary.

    The pi-workflows test reads *"a gate marked protected cannot be answered by
    an agent that answered the previous checkpoint"*. A node is *protected*
    here when it requires a capability its executor does not declare, and the
    refusal is the capability-flag one — so the property under test is the
    "even though" half: authority is per **node**, never per scope, and a
    checkpoint this same executor already answered in this same scope is not a
    grant. A test that only asserted the refusal on a fresh scope would not
    test that property at all; it would pass for a framework where one success
    opened the rest of the walk.

    The mechanism is the resume: run one gets the agent past `checkpoint` and
    stops at the gate, and run two — same scope, same declaration, an executor
    that declares less — is refused at `apply` with the checkpoint's `success`
    record sitting in the scope.
    """

    @staticmethod
    def _request() -> RunRequest:
        """The run an agent step's executor is told about.

        A walk built by hand must supply one: the port carries the request as
        provenance, and a walker that invented one would be fabricating where
        the run came from.
        """
        return RunRequest(job_name="release", surface="engine.step")

    def _declaration(self) -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(
                AgentStep(name="checkpoint", instructions="Do the first half"),
                Gate(name="approve", awaits=Approval),
                AgentStep(name="apply", instructions="Apply it", tools=("deploy",)),
            ),
            edges=(
                Edge(source="checkpoint", target="approve"),
                Edge(source="approve", target="apply"),
                Edge(source="apply", target=END),
            ),
        )

    def _run_one(
        self, store: StateStore, capability: frozenset[AgentCapability]
    ) -> AgentStepContext:
        """First invocation: the agent answers the checkpoint, then the gate blocks."""
        executor = _Executor("agent-x", capability)
        report = WorkflowRunner(
            store,
            run_step=_Recorder(),
            scope_id="parity-4",
            agent_step_registry=_registry(executor),
            request=self._request(),
        ).prelude("release", self._declaration())

        assert report.blocked_on == "approve"
        return executor.calls[0]

    def test_the_checkpoint_was_answered_by_the_agent(self, store: StateStore) -> None:
        """The premise, asserted rather than assumed: without it the refusal
        below would be indistinguishable from a walk that never ran."""
        answered = self._run_one(
            store, frozenset({AgentCapability.ENFORCES_TOOL_ALLOWLIST})
        )

        assert answered.step_name == "checkpoint"
        scope = store.get_scope("parity-4")
        assert scope is not None
        assert scope["steps"]["checkpoint::"]["status"] == "success"
        assert "apply::" not in scope["steps"]

    def test_the_protected_node_refuses_the_same_executor_on_resume(
        self, store: StateStore
    ) -> None:
        self._run_one(store, frozenset({AgentCapability.ENFORCES_TOOL_ALLOWLIST}))
        # The same executor, declaring less: what an app that registered the
        # plugin without the flag, or lost it to an upgrade, hands the walk.
        weaker = _Executor("agent-x")
        runner = WorkflowRunner(
            store,
            run_step=_Recorder(),
            scope_id="parity-4",
            agent_step_registry=_registry(weaker),
            request=self._request(),
        )

        with pytest.raises(AgentCapabilityRefusedError) as caught:
            runner.prelude("release", self._declaration())

        assert caught.value.step_name == "apply"
        assert caught.value.capability is AgentCapability.ENFORCES_TOOL_ALLOWLIST
        assert weaker.calls == []
        scope = store.get_scope("parity-4")
        assert scope is not None
        # The checkpoint's authority did not carry: it is still recorded, and
        # `apply` has no record at all — refused, not attempted and failed.
        assert scope["steps"]["checkpoint::"]["status"] == "success"
        assert "apply::" not in scope["steps"]

    def test_a_capable_executor_resumes_the_same_scope_past_that_node(
        self, store: StateStore
    ) -> None:
        """The control. Without it, the refusal above could be a walk that
        simply cannot resume, and the checkpoint's record would say nothing."""
        self._run_one(store, frozenset({AgentCapability.ENFORCES_TOOL_ALLOWLIST}))
        store.deposit_gate_payload("parity-4", "approve", {"granted": True})
        capable = _Executor(
            "agent-x", frozenset({AgentCapability.ENFORCES_TOOL_ALLOWLIST})
        )

        report = WorkflowRunner(
            store,
            run_step=_Recorder(),
            scope_id="parity-4",
            agent_step_registry=_registry(capable),
            request=self._request(),
        ).prelude("release", self._declaration())

        assert report.outcome is WalkOutcome.COMPLETED
        assert [call.step_name for call in capable.calls] == ["apply"]
