"""Walking a `@workflow` job's graph, before its body runs (§A.7).

Extracted from ``JobExecutionEngine`` (engine-sealed-construction/T6). The
engine's job is the **lifecycle** — context, DI, config, guards, the body, the
unwind — and the workflow prelude is a different subject that happened to live
in the same class: it builds a `WorkflowRunner`, defines what running one step
means, and turns a walk's outcome into the `JobResult` the lifecycle returns
instead of the body.

**A pure Move Method.** The body below is the one that was in ``executor.py``,
with ``self.x`` rebound to ``self._engine.x`` and nothing else changed. Behaviour
is identical by construction, which is what lets
``tests/engine/test_lifecycle_order.py`` stay green across the move rather than
being edited to match it.

It holds the engine rather than a narrower port, deliberately: ``run_step``
**re-enters** ``engine.run`` for every step, so a port for this would have to
expose the entry point itself, plus the registry, the state store, the two
capability registries and the live-value channel — which is the engine. A port
that is a rename of its one implementation buys nothing. The seal this feature
is building is around *construction* (`EngineHost`, `build_engine`), and this
object is constructed by the engine it serves.

**Four of those reaches are to private names** (``_validate_workflows_once``,
``_state_store``, ``_gate_registry``, ``_agent_step_registry``). That is a
friend relationship inside one private package, not a layer being crossed —
this class *was* four methods of that class an hour ago. It is worth saying out
loud rather than leaving to be discovered, because the reach that motivated this
whole feature (``engine._app``) looked the same and was not: that one crossed
from the kernel *out* to its owner, and every one of these stays inside
``_engine``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from functualize._types import JobResult, RunStatus
from functualize._types.run_request import nested_request

if TYPE_CHECKING:
    from functualize._engine.executor import JobExecutionEngine
    from functualize._types.run_request import RunRequest

__all__ = ["WorkflowOrchestrator"]


class WorkflowOrchestrator:
    """The `@workflow` prelude: walk the graph, and say what the body should do."""

    __slots__ = ("_engine",)

    def __init__(self, engine: JobExecutionEngine) -> None:
        self._engine = engine

    def prelude(
        self,
        job_name: str,
        declaration: Any,
        *,
        scope_id: str | None,
        invoke_depth: int,
        start_time: float,
        request: RunRequest | None = None,
    ) -> tuple[Any, JobResult | None]:
        """Walk a `@workflow` job's graph before its body runs.

        Returns the runner (so the caller can record the epilogue) and, when
        the body must not run, the `JobResult` to return instead.
        """
        # Validate before walking, not only at boot. `register_dynamic_job`
        # never calls the boot validator, so a dynamically registered workflow
        # reached a live walk unchecked — the same second-door shape SG closed
        # for the job graph. Validation is memoized per registry generation, so
        # this costs one pass rather than one per invocation.
        self._engine._validate_workflows_once()

        from functualize._engine.workflow_runner import WorkflowRunner
        from functualize._engine.workflow_walker import (
            StepBlocked,
            StepOutcome,
            WalkOutcome,
        )

        def run_step(step_name: str) -> Any:
            entry = self._engine.get_job(step_name)
            step_result = self._engine.run(
                nested_request(
                    request,
                    job_name=step_name,
                    surface="engine.step",
                    invoke_depth=invoke_depth + 1,
                    # Run the step *inside* the scope, so a `FromJob` parameter
                    # resolves against what the walk has already recorded rather
                    # than falling through to the fingerprint store and, finding
                    # nothing, silently taking the parameter's default.
                    #
                    # Unless the step is itself a workflow: a nested workflow owns
                    # its own scope (§A.7), and handing it the parent's would make
                    # the two walks share one set of step records and one epilogue
                    # slot — the inner body's return value would surface as the
                    # outer's.
                    # A nested workflow's scope is *derived*, not fresh. It must
                    # still be its own scope — sharing the parent's would merge
                    # two sets of step records and two epilogue slots, surfacing
                    # the inner body's return value as the outer's — but it must
                    # also be the *same* scope on re-entry, or a gate inside it
                    # can never be resumed: each parent run would spawn a new
                    # child, and the input an agent deposited would belong to a
                    # scope nothing re-enters (Part I cell G×W×W).
                    workflow_scope_id=(
                        f"{runner.scope_id}::{step_name}"
                        if getattr(entry.function, "__functualize_workflow__", None)
                        else runner.scope_id
                    ),
                )
            )
            # SKIPPED counts as satisfied: a step whose guards or fingerprint
            # said "no work to do" has done its job, and failing the walk over
            # it would make declaring a cache on a step break every workflow
            # using it.
            # A nested workflow that stopped at a gate has not failed. It
            # must reach the parent walk as a block, or the parent records the
            # step failed, marks its own scope failed, and resuming the child
            # leaves the parent permanently failed (Part I cell G×W×W).
            if step_result.status is RunStatus.BLOCKED:
                raise StepBlocked(
                    str(step_result.metadata.get("workflow_scope") or ""),
                    str(step_result.metadata.get("blocked_on") or step_name),
                )
            if step_result.status not in (RunStatus.SUCCESS, RunStatus.SKIPPED):
                # Surface the step's own exception rather than a wrapper, so
                # the walk records the reason the step actually failed.
                raise step_result.exception or RuntimeError(
                    f"step {step_name!r} returned {step_result.status.value}"
                )
            # Keep the in-process value for the walk's lifetime. If this
            # step's return cannot be carried through the state store, a later
            # step reading it with `FromJob` has nowhere else to look, and
            # re-running is not available inside a walk (resolved 19b).
            self._engine.publish_live_step_value(
                runner.scope_id, step_name, step_result.return_value
            )

            return StepOutcome(
                step_result.return_value,
                dict(step_result.metadata.get("resolved_inputs") or {}),
            )

        runner = WorkflowRunner(
            self._engine._state_store(),
            run_step=run_step,
            scope_id=scope_id,
            gate_registry=self._engine._gate_registry,
            agent_step_registry=self._engine._agent_step_registry,
            request=request,
            # From the request, not from the app. This used to reach two
            # attributes deep into the engine's back-reference to the app for a
            # value the CLI boundary had deposited there before dispatch — so
            # two concurrent runs shared one answer, and the kernel depended on
            # an attribute the app is not obliged to have. run-request/T12
            # removed the deposits; the request carries this per run. (Worded
            # without naming the removed attributes: the gates that count them
            # in this file never matched a sentence that described them
            # instead.)
            prompt_gates=(request.prompt_gates if request is not None else False),
        )
        run = runner.prelude(job_name, declaration)
        if run.should_run_body:
            return runner, None

        duration_ms = (time.perf_counter() - start_time) * 1000
        metadata: dict[str, Any] = {
            "workflow_scope": run.scope_id,
            "workflow_status": run.outcome.value,
        }
        if run.body_done:
            # An already-completed scope: replaying it is a no-op that answers
            # with the value the body returned the first time.
            return None, JobResult(
                status=RunStatus.SUCCESS,
                return_value=run.body_value,
                duration_ms=duration_ms,
                metadata=metadata,
                job_name=job_name,
            )
        if run.outcome is WalkOutcome.BLOCKED:
            metadata["blocked_on"] = run.blocked_on
            # Present only when there is something to say — a gate waiting by
            # design has no reason to give, and an always-present empty key
            # would make consumers guard for it.
            if run.blocked_reason:
                metadata["blocked_reason"] = run.blocked_reason
            return None, JobResult(
                status=RunStatus.BLOCKED,
                return_value=None,
                duration_ms=duration_ms,
                metadata=metadata,
                job_name=job_name,
            )
        return None, JobResult(
            status=RunStatus.FAILURE,
            return_value=None,
            duration_ms=duration_ms,
            metadata=metadata,
            exception=RuntimeError(run.error) if run.error else None,
            job_name=job_name,
        )
