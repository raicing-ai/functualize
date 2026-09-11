"""Running a job's declared dependency graph, before its own pre-flight.

Extracted from ``JobExecutionEngine`` (engine-sealed-construction/T7), a sibling
move to ``workflow_orchestrator``. Scheduling upstreams is its own subject: it
owns a plan, a diamond-safe traversal, the rule that a node already run inside a
walk is not run again, and the `FromJob` values carried in-process because the
store cannot hold them.

**A pure Move Method**, like T6: the three bodies below are the ones that were
in ``executor.py``, with ``self.x`` rebound to ``self._engine.x`` and nothing
else changed.

``_declared_dep_names`` stayed on the engine and is reached through it, because
``app/core.py`` calls it too. Moving it would have meant editing an unrelated
public class in a refactoring commit, and `engine-sealed-construction`/T9 is the
task that puts that class on a diet — this one should not pre-empt it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._types import JobResult, RunStatus
from functualize._types.run_request import nested_request

if TYPE_CHECKING:
    from functualize._engine.executor import JobExecutionEngine

__all__ = ["DependencyRunner"]


class DependencyRunner:
    """Runs the upstreams a job declared, in an order that runs each once."""

    __slots__ = ("_engine",)

    def __init__(self, engine: JobExecutionEngine) -> None:
        self._engine = engine

    def _unreusable_upstreams(self, function: Any) -> set[str]:
        """Upstreams a `FromJob` needs whose recorded value cannot be reused.

        Those must actually run: the dependent asked for a value, and the only
        copy of it is the one the body produces. Freshness cannot stand in —
        it certifies files, and this value was never storable.

        `run=False` is excluded by construction: it means "read what is
        recorded, cause no work", so a missing value is the answer it asked
        for rather than a reason to run anything.
        """
        from functualize._types.from_job import from_job_refs

        store = self._engine._state_store()
        if store is None:
            return set()

        needed: set[str] = set()
        for ref in from_job_refs(function).values():
            if not ref.run:
                continue
            for method in ("checksum", "timestamp", "none"):
                record = store.get_fingerprint(
                    self._engine.fingerprint_key_for(ref.name, method)
                )
                if record is None:
                    continue
                if record.get("return_value_reusable") is False:
                    needed.add(ref.name)
                break
        return needed

    def _scope_step_succeeded(self, scope_id: str, node: str) -> bool:
        """True when ``node`` already completed successfully in this scope.

        Reads the walk's step records — the same ones the walker replays from
        — so "already ran here" has one answer rather than one per consumer.
        """
        store = self._engine._scope_store()
        if store is None:
            return False
        scope = store.get_scope(scope_id)
        for key, record in ((scope or {}).get("steps") or {}).items():
            if key.split("::", 1)[0] == node and isinstance(record, dict):
                return bool(record.get("status") == "success")
        return False

    def run_for(
        self,
        job_name: str,
        function: Any,
        context: Any,
        invoke_depth: int,
        workflow_scope_id: str | None = None,
    ) -> JobResult | None:
        """Run ``job_name``'s dependency graph; None when all succeeded.

        Returns a FAILURE result when a dep failed, so the dependent never
        runs against a half-built world — the whole point of declaring the
        edge.
        """
        # Ask the resolved dependency list, not `Deps` specifically: a job
        # whose only edge comes from a `FromJob` parameter has no `Deps` at
        # all, and asking the wrong question skipped its upstream entirely.
        if not self._engine._declared_dep_names(job_name):
            return None

        from functualize._engine.scheduler import DepScheduler

        order = self._engine.job_graph.order_for(job_name)
        if not order:
            return None
        graph = {node: self._engine.job_graph.deps_of(node) for node in order}

        declaration = getattr(function, "__functualize_job__", None)
        deps = getattr(declaration, "deps", None) if declaration else None
        from functualize._types.from_job import from_job_names

        unreusable_upstreams = self._unreusable_upstreams(function)
        from_job_upstreams = set(from_job_names(function))
        live_values: dict[str, Any] = {}

        def run_node(node: str) -> Any:
            # Inside a walk, a dependency that is *also* a graph node has
            # already run under its node identity — boot validation requires
            # the graph to order it first (Part I cell D×W). Its step record
            # satisfies the edge, so re-running it would execute the same node
            # twice per scope: once as a dependency and once as a node. A
            # non-idempotent job corrupted its own output that way, and every
            # resume repeated it, because this pass consulted no records at
            # all.
            if workflow_scope_id is not None and self._scope_step_succeeded(
                workflow_scope_id, node
            ):
                return True

            # `run()` resolves the name itself, `get_job` included, so a warm
            # boot's deferred-import stand-in is materialized on the way
            # through. Reading the registry entry directly here worked cold and
            # failed warm with "dependencies failed"; naming the node and
            # letting the one entry resolve it is what makes that unrepeatable.
            result = self._engine.run(
                nested_request(
                    getattr(context, "request", None),
                    job_name=node,
                    surface="engine.dependency",
                    invoke_depth=invoke_depth + 1,
                    # The dependent's run is this upstream's parent, read off
                    # the context rather than a ContextVar — see
                    # `RunRequest.parent_run_id` for why that distinction
                    # matters for a thread pool.
                    parent_run_id=getattr(context, "run_id", None),
                    # The plan already contains this node's own dependencies,
                    # in order. Letting it schedule them again would run a
                    # shared upstream once per path into it — a diamond ran
                    # its base three times before this.
                    run_dependencies=False,
                    # A `FromJob` dependent needs this job's *value*, and the
                    # recorded one cannot be reused, so freshness must not
                    # stand in for it (resolved Q19, T32b).
                    force_fresh=node in unreusable_upstreams,
                )
            )
            # Keep the value of any upstream that just ran for this job's
            # `FromJob` parameters. Injection otherwise reads the fingerprint
            # record, which only exists when the upstream declared
            # `cache=Fingerprint(...)` — so a plain `@job` upstream ran, and
            # the consumer silently received its parameter default. That made
            # `FromJob` quietly depend on an unrelated declaration.
            #
            # A forced run is the same case sharpened: it ran precisely
            # because its value could not be read back, so the copy in hand is
            # the only one.
            if node in from_job_upstreams and result.status is RunStatus.SUCCESS:
                live_values[node] = result.return_value

            # A dep that was skipped as fresh has satisfied the edge; only a
            # real failure blocks the dependent.
            return result.status in (RunStatus.SUCCESS, RunStatus.SKIPPED)

        report = DepScheduler(graph, policy=getattr(deps, "policy", "fail-fast")).run(
            run_node
        )

        if live_values:
            context.metadata["_from_job_live"] = live_values
        context.metadata["dependencies"] = {
            "ran": report.succeeded,
            "failed": report.failed,
            "skipped": report.skipped,
        }
        if report.ok:
            return None

        duration_ms = context.elapsed_ms
        return JobResult(
            status=RunStatus.FAILURE,
            return_value=None,
            duration_ms=duration_ms,
            metadata=dict(context.metadata),
            exception=RuntimeError(
                f"dependencies failed for {job_name!r}: {', '.join(report.failed)}"
            ),
            job_name=job_name,
        )
