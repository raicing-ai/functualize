"""Every declared `@job` capability, exercised through a real run.

This file exists because of what a sweep on 2026-07-21 found: `Deps`, `Guards`,
`Fingerprint` and the `func why` renderer had all shipped at the S3 stage gate
with full unit tests, and **none of them were connected to `execute()`**. The
components were correct in isolation and inert in production — 944 lines of
tested code reachable only from each other:

    fingerprint.evaluate <- guards.py <- explain.py <- (nothing)
    scheduler.py <- (nothing)

Unit tests could not catch that, because each one instantiated its subject
directly. The stage gate could not catch it either, because the suite was green.
The only thing that catches it is asking, of each declared capability, "does a
real invocation exercise it?" — which is what every test here does.

So the rule this file encodes: **a capability a user can declare must have a
test that declares it and observes the consequence through the front door.**
Not the component; the capability.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Annotated

import pytest

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.app.utils import StateStore
from functualize.job import (
    Deps,
    Exec,
    Fingerprint,
    FromJob,
    Guards,
    Precondition,
    Retry,
    RunContext,
    RunStatus,
    job,
)


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


def _app(**jobs: object) -> FunctualizeApp:
    app = FunctualizeApp(name="caps")
    for name, fn in jobs.items():
        app.register_dynamic_job(name, fn)
    return app


class TestDeps:
    """`@job(deps=...)` — the upstream must actually run."""

    def test_a_declared_dependency_runs_first(self) -> None:
        order: list[str] = []

        @job
        def upstream() -> str:
            order.append("upstream")
            return "u"

        @job(deps=Deps("upstream"))
        def downstream() -> str:
            order.append("downstream")
            return "d"

        _app(upstream=upstream, downstream=downstream).execute("downstream")

        assert order == ["upstream", "downstream"], (
            "the declared dependency did not run — Deps is inert again"
        )

    def test_a_transitive_dependency_runs(self) -> None:
        order: list[str] = []

        @job
        def a() -> None:
            order.append("a")

        @job(deps=Deps("a"))
        def b() -> None:
            order.append("b")

        @job(deps=Deps("b"))
        def c() -> None:
            order.append("c")

        _app(a=a, b=b, c=c).execute("c")

        assert order == ["a", "b", "c"]

    def test_a_shared_dependency_runs_once(self) -> None:
        """A diamond must not run the shared upstream twice."""
        order: list[str] = []

        @job
        def base() -> None:
            order.append("base")

        @job(deps=Deps("base"))
        def left() -> None:
            order.append("left")

        @job(deps=Deps("base"))
        def right() -> None:
            order.append("right")

        @job(deps=Deps("left", "right"))
        def top() -> None:
            order.append("top")

        _app(base=base, left=left, right=right, top=top).execute("top")

        assert order.count("base") == 1
        assert order.index("base") < order.index("left")
        assert order[-1] == "top"

    def test_a_failing_dependency_stops_the_dependent(self) -> None:
        ran: list[str] = []

        @job
        def broken() -> None:
            raise RuntimeError("no network")

        @job(deps=Deps("broken"))
        def dependent() -> None:
            ran.append("dependent")

        result = _app(broken=broken, dependent=dependent).execute("dependent")

        assert result.status is RunStatus.FAILURE
        assert ran == [], "the dependent ran against a half-built world"


class TestGuards:
    """`@job(guards=...)` — a failing precondition must refuse the run."""

    def test_a_failing_precondition_refuses_the_job(self) -> None:
        ran: list[str] = []

        @job(guards=Guards(preconditions=[Precondition("exit 1", "always fails")]))
        def guarded() -> None:
            ran.append("guarded")

        result = _app(guarded=guarded).execute("guarded")

        # REFUSED, not FAILURE — which is what this test's own name has always
        # said, and what `Precondition`'s docstring has always promised
        # ("non-zero = refuse"). Nothing ran and nothing raised: the job
        # declined to start because a declared condition for running it was not
        # met. Reported as FAILURE it was indistinguishable from a job that ran
        # and threw, and it exited 1 rather than the pinned refusal code 3.
        assert result.status is RunStatus.REFUSED
        assert ran == []

    def test_a_failing_precondition_exits_three(self) -> None:
        """The refusal must survive to the process boundary (T39 exit table)."""
        from functualize._types.exit_codes import ExitCode, exit_code_for_status

        assert exit_code_for_status(RunStatus.REFUSED) == ExitCode.REFUSED == 3

    def test_a_passing_precondition_lets_the_job_run(self) -> None:
        ran: list[str] = []

        @job(guards=Guards(preconditions=["exit 0"]))
        def guarded() -> None:
            ran.append("guarded")

        result = _app(guarded=guarded).execute("guarded")

        assert result.status is RunStatus.SUCCESS
        assert ran == ["guarded"]

    def test_a_satisfied_status_guard_skips_the_job(self) -> None:
        ran: list[str] = []

        @job(guards=Guards(status=["exit 0"]))
        def already_done() -> None:
            ran.append("already_done")

        result = _app(already_done=already_done).execute("already_done")

        assert result.status is RunStatus.SKIPPED
        assert ran == []
        assert result.metadata["skip_reason"]


class TestFingerprint:
    """`@job(cache=Fingerprint(...))` — an unchanged source must skip."""

    def _job(self, ran: list[str]):
        @job(cache=Fingerprint(sources=["input.txt"]))
        def build() -> str:
            ran.append("build")
            return "built"

        return build

    def test_a_second_run_with_unchanged_sources_skips(self) -> None:
        Path("input.txt").write_text("v1")
        ran: list[str] = []
        app = _app(build=self._job(ran))

        first = app.execute("build")
        second = app.execute("build")

        assert first.status is RunStatus.SUCCESS
        assert second.status is RunStatus.SKIPPED
        assert ran == ["build"], "the job re-ran despite unchanged sources"

    def test_a_changed_source_re_runs(self) -> None:
        Path("input.txt").write_text("v1")
        ran: list[str] = []
        app = _app(build=self._job(ran))

        app.execute("build")
        Path("input.txt").write_text("v2")
        again = app.execute("build")

        assert again.status is RunStatus.SUCCESS
        assert ran == ["build", "build"]

    def test_a_failed_run_records_no_fingerprint(self) -> None:
        """Otherwise the retry the user is about to make would be skipped."""
        Path("input.txt").write_text("v1")
        attempts: list[str] = []

        @job(cache=Fingerprint(sources=["input.txt"]))
        def flaky() -> None:
            attempts.append("try")
            raise RuntimeError("boom")

        app = _app(flaky=flaky)
        app.execute("flaky")
        app.execute("flaky")

        assert len(attempts) == 2, "a failed run was recorded as fresh"

    def test_an_undeclared_job_is_never_skipped(self) -> None:
        """No `cache=` means no caching — the common case must stay eager."""
        ran: list[str] = []

        @job
        def plain() -> None:
            ran.append("plain")

        app = _app(plain=plain)
        app.execute("plain")
        app.execute("plain")

        assert ran == ["plain", "plain"]


class TestDepsAndFreshnessTogether:
    def test_dependencies_run_before_freshness_is_judged(self) -> None:
        """A dep may regenerate the very file the dependent fingerprints, so
        checking staleness first would compare against sources the dep is
        about to change. Make's ordering, for Make's reason."""
        ran: list[str] = []
        revision = iter(range(1, 99))
        Path("generated.txt").write_text("v0")

        @job
        def regenerate() -> None:
            ran.append("regenerate")
            # Distinct content each time. Deriving this from `ran` would not
            # work — the test clears that list between runs, so the second
            # write would reproduce the first and leave the consumer
            # legitimately fresh, proving nothing about ordering.
            Path("generated.txt").write_text(f"v{next(revision)}")

        @job(deps=Deps("regenerate"), cache=Fingerprint(sources=["generated.txt"]))
        def consumer() -> None:
            ran.append("consumer")

        app = _app(regenerate=regenerate, consumer=consumer)
        app.execute("consumer")
        ran.clear()
        app.execute("consumer")

        # The dep rewrote the source, so the consumer cannot be fresh.
        assert ran == ["regenerate", "consumer"]

    def test_a_fresh_dependency_still_satisfies_the_edge(self) -> None:
        """A dep skipped as up-to-date has done its job; the dependent must
        not be treated as having a failed dependency."""
        Path("dep_input.txt").write_text("v1")
        ran: list[str] = []

        @job(cache=Fingerprint(sources=["dep_input.txt"]))
        def upstream() -> None:
            ran.append("upstream")

        @job(deps=Deps("upstream"))
        def downstream() -> None:
            ran.append("downstream")

        app = _app(upstream=upstream, downstream=downstream)
        app.execute("upstream")
        ran.clear()

        result = app.execute("downstream")

        assert result.status is RunStatus.SUCCESS
        assert ran == ["downstream"]


class TestPlatformGuard:
    def test_a_foreign_platform_skips_neutrally(self) -> None:
        ran: list[str] = []

        @job(exec=Exec(platforms=["definitely-not-this-platform"]))
        def elsewhere() -> None:
            ran.append("elsewhere")

        result = _app(elsewhere=elsewhere).execute("elsewhere")

        assert result.status is RunStatus.SKIPPED
        assert ran == []


class TestRunStatusSkipped:
    def test_skipped_is_neither_success_nor_failure(self) -> None:
        """CI must be able to tell "already current" from "ran", and neither
        from "broke"."""
        assert RunStatus.SKIPPED is not RunStatus.SUCCESS
        assert not RunStatus.SKIPPED.ran
        assert RunStatus.SUCCESS.ran
        assert not RunStatus.SKIPPED.resumable


class TestExecHasNoTimeout:
    """There is no job-level timeout, and that is a decision (§A.5).

    A first implementation ran the body in a daemon thread and reported
    TIMEOUT on overrun — while the work carried on, because Python cannot
    preempt a running function. A caller believing the job stopped may release
    a lock or delete a file the live job is still using, which is worse than
    having no timeout. `invoke` has no task-level timeout either (only
    `run(cmd, timeout=)`, which SIGKILLs a subprocess) and `doit` has none at
    all. Bound work where the OS can enforce it: `sh(..., timeout=N)`.
    """

    def test_exec_rejects_a_timeout_argument(self) -> None:
        with pytest.raises(TypeError):
            Exec(timeout=1)  # type: ignore[call-arg]

    def test_a_long_job_simply_runs(self) -> None:
        """No silent partial enforcement — the job completes."""

        @job(exec=Exec(retry=Retry(attempts=1)))
        def slow() -> str:
            return "finished"

        result = _app(slow=slow).execute("slow")
        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "finished"


class TestExecRetry:
    """`@job(exec=Exec(retry=...))` — a declared retry must re-attempt."""

    def test_a_failing_job_is_retried(self) -> None:
        attempts: list[int] = []

        @job(exec=Exec(retry=Retry(attempts=3, backoff="constant")))
        def flaky() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("transient")
            return "eventually"

        result = _app(flaky=flaky).execute("flaky")

        assert result.status is RunStatus.SUCCESS
        assert len(attempts) == 3

    def test_retries_are_bounded_by_attempts(self) -> None:
        attempts: list[int] = []

        @job(exec=Exec(retry=Retry(attempts=2, backoff="constant")))
        def always_broken() -> None:
            attempts.append(1)
            raise RuntimeError("permanent")

        result = _app(always_broken=always_broken).execute("always_broken")

        assert result.status is RunStatus.FAILURE
        assert len(attempts) == 2

    def test_a_job_without_retry_runs_once(self) -> None:
        attempts: list[int] = []

        @job
        def plain_failure() -> None:
            attempts.append(1)
            raise RuntimeError("boom")

        _app(plain_failure=plain_failure).execute("plain_failure")

        assert len(attempts) == 1

    def test_on_narrows_which_failures_retry(self) -> None:
        """`on=(TypeError,)` must not retry a ValueError."""
        attempts: list[int] = []

        @job(exec=Exec(retry=Retry(attempts=3, backoff="constant", on=(TypeError,))))
        def wrong_error() -> None:
            attempts.append(1)
            raise ValueError("not the declared type")

        _app(wrong_error=wrong_error).execute("wrong_error")

        assert len(attempts) == 1


class TestExecRunMode:
    """`@job(exec=Exec(run=...))` — session-scoped dedup."""

    def test_run_once_collapses_repeat_invocations(self) -> None:
        ran: list[str] = []

        @job(exec=Exec(run="once"))
        def setup() -> None:
            ran.append("setup")

        app = _app(setup=setup)
        first = app.execute("setup")
        second = app.execute("setup")

        assert first.status is RunStatus.SUCCESS
        assert second.status is RunStatus.SKIPPED
        assert ran == ["setup"]

    def test_run_once_ignores_differing_arguments(self) -> None:
        """ "Once" is once — args do not make it a different invocation."""
        ran: list[str] = []

        @job(exec=Exec(run="once"))
        def setup(flavour: str = "a") -> None:
            ran.append(flavour)

        app = _app(setup=setup)
        app.execute("setup", flavour="a")
        app.execute("setup", flavour="b")

        assert ran == ["a"]

    def test_when_changed_reruns_for_different_arguments(self) -> None:
        ran: list[str] = []

        @job(exec=Exec(run="when_changed"))
        def build(target: str = "a") -> None:
            ran.append(target)

        app = _app(build=build)
        app.execute("build", target="a")
        app.execute("build", target="a")
        app.execute("build", target="b")

        assert ran == ["a", "b"]

    def test_run_always_is_the_default(self) -> None:
        ran: list[str] = []

        @job(exec=Exec(run="always"))
        def normal() -> None:
            ran.append("normal")

        app = _app(normal=normal)
        app.execute("normal")
        app.execute("normal")

        assert ran == ["normal", "normal"]


class TestFromJobEdges:
    """A `FromJob` parameter is a dependency edge (§D.5, S8/T30).

    Ordering only — *injecting* the upstream's value is T31. These assert the
    upstream runs first, which is the half that makes the annotation a
    dependency rather than a decoration.

    `FromJob` is imported at module level on purpose: this module uses
    `from __future__ import annotations`, so annotations are strings resolved
    against *module* globals. A `FromJob` imported inside a test function is
    invisible to `get_type_hints`, and the edge silently disappears — standard
    PEP 563 behavior, and a real trap for job authors too.
    """

    def test_a_from_job_parameter_orders_the_upstream_first(self) -> None:
        order: list[str] = []

        @job
        def build_wheel() -> str:
            order.append("build_wheel")
            return "dist/app.whl"

        @job
        def publish(wheel: Annotated[str, FromJob("build_wheel")] = "") -> None:
            order.append("publish")

        _app(build_wheel=build_wheel, publish=publish).execute("publish")

        assert order == ["build_wheel", "publish"]

    def test_deps_and_from_job_merge_without_double_running(self) -> None:
        """Both name the same upstream; it must run once, not twice."""
        order: list[str] = []

        @job
        def shared() -> str:
            order.append("shared")
            return "v"

        @job(deps=Deps("shared"))
        def consumer(value: Annotated[str, FromJob("shared")] = "") -> None:
            order.append("consumer")

        _app(shared=shared, consumer=consumer).execute("consumer")

        assert order == ["shared", "consumer"]


class TestWarmBootParity:
    """Dependencies must behave identically once a discovery cache exists.

    The regression this guards shipped and was not caught: dep names were read
    off the job *function*, which on a warm boot is a deferred-import stand-in
    carrying no declaration. A cold run executed the whole chain and a warm run
    silently executed only the target.

    The earlier capability tests could not catch it — they use
    `register_dynamic_job`, which is always materialized, so they never
    exercised the cached path. That is the same trap as a test supplying its
    own collaborators: it went through a side door.
    """

    JOBS = """
from functualize.job import job, Deps

@job
def a() -> str:
    open("trace.txt", "a").write("a\\n")
    return "a"

@job(deps=Deps("a"))
def b() -> str:
    open("trace.txt", "a").write("b\\n")
    return "b"

@job(deps=Deps("b"))
def c() -> str:
    open("trace.txt", "a").write("c\\n")
    return "c"
"""

    def _discovered_app(self) -> FunctualizeApp:
        from functualize.app.core import JobSources

        Path("jobs.py").write_text(self.JOBS)
        return FunctualizeApp(name="warm", job_sources=JobSources(directories=["."]))

    def test_a_transitive_chain_runs_the_same_cold_and_warm(self) -> None:
        # Cold: nothing cached yet.
        self._discovered_app().execute("c")
        cold = Path("trace.txt").read_text().split()
        Path("trace.txt").unlink()

        # Warm: the first app wrote a discovery cache, so the second boots
        # from it and the job functions are not imported up front.
        AppState.reset()
        self._discovered_app().execute("c")
        warm = Path("trace.txt").read_text().split()

        assert cold == ["a", "b", "c"]
        assert warm == cold, (
            "warm boot dropped transitive dependencies — dep names are being "
            "read from the function again instead of the registration"
        )


class TestFromJobInjection:
    """`FromJob` delivers the upstream's value, not just ordering (§D.5, T31)."""

    def test_the_upstream_value_is_injected(self) -> None:
        @job
        def build_wheel() -> str:
            return "dist/app.whl"

        @job(cache=Fingerprint(sources=["input.txt"]))
        def cached_build() -> str:
            return "cached-artifact"

        seen: list[str] = []

        @job
        def publish(wheel: Annotated[str, FromJob("cached_build")] = "") -> None:
            seen.append(wheel)

        Path("input.txt").write_text("v1")
        _app(
            build_wheel=build_wheel, cached_build=cached_build, publish=publish
        ).execute("publish")

        assert seen == ["cached-artifact"]

    def test_a_fresh_upstream_is_not_rerun_but_its_value_still_arrives(self) -> None:
        """Ensure-fresh: the point of the cache is skipping work, not losing
        the answer."""
        Path("input.txt").write_text("v1")
        ran: list[str] = []
        seen: list[str] = []

        @job(cache=Fingerprint(sources=["input.txt"]))
        def build() -> str:
            ran.append("build")
            return "artifact"

        @job
        def publish(art: Annotated[str, FromJob("build")] = "") -> None:
            seen.append(art)

        app = _app(build=build, publish=publish)
        app.execute("publish")
        app.execute("publish")

        assert ran == ["build"], "the fresh upstream was re-run"
        assert seen == ["artifact", "artifact"], "the cached value was lost"

    def test_an_explicitly_passed_argument_wins(self) -> None:
        """A caller naming the value is not overridden by a recorded one."""
        Path("input.txt").write_text("v1")
        seen: list[str] = []

        @job(cache=Fingerprint(sources=["input.txt"]))
        def build() -> str:
            return "recorded"

        @job
        def publish(art: Annotated[str, FromJob("build")] = "") -> None:
            seen.append(art)

        app = _app(build=build, publish=publish)
        app.execute("build")
        app.execute("publish", art="explicit")

        assert seen == ["explicit"]


class TestFromJobRunFalse:
    """`FromJob(x, run=False)` reads without causing work."""

    def test_it_does_not_trigger_the_upstream(self) -> None:
        ran: list[str] = []
        seen: list[str] = []

        @job
        def build() -> str:
            ran.append("build")
            return "artifact"

        @job
        def report(art: Annotated[str, FromJob("build", run=False)] = "none") -> None:
            seen.append(art)

        _app(build=build, report=report).execute("report")

        assert ran == [], "run=False triggered the upstream anyway"
        assert seen == ["none"], "no recorded value — the default should stand"

    def test_it_uses_a_recorded_value_when_one_exists(self) -> None:
        Path("input.txt").write_text("v1")
        ran: list[str] = []
        seen: list[str] = []

        @job(cache=Fingerprint(sources=["input.txt"]))
        def build() -> str:
            ran.append("build")
            return "artifact"

        @job
        def report(art: Annotated[str, FromJob("build", run=False)] = "none") -> None:
            seen.append(art)

        app = _app(build=build, report=report)
        app.execute("build")
        ran.clear()
        app.execute("report")

        assert ran == [], "reading a recorded value must not re-run anything"
        assert seen == ["artifact"]

    def test_it_contributes_no_dependency_edge(self) -> None:
        @job
        def build() -> str:
            return "artifact"

        @job
        def report(art: Annotated[str, FromJob("build", run=False)] = "none") -> None:
            pass

        app = _app(build=build, report=report)
        assert app.execution_engine._declared_dep_names("report") == []


class TestInvokeHonoursDeclarations:
    """`rc.invoke` is the same execution path as the CLI (CONSTITUTION)."""

    def test_invoke_runs_the_targets_dependencies(self) -> None:
        order: list[str] = []

        @job
        def upstream() -> None:
            order.append("upstream")

        @job(deps=Deps("upstream"))
        def target() -> None:
            order.append("target")

        @job
        def caller(rc: RunContext) -> None:
            rc.invoke("target")

        _app(upstream=upstream, target=target, caller=caller).execute("caller")

        assert order == ["upstream", "target"]

    def test_invoke_on_a_fresh_job_returns_its_recorded_value(self) -> None:
        """The defect this guards: once a fingerprint went warm, invoke
        returned SKIPPED with return_value=None and the caller silently got
        nothing where it used to get the artifact."""
        Path("input.txt").write_text("v1")
        got: list[object] = []

        @job(cache=Fingerprint(sources=["input.txt"]))
        def build() -> str:
            return "artifact"

        @job
        def caller(rc: RunContext) -> None:
            got.append(rc.invoke("build").return_value)

        app = _app(build=build, caller=caller)
        app.execute("build")
        app.execute("caller")

        assert got == ["artifact"], "a skipped-as-fresh job returned no value"


class TestWorkflowFromJobIsARead:
    """Inside a workflow, `FromJob` reads the walk; it does not order (T31).

    Outside a workflow the reference *is* the dependency edge and may run the
    upstream. Inside one that would be wrong twice over: the graph already
    declared the order, and the walk already recorded the value — running it
    again would execute the job outside the scope and defeat the memoization.

    So inside a workflow it is a read, and reaching for a node the graph never
    ordered is a bug in the graph, refused at boot rather than mid-walk when a
    scope is already open.
    """

    def _app_with(self, edges: list) -> FunctualizeApp:
        from functualize.workflow import END, Edge, Step, workflow

        app = FunctualizeApp(name="wf")

        @job
        def forecast() -> str:
            return "sunny"

        @job
        def travel_plan(sky: Annotated[str, FromJob("forecast")] = "") -> str:
            return f"packing for {sky}"

        @workflow(
            steps=[Step("forecast"), Step("travel_plan")],
            edges=[*edges, Edge(source="travel_plan", target=END)],
        )
        def trip() -> str:
            return "done"

        for name, fn in [
            ("forecast", forecast),
            ("travel_plan", travel_plan),
            ("trip", trip),
        ]:
            app.register_dynamic_job(name, fn)
        return app

    def test_a_step_reads_the_previous_steps_result(self) -> None:
        from functualize.workflow import Edge

        app = self._app_with([Edge(source="forecast", target="travel_plan")])
        result = app.execute("trip", scope_id="run-1")

        assert result.status is RunStatus.SUCCESS
        store = StateStore.for_project(Path.cwd())
        steps = store.get_scope("run-1")["steps"]
        assert steps["travel-plan::"]["return_value"] == "packing for sunny"

    def test_the_upstream_runs_once_not_twice(self) -> None:
        """If the annotation also created a dependency edge, the walk's step
        and the injected dependency would both run `forecast`."""
        from functualize.workflow import Edge

        app = self._app_with([Edge(source="forecast", target="travel_plan")])
        app.execute("trip", scope_id="run-1")

        store = StateStore.for_project(Path.cwd())
        scope = store.get_scope("run-1")
        assert sorted(scope["steps"]) == ["forecast::", "travel-plan::"]

    def test_consuming_a_node_the_graph_does_not_order_is_refused(self) -> None:
        """The graph, not the annotation, orders workflow steps.

        Driven through the boot validator directly: `register_dynamic_job`
        does not run boot validation, so a dynamically registered workflow is
        never checked. That is a real gap — dynamic registration skips every
        boot validator, not just this one — but it is a separate concern from
        whether the rule itself holds.
        """
        from functualize._app.boot import validate_workflow_declarations
        from functualize._types.errors import WorkflowDeclarationError
        from functualize.workflow import Edge

        # travel_plan consumes forecast, but nothing orders forecast first.
        app = self._app_with([Edge(source="travel_plan", target="forecast")])

        with pytest.raises(WorkflowDeclarationError, match="does not order"):
            validate_workflow_declarations(app)

    def test_a_correctly_ordered_graph_passes_validation(self) -> None:
        """The refusal must not fire on the legitimate case."""
        from functualize._app.boot import validate_workflow_declarations
        from functualize.workflow import Edge

        app = self._app_with([Edge(source="forecast", target="travel_plan")])
        validate_workflow_declarations(app)  # must not raise


class TestPartIMatrixDxW:
    """Part I cell D×W — a job that is both a dependency and a graph node.

    Specified as "runs once per scope (§D.7d dedupe)"; measured at twice
    during the S9 audit. The walker already replayed from step records, but
    the *dependency* pass consulted none, so a node ran once as a dependency
    and once as itself. A non-idempotent job corrupted its own output that
    way, and every resume repeated it.
    """

    def _graph(self, order_dep_first: bool) -> tuple[list[str], object]:
        from functualize.workflow import END, Edge, Step, workflow

        calls: list[str] = []

        @job
        def shared() -> str:
            calls.append("shared")
            return "s"

        @job(deps=Deps("shared"))
        def step_a() -> str:
            calls.append("step_a")
            return "a"

        edges = (
            [Edge(source="shared", target="step-a"), Edge(source="step-a", target=END)]
            if order_dep_first
            else [
                Edge(source="step-a", target="shared"),
                Edge(source="shared", target=END),
            ]
        )
        steps = (
            [Step(shared), Step(step_a)]
            if order_dep_first
            else [Step(step_a), Step(shared)]
        )

        @workflow(steps=steps, edges=edges)
        def wf() -> str:
            return "done"

        app = FunctualizeApp(name="dxw")
        for name, fn in [("shared", shared), ("step_a", step_a), ("wf", wf)]:
            app.register_dynamic_job(name, fn)
        return calls, app

    def test_a_node_that_is_also_a_dependency_runs_once_per_scope(self) -> None:
        calls, app = self._graph(order_dep_first=True)
        app.execute("wf", scope_id="dxw-1")

        assert calls.count("shared") == 1, f"ran {calls.count('shared')}×: {calls}"
        assert calls == ["shared", "step_a"]

    def test_it_still_runs_once_across_a_second_scope_entry(self) -> None:
        """Resume amplified the original bug: the dependency pass re-ran the
        node on every re-entry because it consulted no records."""
        calls, app = self._graph(order_dep_first=True)
        app.execute("wf", scope_id="dxw-2")
        app.execute("wf", scope_id="dxw-2")

        assert calls.count("shared") == 1, f"ran {calls.count('shared')}×: {calls}"

    def test_a_contradictory_declaration_is_rejected(self) -> None:
        """The dependency says "before" and the graph says "after".

        Mirrors the rule `FromJob` already has: the run used to resolve the
        contradiction by executing the node twice.
        """
        from functualize._engine.workflow_validation import (
            validate_workflow_declarations,
        )
        from functualize._types.errors import WorkflowDeclarationError

        _calls, app = self._graph(order_dep_first=False)
        with pytest.raises(WorkflowDeclarationError, match="does not order it before"):
            validate_workflow_declarations(app)

    def test_the_check_reaches_a_dynamically_registered_workflow(self) -> None:
        """The second door. `register_dynamic_job` never called the boot
        validator, so this contradiction reached a live walk unchecked — the
        guard existed and the path around it did too.

        Validation now runs where every walk must pass, so the door is closed
        by construction rather than by remembering to call it.
        """
        from functualize._types.errors import WorkflowDeclarationError

        _calls, app = self._graph(order_dep_first=False)
        with pytest.raises(WorkflowDeclarationError, match="does not order it before"):
            app.execute("wf", scope_id="second-door")

    def test_a_dependency_outside_the_graph_is_untouched(self) -> None:
        """Only nodes are governed. An ordinary dependency keeps following its
        own `Exec.run`, so a per-step dep (a token refresh) still repeats."""
        from functualize._engine.workflow_validation import (
            validate_workflow_declarations,
        )
        from functualize.workflow import END, Edge, Step, workflow

        calls: list[str] = []

        @job
        def refresh_token() -> str:
            calls.append("refresh")
            return "t"

        @job(deps=Deps("refresh_token"))
        def step_a() -> str:
            return "a"

        @job(deps=Deps("refresh_token"))
        def step_b() -> str:
            return "b"

        @workflow(
            steps=[Step(step_a), Step(step_b)],
            edges=[
                Edge(source="step-a", target="step-b"),
                Edge(source="step-b", target=END),
            ],
        )
        def wf() -> str:
            return "done"

        app = FunctualizeApp(name="dxw-outside")
        for name, fn in [
            ("refresh_token", refresh_token),
            ("step_a", step_a),
            ("step_b", step_b),
            ("wf", wf),
        ]:
            app.register_dynamic_job(name, fn)

        validate_workflow_declarations(app)  # not a node — no contradiction
        app.execute("wf", scope_id="dxw-3")

        assert calls.count("refresh") == 2, (
            "a dependency outside the graph must not be scope-deduped"
        )


class TestForcedUpstreamForAnUnusableValue:
    """T32b (resolved Q19) — a value that cannot be reused forces a run.

    Freshness answers "are the outputs on disk current?". It says nothing
    about a return value that was never storable, so honouring it when a
    `FromJob` dependent asks for that value hands the dependent nothing.

    After T32a this is the rare tail — a job returning a live handle — because
    dataclasses, `BaseModel`, `Path` and friends all round-trip.
    """

    def _app(self, tmp_path: Path):
        import threading

        from functualize.job import Fingerprint, job

        (tmp_path / "a.csv").write_text("x")
        ran: list[str] = []

        @job(cache=Fingerprint(sources=["*.csv"]))
        def make_handle():  # type: ignore[no-untyped-def]
            ran.append("make_handle")
            return threading.Lock()

        @job
        def uses_handle(h: Annotated[object, FromJob("make-handle")] = None) -> str:
            return type(h).__name__

        @job
        def reads_only(
            h: Annotated[object, FromJob("make-handle", run=False)] = None,
        ) -> str:
            return type(h).__name__

        app = FunctualizeApp(name="t32b")
        for name, fn in [
            ("make_handle", make_handle),
            ("uses_handle", uses_handle),
            ("reads_only", reads_only),
        ]:
            app.register_dynamic_job(name, fn)
        return app, ran

    def test_caching_is_untouched_for_everyone_else(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The job still skips when nobody needs its value — the whole point
        of scoping the disqualification to *reuse* rather than caching."""
        monkeypatch.chdir(tmp_path)
        app, ran = self._app(tmp_path)

        app.execute("make-handle")
        assert app.execute("make-handle").status is RunStatus.SKIPPED
        assert ran == ["make_handle"], "ran once, then skipped as fresh"

    def test_a_dependent_forces_the_upstream_and_gets_a_live_value(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Without this the dependent silently received its default — a run
        that succeeded with the wrong data and exit code 0."""
        monkeypatch.chdir(tmp_path)
        app, ran = self._app(tmp_path)

        app.execute("make-handle")
        ran.clear()

        result = app.execute("uses-handle")
        assert ran == ["make_handle"], "the fresh upstream must be forced"
        assert result.return_value == "lock", "the live value must be injected"

    def test_run_false_never_forces(self, tmp_path: Path, monkeypatch) -> None:
        """`run=False` means "read what is recorded, cause no work". A missing
        value is the answer it asked for, not a reason to run anything."""
        monkeypatch.chdir(tmp_path)
        app, ran = self._app(tmp_path)

        app.execute("make-handle")
        ran.clear()

        result = app.execute("reads-only")
        assert ran == [], "run=False must not trigger the upstream"
        assert result.return_value == "NoneType"

    def test_a_satisfied_status_guard_is_not_overridden(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Only SKIP_FRESH is overridden. Wanting a value is not a reason to
        run somewhere the job does not belong.

        A `status` guard saying "already done" is the user's own external
        check, and it says nothing about return values; overriding it to
        obtain one would run a job its author told us not to.

        The setup is fiddly on purpose. The job needs *both* a recorded
        non-reusable value (so it is a force candidate at all) and a
        non-fresh skip, so the guard is sequenced with a marker file: absent
        on the first run so the job runs and records, present afterwards so
        the skip is SKIP_SATISFIED rather than SKIP_FRESH.

        Two earlier versions of this test passed under the sabotage that
        relaxes the SKIP_FRESH condition — the first because the job had no
        `Fingerprint` and so was never a force candidate. Worth recording:
        the boundary is easy to *look* covered.
        """
        import threading

        from functualize.job import Fingerprint, Guards, job

        monkeypatch.chdir(tmp_path)
        (tmp_path / "a.csv").write_text("x")
        ran: list[str] = []

        @job(
            cache=Fingerprint(sources=["*.csv"]),
            guards=Guards(status=["test -f done.marker"]),
        )
        def guarded():  # type: ignore[no-untyped-def]
            ran.append("guarded")
            return threading.Lock()

        @job
        def wants_it(h: Annotated[object, FromJob("guarded")] = None) -> str:
            return type(h).__name__

        app = FunctualizeApp(name="guard-not-forced")
        app.register_dynamic_job("guarded", guarded)
        app.register_dynamic_job("wants_it", wants_it)

        # Marker absent: the guard does not satisfy, so the job runs and
        # records a value that cannot be reused.
        app.execute("guarded")
        assert ran == ["guarded"], "setup: the job must run once to record"

        # Marker present: the skip is now SKIP_SATISFIED, not SKIP_FRESH.
        (tmp_path / "done.marker").write_text("")
        ran.clear()

        app.execute("wants-it")

        assert ran == [], (
            "a satisfied status guard must still refuse, even when a "
            "dependent wants the value"
        )
