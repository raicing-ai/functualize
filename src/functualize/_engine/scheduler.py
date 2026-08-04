"""Dependency execution: ordering, failure policy, and `--from` (§D.1).

Scheduling decisions this module encodes, straight from the proposal:

- **Sequential by default.** Independent deps run one at a time; ``--parallel``
  (or ``[runner] parallel``) opts in. Taskfile parallelizes by default and it is
  a recurring footgun — hidden ordering assumptions between "independent" deps
  surface as flaky interleavings. Determinism first; opt into speed.
- **Deterministic order.** Ties in the topological sort break alphabetically
  (``_primitives.graph``), so the same graph always yields the same plan.
- **Failure policy.** ``fail-fast`` marks everything downstream of a failure
  ``SKIPPED(reason="dep failed: <node>")`` — it does not attempt them, and it
  does not touch independent branches already scheduled. ``keep-going`` runs
  everything not downstream of a failure.
- **``--from``** resumes a plan partway, skipping already-completed deps.

The scheduler is deliberately runner-agnostic: it takes a callable that
executes one node and reports an outcome, so it is testable without the engine
and reusable by the S4 workflow walker (which needs the same graph model in
frontier mode — §D.7a).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from functualize._primitives.graph import descendants, topological_order

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "DepScheduler",
    "NodeOutcome",
    "NodeResult",
    "SchedulePlan",
    "ScheduleReport",
]

# Bound shared with Invoke.parallel's thread pool (§D.1).
MAX_PARALLEL = 32


class NodeOutcome(Enum):
    """What happened to one node in a scheduled run."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class NodeResult:
    """The outcome of one node, with the reason a skip happened."""

    name: str
    outcome: NodeOutcome
    reason: str = ""

    @property
    def ok(self) -> bool:
        """True when the node did not fail (success or skip)."""
        return self.outcome is not NodeOutcome.FAILED


@dataclass(frozen=True)
class SchedulePlan:
    """The ordered plan, as `--dry-run`/`--explain` would print it (§D.1)."""

    order: tuple[str, ...]
    skipped_before_start: tuple[str, ...] = field(default=())


@dataclass
class ScheduleReport:
    """Results of a scheduled run, in completion order."""

    results: list[NodeResult] = field(default_factory=list)

    @property
    def failed(self) -> list[str]:
        return [r.name for r in self.results if r.outcome is NodeOutcome.FAILED]

    @property
    def succeeded(self) -> list[str]:
        return [r.name for r in self.results if r.outcome is NodeOutcome.SUCCESS]

    @property
    def skipped(self) -> list[str]:
        return [r.name for r in self.results if r.outcome is NodeOutcome.SKIPPED]

    @property
    def ok(self) -> bool:
        return not self.failed

    def result_for(self, name: str) -> NodeResult | None:
        for result in self.results:
            if result.name == name:
                return result
        return None


class DepScheduler:
    """Schedules a job's dependency graph (§D.1).

    Args:
        dependencies: ``{node: [nodes it depends on]}``; every dependency must
            also be a key. Cycles raise from :func:`topological_order` — they
            are rejected at registration, not discovered mid-run.
        policy: ``"fail-fast"`` (default) or ``"keep-going"``.
        parallel: Run independent nodes concurrently (opt-in, §D.1).
        max_workers: Concurrency bound; capped at :data:`MAX_PARALLEL`.
    """

    def __init__(
        self,
        dependencies: Mapping[str, Sequence[str]],
        *,
        policy: str = "fail-fast",
        parallel: bool = False,
        max_workers: int = MAX_PARALLEL,
    ) -> None:
        self._dependencies = {
            node: list(deps or ()) for node, deps in dependencies.items()
        }
        self._policy = policy
        self._parallel = parallel
        self._max_workers = max(1, min(max_workers, MAX_PARALLEL))

    def plan(self, start_from: str | None = None) -> SchedulePlan:
        """Build the ordered plan, optionally resuming at ``start_from``.

        ``--from test`` drops everything test does not (transitively) depend on
        *and* that precedes it in the order — the already-completed prefix.
        """
        order = topological_order(self._dependencies)
        if start_from is None:
            return SchedulePlan(tuple(order))
        if start_from not in self._dependencies:
            raise KeyError(f"--from target {start_from!r} is not in the graph")
        index = order.index(start_from)
        return SchedulePlan(tuple(order[index:]), tuple(order[:index]))

    def run(
        self,
        runner: Callable[[str], Any],
        *,
        start_from: str | None = None,
    ) -> ScheduleReport:
        """Execute the plan, honoring the failure policy.

        ``runner`` receives a node name and returns either a
        :class:`NodeResult`, a :class:`NodeOutcome`, or a truthy/falsy value
        (True → success, False → failed).
        """
        plan = self.plan(start_from)
        report = ScheduleReport()
        blocked: dict[str, str] = {}

        if self._parallel:
            self._run_parallel(plan, runner, report, blocked)
        else:
            self._run_sequential(plan, runner, report, blocked)
        return report

    # ------------------------------------------------------------------
    # Execution modes
    # ------------------------------------------------------------------

    def _run_sequential(
        self,
        plan: SchedulePlan,
        runner: Callable[[str], Any],
        report: ScheduleReport,
        blocked: dict[str, str],
    ) -> None:
        for node in plan.order:
            if node in blocked:
                report.results.append(
                    NodeResult(node, NodeOutcome.SKIPPED, blocked[node])
                )
                continue
            result = self._invoke(runner, node)
            report.results.append(result)
            if result.outcome is NodeOutcome.FAILED:
                self._block_downstream(node, blocked)

    def _run_parallel(
        self,
        plan: SchedulePlan,
        runner: Callable[[str], Any],
        report: ScheduleReport,
        blocked: dict[str, str],
    ) -> None:
        """Run each dependency *level* concurrently, levels in order.

        Concurrency never reorders the graph: a node still starts only after
        every dependency finished.
        """
        from concurrent.futures import ThreadPoolExecutor

        scheduled = set(plan.order)
        done: set[str] = set()
        remaining = list(plan.order)

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            while remaining:
                level = [
                    node
                    for node in remaining
                    if all(
                        dep in done or dep not in scheduled
                        for dep in self._dependencies.get(node, ())
                    )
                ]
                if not level:  # unreachable for an acyclic graph
                    break
                runnable = [node for node in level if node not in blocked]
                for node in level:
                    if node in blocked:
                        report.results.append(
                            NodeResult(node, NodeOutcome.SKIPPED, blocked[node])
                        )
                results = list(pool.map(lambda n: self._invoke(runner, n), runnable))
                for result in results:
                    report.results.append(result)
                    if result.outcome is NodeOutcome.FAILED:
                        self._block_downstream(result.name, blocked)
                done.update(level)
                remaining = [node for node in remaining if node not in done]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _block_downstream(self, failed: str, blocked: dict[str, str]) -> None:
        """Mark nodes downstream of a failure as skipped (§D.1).

        Both policies skip *dependents* of a failure — running a job whose
        dependency failed is never correct. The policies differ in what happens
        to independent branches: fail-fast stops the whole plan, keep-going
        continues with everything not downstream.
        """
        for node in descendants(self._dependencies, [failed]):
            blocked.setdefault(node, f"dep failed: {failed}")
        if self._policy == "fail-fast":
            # Independent branches did NOT have a failed dependency — the run
            # was aborted. Saying "dep failed" there would be a lie in the
            # CI log that sends someone hunting a dependency that is fine.
            for node in self._dependencies:
                blocked.setdefault(node, f"aborted: fail-fast after {failed}")

    def _invoke(self, runner: Callable[[str], Any], node: str) -> NodeResult:
        """Run one node and normalize whatever the runner returned."""
        try:
            raw = runner(node)
        except Exception as exc:
            return NodeResult(node, NodeOutcome.FAILED, f"{type(exc).__name__}: {exc}")
        return _normalize(node, raw)


def _normalize(node: str, raw: Any) -> NodeResult:
    """Accept a NodeResult, a NodeOutcome, or a plain truthy/falsy value."""
    if isinstance(raw, NodeResult):
        return raw
    if isinstance(raw, NodeOutcome):
        return NodeResult(node, raw)
    return NodeResult(
        node, NodeOutcome.SUCCESS if raw or raw is None else NodeOutcome.FAILED
    )
