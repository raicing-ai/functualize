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

if TYPE_CHECKING:
    from functualize._primitives.state_store import StateStore
    from functualize._types.workflow import WorkflowDeclaration

__all__ = ["WorkflowRun", "WorkflowRunner", "new_scope_id"]


def new_scope_id() -> str:
    """A fresh scope identifier for one workflow invocation."""
    return uuid.uuid4().hex[:16]


@dataclass(frozen=True)
class WorkflowRun:
    """The prelude's verdict on whether the body should run.

    Attributes:
        outcome: How the walk ended.
        scope_id: The scope this invocation ran in — the handle a resume needs.
        blocked_on: Gate name, when the walk stopped for input.
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
    """

    def __init__(
        self,
        store: StateStore,
        *,
        run_step: Any,
        scope_id: str | None = None,
        gate_registry: Any = None,
        prompt_gates: bool = False,
    ) -> None:
        self._store = store
        self._run_step = run_step
        self._scope_id = scope_id or new_scope_id()
        self._gate_registry = gate_registry
        self._prompt_gates = prompt_gates

    @property
    def scope_id(self) -> str:
        return self._scope_id

    def prelude(self, job_name: str, declaration: WorkflowDeclaration) -> WorkflowRun:
        """Walk the graph and decide whether the body runs."""
        report = WorkflowWalker(
            declaration,
            self._store,
            self._scope_id,
            run_step=self._run_step,
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
