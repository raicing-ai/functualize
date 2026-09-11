"""Workflow-as-job: the graph is a prelude, the body is the job (§A.7).

The unification this module implements, stated once in the proposal: *`@workflow`
is a generalized `Deps` — the graph is a richer prelude; the body is the job.*

So a workflow job executes in two phases. First the **walk**
(:mod:`functualize._engine.workflow_walker`) runs the declared graph. Only if it
reaches `END` does the decorated function's own body run, as an ordinary job
with ordinary DI. That is what makes a workflow indistinguishable from any other
job to everything downstream — which in turn is why workflows chain and nest
with no composition feature at all: `Deps(wf)` orders on it, `Step(wf)` nests it
(the nested run gets its own child scope through the normal invoke path).

**Body-once-per-scope.** Resume re-invokes the whole job, so without a record
the body would run again every time an already-finished scope was replayed. The
epilogue record is that guard, and it holds the body's return value so a replay
answers with the same value rather than a fresh one.

Each fresh invocation creates a new scope; passing an existing ``scope_id`` is
what makes an invocation a *resume* rather than a new run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from functualize._engine.workflow_walker import WalkOutcome, WorkflowWalker
from functualize._types.errors import ScopeCancelledError

if TYPE_CHECKING:
    from functualize._engine.agent_step import AgentStepRegistry
    from functualize._primitives.state_store import StateStore
    from functualize._types.protocols import AgentStepResult
    from functualize._types.run_request import RunRequest
    from functualize._types.workflow import AgentStep, WorkflowDeclaration

__all__ = ["WorkflowRun", "WorkflowRunner", "new_scope_id"]


def new_scope_id(job_name: str | None = None) -> str:
    """A fresh scope identifier for one run.

    Named after the job when the caller knows it — ``deploy-8f3c1a2b`` — because
    this id is what a human is handed to resume with, and a bare hex string
    tells them nothing about which workflow they are resuming.

    **One generator.** There were two: this one minted ``<hex16>`` and
    `app.execute` minted ``<job>-<hex8>``, so the id a user was told to type
    depended on which door started the run. Two test suites each asserted a
    different shape, which is how a divergence survives.
    """
    tail = uuid.uuid4().hex[:8]
    return f"{job_name}-{tail}" if job_name else uuid.uuid4().hex[:16]


@dataclass(frozen=True)
class WorkflowRun:
    """The prelude's verdict on whether the body should run.

    Attributes:
        outcome: How the walk ended.
        scope_id: The scope this invocation ran in — the handle a resume needs.
        blocked_on: Gate name, when the walk stopped for input.
        blocked_reason: Why the gate could not be resolved, when a strategy
            ladder was tried and every rung failed. Empty for a gate waiting
            by design — the two are indistinguishable from ``blocked_on``
            alone, which is the whole point of carrying it.
        error: Failure detail, when a step raised.
        body_done: True when this scope already ran its body; ``body_value``
            holds what it returned. The body must not run a second time.
        body_value: The recorded body return value when ``body_done``.
    """

    outcome: WalkOutcome
    scope_id: str
    blocked_on: str | None = None
    error: str = ""
    body_done: bool = False
    body_value: Any = None
    blocked_reason: str = ""

    @property
    def should_run_body(self) -> bool:
        """True only when the walk reached `END` and the body has not run."""
        return self.outcome is WalkOutcome.COMPLETED and not self.body_done


class WorkflowRunner:
    """Runs a workflow job's graph and guards its epilogue body.

    Args:
        store: State store holding the scope's records.
        run_step: Executes one step job by node name, returning its value.
        scope_id: Resume an existing scope; omit to start a fresh one.
        gate_registry: Resolution dispatch for gates.
        prompt_gates: Whether a gate without an explicit strategy may be
            answered by prompting.
        agent_step_registry: The registered agent step executors. Defaults to
            an empty registry, which refuses any agent step — a walk built
            without one cannot quietly run a step with no executor behind it.
        request: The run this walk belongs to, handed to an agent step's
            executor as provenance. None is legal for a graph with no agent
            steps; a graph with one refuses at its first agent step rather than
            fabricating a request.
    """

    def __init__(
        self,
        store: StateStore,
        *,
        run_step: Any,
        scope_id: str | None = None,
        gate_registry: Any = None,
        prompt_gates: bool = False,
        agent_step_registry: AgentStepRegistry | None = None,
        request: RunRequest | None = None,
    ) -> None:
        self._store = store
        self._run_step = run_step
        self._scope_id = scope_id or new_scope_id()
        self._gate_registry = gate_registry
        self._prompt_gates = prompt_gates
        self._request = request
        if agent_step_registry is None:
            from functualize._engine.agent_step import AgentStepRegistry as _Registry

            agent_step_registry = _Registry()
        self._agent_step_registry = agent_step_registry

    @property
    def scope_id(self) -> str:
        return self._scope_id

    def _run_agent_step(self, step: AgentStep) -> AgentStepResult:
        """Hand one agent step to its registered executor.

        The executor was chosen during :meth:`prelude`, so this resolves the
        same step to the same executor rather than making a second decision.
        The walk's `RunRequest` travels with it: it is what tells the executor
        where the run came from, and it is the only legal way one is supplied.
        """
        return self._agent_step_registry.execute(step, request=self._request)

    def prelude(self, job_name: str, declaration: WorkflowDeclaration) -> WorkflowRun:
        """Walk the graph and decide whether the body runs.

        Raises:
            ScopeCancelledError: The scope was cancelled. Checked here, before
                the walk, because this is the one point every continuation
                passes through — the CLI, the MCP tools and the `--wf-*` flags
                all reach a walk by constructing a runner and calling this.
                Enforcing it at each surface would be three copies of a rule
                and a fourth surface away from being wrong.
            AgentExecutorUnavailableError: The graph declares an agent step
                with no executor to run it.
            AgentCapabilityRefusedError: An agent step requires something its
                executor cannot honour.
        """
        scope = self._store.get_scope(self._scope_id)
        if scope is not None and scope.get("status") == "cancelled":
            raise ScopeCancelledError(
                self._scope_id, workflow=scope.get("workflow") or job_name
            )

        # Before the walk, for the same reason as the rule above — and before
        # `FrontierWalk.start` writes anything, so a refused declaration leaves
        # the store exactly as it was. Running an agent step whose executor
        # cannot honour it would enforce nothing while appearing to; refusing
        # it mid-walk would have performed the earlier nodes' side effects
        # first.
        self._agent_step_registry.check(declaration)

        report = WorkflowWalker(
            declaration,
            self._store,
            self._scope_id,
            run_step=self._run_step,
            run_agent_step=self._run_agent_step,
            workflow_name=job_name,
            gate_registry=self._gate_registry,
            prompt_gates=self._prompt_gates,
        ).run()

        if report.outcome is not WalkOutcome.COMPLETED:
            return WorkflowRun(
                report.outcome,
                self._scope_id,
                blocked_on=report.blocked_on,
                error=report.error,
                blocked_reason=report.blocked_reason,
            )

        recorded = self._store.get_epilogue(self._scope_id)
        if recorded is not None:
            return WorkflowRun(
                report.outcome,
                self._scope_id,
                body_done=True,
                body_value=recorded.get("return_value"),
            )
        return WorkflowRun(report.outcome, self._scope_id)

    def record_body(self, return_value: Any, *, status: str = "success") -> None:
        """Record the epilogue so a replay of this scope does not re-run it."""
        self._store.record_epilogue(
            self._scope_id,
            {
                "status": status,
                "return_value": return_value,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
