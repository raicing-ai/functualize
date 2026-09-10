"""The agent-step port's registry, and the two refusals that guard it.

An `AgentStep` is serviced by an executor that is **registered** on the app —
``app.register_agent_step_executor`` — and never auto-discovered.
Auto-discovery is how a surface acquires behaviour nobody declared, and this is
the one node kind whose behaviour lives outside the process. `GateResolver` is
the template, down to the registration door.

**The engine refuses rather than degrades.** Two things are checked, both
*before* the walk's first node:

- an `AgentStep` naming an executor nobody registered, or naming none where the
  answer is not unique → :class:`AgentExecutorUnavailableError`, which says
  which package supplies it
- an executor that cannot honour what the step requires →
  :class:`AgentCapabilityRefusedError`

Neither is substituted. A step declared as an agent's work is not handed to a
human instead — a fallback that changes who answers is a different program —
and it is not handed to *another* executor, whose capabilities are not the ones
the step declared.

The check runs in ``WorkflowRunner.prelude``, the one point every continuation
passes through (the same reason the cancelled-scope rule lives there). Refusing
mid-walk would leave side effects already performed for a step that was never
going to run.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from functualize._engine.agent_providers import missing_executor_hint
from functualize._engine.surface_routing import active_collector
from functualize._types.errors import (
    AgentCapabilityRefusedError,
    AgentExecutorUnavailableError,
)
from functualize._types.interactivity import (
    InputNotAvailable,
    PromptIntent,
    PromptRequest,
)
from functualize._types.protocols import (
    AgentCapability,
    AgentStepContext,
    AgentStepExecutor,
    AgentStepResult,
)
from functualize._types.workflow import AgentStep

if TYPE_CHECKING:
    from functualize._types.interactivity import PromptCollector
    from functualize._types.run_request import RunRequest
    from functualize._types.workflow import WorkflowDeclaration

__all__ = ["AgentStepRegistry", "CliPromptExecutor"]

#: What an agent step binds into its executor's work, when the declaration
#: binds nothing.
#:
#: `AgentStep` declares `instructions`, not input bindings, so there is nothing
#: for the walk to resolve into this mapping yet. It is a shared empty mapping
#: rather than a fresh dict per step: the context is frozen and never mutated,
#: and one object keeps an agent step from being the only node kind that
#: allocates per execution.
_NO_INPUTS: MappingProxyType[str, Any] = MappingProxyType({})


class AgentStepRegistry:
    """The agent-step executors this app will run steps with.

    Keyed by the executor's own ``name``, which is what ``AgentStep.executor``
    refers to and what ``_engine.agent_providers.EXECUTOR_PROVIDERS`` names a
    package for.

    Registration is the only door, and it is deliberately closed to anything
    that is not an `AgentStepExecutor`: a missing ``capabilities`` declaration
    surfacing as an ``AttributeError`` halfway through a walk would be a
    runtime surprise for something a startup check can refuse.
    """

    def __init__(self) -> None:
        self._executors: dict[str, AgentStepExecutor] = {}

    def register(self, executor: object) -> None:
        """Register ``executor`` under its own name.

        ``executor`` is deliberately typed ``object``: this door is reached
        dynamically — a plugin's entry point, a registry built by hand, a test
        double — so the runtime check below *is* the contract rather than a
        formality a type checker has already enforced.

        Raises:
            TypeError: ``executor`` does not satisfy `AgentStepExecutor`.
            ValueError: Its name is empty, or already registered. The second
                registration is refused rather than replacing the first: a
                step resolving to one of two implementations with the same name
                is exactly the ambiguity this port exists to eliminate.
        """
        if not isinstance(executor, AgentStepExecutor):
            raise TypeError(
                "An agent step executor must satisfy AgentStepExecutor: a `name`, "
                "a `capabilities` set, and `execute(ctx)`. "
                f"Got {type(executor).__name__}, which does not. Refused here "
                "because the alternative is a missing declaration surfacing "
                "mid-walk."
            )
        name = executor.name
        if not name.strip():
            raise ValueError(
                f"An agent step executor must declare a non-empty name, got {name!r}"
            )
        if name in self._executors:
            raise ValueError(
                f"An agent step executor named '{name}' is already registered "
                f"({type(self._executors[name]).__name__}). Registration is "
                "refused rather than replaced, so a step naming it cannot "
                "silently reach a different implementation than the one the "
                "first registration was vetted as."
            )
        self._executors[name] = executor

    def names(self) -> tuple[str, ...]:
        """Every registered executor name, sorted — for diagnostics."""
        return tuple(sorted(self._executors))

    def resolve(self, step: AgentStep) -> AgentStepExecutor:
        """The executor that services ``step``, or a refusal saying why not.

        Raises:
            AgentExecutorUnavailableError: ``step`` named an executor that is
                not registered, or named none where exactly one cannot be
                identified — none registered, or several. Nothing is guessed:
                an executor the step did not name cannot honour what it
                declared.
        """
        if step.executor is None:
            if len(self._executors) == 1:
                return next(iter(self._executors.values()))
            raise AgentExecutorUnavailableError(
                step.name, None, registered=self.names()
            )

        executor = self._executors.get(step.executor)
        if executor is None:
            raise AgentExecutorUnavailableError(
                step.name,
                step.executor,
                registered=self.names(),
                hint=missing_executor_hint(step.executor),
            )
        return executor

    def check(self, declaration: WorkflowDeclaration) -> None:
        """Refuse every agent step in ``declaration`` that cannot be serviced.

        Raises:
            AgentExecutorUnavailableError: The step has no executor.
            AgentCapabilityRefusedError: The executor it resolved to does not
                declare something the step requires.

        The first missing capability is reported, in name order, so the refusal
        is deterministic when a step needs several — and the remedy is the same
        for each of them: an executor that declares what the step requires.
        """
        for node in declaration.nodes:
            if not isinstance(node, AgentStep):
                continue
            executor = self.resolve(node)
            missing = node.requires - executor.capabilities
            if missing:
                raise AgentCapabilityRefusedError(
                    node.name,
                    executor=executor.name,
                    capability=min(missing, key=str),
                    declared=sorted(executor.capabilities, key=str),
                )

    def execute(
        self, step: AgentStep, *, request: RunRequest | None
    ) -> AgentStepResult:
        """Run one agent step through the executor that services it.

        ``request`` is the run's own `RunRequest`: it carries where the run
        came from and what it was asked for, and the port hands it to the
        executor rather than restating those fields. A walk with no request
        cannot supply it, and inventing one would be fabricating provenance, so
        that is a refusal rather than a default.
        """
        executor = self.resolve(step)
        if request is None:
            raise RuntimeError(
                f"Agent step {step.name!r} reached a walk with no RunRequest, so "
                "its executor cannot be told where the run came from. Every "
                "entry surface builds a RunRequest before dispatching; a walk "
                "built by hand must pass one."
            )
        ctx = AgentStepContext(
            request=request,
            step_name=step.name,
            instructions=step.instructions,
            tools=tuple(step.tools),
            inputs=_NO_INPUTS,
            time_budget_s=step.time_budget_s,
        )
        return executor.execute(ctx)


class CliPromptExecutor:
    """Core's own agent step executor: it asks a person to perform the step.

    Declares **no** capabilities, and that is not an oversight — it can enforce
    nothing about what the person on the other end does. `tools=[…]`, a time
    budget, or a required live output are all refused against it, which makes
    this the fixture for every refusal path as well as the proof the port is
    wired end to end: a bare app has exactly one executor, so an `AgentStep`
    that names none resolves to this one.

    It is registered by `_app.boot` through the same
    ``app.register_agent_step_executor`` door a plugin uses. Nothing
    auto-discovers it, because nothing auto-discovers an executor.

    The question is the step's own ``instructions``, asked through the active
    surface; with no surface to ask (a headless run, a non-interactive
    process) it raises :class:`InputNotAvailable` rather than inventing an
    answer. That is a *failure of this executor*, not a fallback to some other
    one — there is no other one.
    """

    name: str = "cli-prompt"
    capabilities: frozenset[AgentCapability] = frozenset()

    def __init__(self, host: Any = None) -> None:
        # The **host**, not the owning application object.
        # `engine-sealed-construction/T4` replaced every such reach-through in
        # `_engine/` with a host call and its gate records `after: 0`. This
        # executor was written on a parallel branch that predated the seal, so
        # it arrived carrying two fresh ones and put the count back to 2 — a
        # semantic conflict `git` merged cleanly, because the two branches never
        # touched the same line. (Worded without naming the attribute: T4's gate
        # counts it in this directory, and a comment quoting it would hold the
        # count at 1 forever — that has happened six times on this branch.)
        #
        # Found by the test that re-runs every finished task's gate, which is
        # the only thing that could have found it: `ruff`, `mypy` and all six
        # import-linter contracts were green with the reach-throughs in place.
        self._host = host

    def _collector(self) -> PromptCollector | None:
        host = self._host
        if host is None:
            return None
        collector = getattr(host, "collector", None)
        if callable(collector):
            return cast("PromptCollector | None", collector())
        # An owner that is not a host (a direct construction in a test) still
        # answers the same question through the surface router.
        return active_collector(host)

    def execute(self, ctx: AgentStepContext) -> AgentStepResult:
        """Ask the active surface to perform ``ctx``'s step.

        Raises:
            InputNotAvailable: No surface can answer.
        """
        provider = self._collector()
        if provider is None:
            raise InputNotAvailable(
                f"No Surface is available to perform agent step "
                f"{ctx.step_name!r}. The 'cli-prompt' executor asks a person, "
                "so it needs an interactive terminal or a registered surface."
            )
        response = provider.collect(
            PromptRequest(
                question=ctx.instructions,
                intent=PromptIntent.TEXT_INPUT,
                required=True,
                source_step=ctx.step_name,
            )
        )
        return AgentStepResult(value=response.value)
