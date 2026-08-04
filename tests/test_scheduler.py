"""Tests for dependency execution (S3/T19, §D.1).

Covers deterministic ordering, sequential-by-default, opt-in parallelism, the
two failure policies, and `--from`.
"""

from __future__ import annotations

import pytest

from functualize._engine.scheduler import (
    MAX_PARALLEL,
    DepScheduler,
    NodeOutcome,
    NodeResult,
)
from functualize._primitives.graph import (
    GraphCycleError,
    MissingNodeError,
    descendants,
    topological_order,
)

# lint → test → build ; docs is an independent branch
GRAPH = {
    "lint": [],
    "test": ["lint"],
    "build": ["test"],
    "docs": [],
}


def _recording_runner(fail: set[str] | None = None):
    ran: list[str] = []
    failures = fail or set()

    def runner(node: str) -> bool:
        ran.append(node)
        return node not in failures

    return runner, ran


class TestGraphPrimitive:
    def test_dependencies_precede_dependents(self) -> None:
        order = topological_order(GRAPH)
        assert order.index("lint") < order.index("test") < order.index("build")

    def test_ties_break_alphabetically(self) -> None:
        # Determinism: same graph, same plan, every run.
        assert topological_order({"b": [], "a": [], "c": []}) == ["a", "b", "c"]

    def test_the_frontier_is_global_not_per_level(self) -> None:
        """A node freed mid-walk competes with everything still waiting.

        `a` and `z` start ready; finishing `a` frees `b`. The frontier is
        re-sorted as a whole, so `b` (freed later, sorts earlier) precedes
        `z` — the answer differs from emitting each readiness *level* as a
        sorted batch, which would give `[a, z, b]`.

        The flat-graph tie-break case above passes under both, which is why
        this one exists: a `graphlib` rewrite that batched by level was
        caught here and nowhere else.
        """
        assert topological_order({"a": [], "b": ["a"], "z": []}) == ["a", "b", "z"]

    def test_cycle_is_reported(self) -> None:
        with pytest.raises(GraphCycleError) as exc:
            topological_order({"a": ["b"], "b": ["a"]})
        assert set(exc.value.cycle) >= {"a", "b"}

    def test_unknown_dependency_is_reported(self) -> None:
        with pytest.raises(MissingNodeError) as exc:
            topological_order({"a": ["ghost"]})
        assert exc.value.dependency == "ghost"

    def test_descendants_finds_transitive_dependents(self) -> None:
        assert descendants(GRAPH, ["lint"]) == {"test", "build"}

    def test_descendants_of_leaf_is_empty(self) -> None:
        assert descendants(GRAPH, ["build"]) == set()


class TestPlan:
    def test_plan_is_topological(self) -> None:
        order = DepScheduler(GRAPH).plan().order
        assert order.index("test") < order.index("build")

    def test_from_drops_the_completed_prefix(self) -> None:
        plan = DepScheduler(GRAPH).plan(start_from="test")
        assert "lint" not in plan.order
        assert "lint" in plan.skipped_before_start
        assert plan.order[0] == "test"

    def test_from_unknown_node_errors(self) -> None:
        with pytest.raises(KeyError, match="not in the graph"):
            DepScheduler(GRAPH).plan(start_from="ghost")


class TestSequentialExecution:
    def test_runs_everything_in_order(self) -> None:
        runner, ran = _recording_runner()
        report = DepScheduler(GRAPH).run(runner)
        assert report.ok
        assert ran.index("lint") < ran.index("test") < ran.index("build")

    def test_sequential_is_the_default(self) -> None:
        # §D.1: determinism first — parallelism must be opt-in.
        assert DepScheduler(GRAPH)._parallel is False

    def test_from_skips_prefix(self) -> None:
        runner, ran = _recording_runner()
        DepScheduler(GRAPH).run(runner, start_from="test")
        assert "lint" not in ran

    def test_runner_exception_is_a_failure_not_a_crash(self) -> None:
        def runner(node: str) -> bool:
            if node == "lint":
                raise RuntimeError("boom")
            return True

        report = DepScheduler(GRAPH, policy="keep-going").run(runner)
        assert report.failed == ["lint"]
        assert "RuntimeError: boom" in report.result_for("lint").reason


class TestFailurePolicies:
    def test_fail_fast_skips_dependents_with_dep_reason(self) -> None:
        runner, ran = _recording_runner(fail={"lint"})
        report = DepScheduler(GRAPH, policy="fail-fast").run(runner)
        assert "test" not in ran and "build" not in ran
        assert report.result_for("test").reason == "dep failed: lint"

    def test_fail_fast_does_not_mislabel_independent_branches(self) -> None:
        # "zeta" sorts after "alpha", so it is still un-run when alpha fails.
        # It never depended on alpha — calling it "dep failed" would send
        # someone hunting a dependency that is fine.
        graph = {"alpha": [], "beta": ["alpha"], "zeta": []}
        runner, ran = _recording_runner(fail={"alpha"})
        report = DepScheduler(graph, policy="fail-fast").run(runner)
        assert "zeta" not in ran  # aborted before it could run
        assert "aborted: fail-fast" in report.result_for("zeta").reason
        assert report.result_for("beta").reason == "dep failed: alpha"

    def test_keep_going_runs_independent_branches(self) -> None:
        # Same graph: keep-going must still run the independent branch.
        graph = {"alpha": [], "beta": ["alpha"], "zeta": []}
        runner, ran = _recording_runner(fail={"alpha"})
        report = DepScheduler(graph, policy="keep-going").run(runner)
        assert "zeta" in ran  # independent branch still ran
        assert "beta" not in ran  # but dependents of the failure did not
        assert report.result_for("beta").reason == "dep failed: alpha"

    def test_keep_going_reports_the_failure(self) -> None:
        runner, _ = _recording_runner(fail={"lint"})
        report = DepScheduler(GRAPH, policy="keep-going").run(runner)
        assert report.ok is False
        assert report.failed == ["lint"]

    def test_success_reports_all_succeeded(self) -> None:
        runner, _ = _recording_runner()
        report = DepScheduler(GRAPH).run(runner)
        assert set(report.succeeded) == set(GRAPH)
        assert report.skipped == []


class TestParallelExecution:
    def test_parallel_still_honors_dependency_order(self) -> None:
        import threading

        lock = threading.Lock()
        finished: list[str] = []

        def runner(node: str) -> bool:
            with lock:
                finished.append(node)
            return True

        report = DepScheduler(GRAPH, parallel=True).run(runner)
        assert report.ok
        assert finished.index("lint") < finished.index("test")
        assert finished.index("test") < finished.index("build")

    def test_parallel_runs_independent_nodes(self) -> None:
        runner, ran = _recording_runner()
        report = DepScheduler(GRAPH, parallel=True).run(runner)
        assert report.ok
        assert set(ran) == set(GRAPH)

    def test_parallel_failure_skips_dependents(self) -> None:
        runner, ran = _recording_runner(fail={"lint"})
        report = DepScheduler(GRAPH, parallel=True, policy="keep-going").run(runner)
        assert "test" not in ran
        assert report.result_for("test").outcome is NodeOutcome.SKIPPED

    def test_worker_bound_is_capped(self) -> None:
        scheduler = DepScheduler(GRAPH, parallel=True, max_workers=9999)
        assert scheduler._max_workers == MAX_PARALLEL

    def test_worker_bound_is_at_least_one(self) -> None:
        assert DepScheduler(GRAPH, parallel=True, max_workers=0)._max_workers == 1


class TestRunnerReturnShapes:
    def test_accepts_node_result(self) -> None:
        report = DepScheduler({"a": []}).run(
            lambda n: NodeResult(n, NodeOutcome.SKIPPED, "already fresh")
        )
        assert report.skipped == ["a"]

    def test_accepts_node_outcome(self) -> None:
        report = DepScheduler({"a": []}).run(lambda _n: NodeOutcome.FAILED)
        assert report.failed == ["a"]

    def test_accepts_bare_bool(self) -> None:
        assert DepScheduler({"a": []}).run(lambda _n: True).ok

    def test_none_counts_as_success(self) -> None:
        # A runner that just does the work and returns nothing succeeded.
        assert DepScheduler({"a": []}).run(lambda _n: None).ok
