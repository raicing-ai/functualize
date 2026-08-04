"""End-to-end: a `@workflow` job executed through the real engine (§A.7).

The unit tests cover the walker and the runner in isolation. These cover the
claim that actually matters — that a workflow is an *ordinary job*: it runs its
steps through the engine, returns its body's value, blocks resumably at a gate,
and can itself be a step of another workflow with no composition feature.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._primitives.state_store import StateStore
from functualize._types.enums import RunStatus
from functualize._types.from_job import FromJob
from functualize._types.workflow import END, Edge, Gate, Step
from functualize.app.core import FunctualizeApp
from functualize.workflow._decorator import workflow


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch) -> Generator[None]:
    """Give each test its own state file by running in a fresh cwd.

    The engine resolves the state store the way `func state` does — upward
    from the working directory — so isolating cwd isolates the store.
    """
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    yield


class TripPreferences(BaseModel):
    budget: str = "mid"


def _state_store() -> StateStore:
    from pathlib import Path

    return StateStore.for_project(Path.cwd())


class TestWorkflowAsOrdinaryJob:
    def test_steps_run_through_the_engine_and_the_body_returns(self) -> None:
        app = FunctualizeApp(name="testapp")
        calls: list[str] = []

        def forecast() -> str:
            calls.append("forecast")
            return "sunny"

        def travel_plan() -> str:
            calls.append("travel_plan")
            return "packed"

        @workflow(
            steps=[Step("forecast"), Step("travel_plan")],
            edges=[
                Edge(source="forecast", target="travel_plan"),
                Edge(source="travel_plan", target=END),
            ],
        )
        def trip_planner() -> str:
            calls.append("body")
            return "itinerary"

        app.register_dynamic_job("forecast", forecast)
        app.register_dynamic_job("travel_plan", travel_plan)
        app.register_dynamic_job("trip_planner", trip_planner)

        result = app.execute("trip_planner")

        assert result.status is RunStatus.SUCCESS
        # The body runs last, after the walk reaches END, and its value is
        # the workflow job's value.
        assert calls == ["forecast", "travel_plan", "body"]
        assert result.return_value == "itinerary"

    def test_an_empty_body_is_legal_and_returns_none(self) -> None:
        app = FunctualizeApp(name="testapp")

        def step_a() -> str:
            return "a"

        @workflow(steps=[Step("step_a")], edges=[Edge(source="step_a", target=END)])
        def flow() -> None:
            """Topology only — no epilogue."""

        app.register_dynamic_job("step_a", step_a)
        app.register_dynamic_job("flow", flow)

        result = app.execute("flow")
        assert result.status is RunStatus.SUCCESS
        assert result.return_value is None


class TestGateBlocking:
    def _app(self, calls: list[str]) -> FunctualizeApp:
        app = FunctualizeApp(name="testapp")

        def forecast() -> str:
            calls.append("forecast")
            return "sunny"

        def travel_plan() -> str:
            calls.append("travel_plan")
            return "packed"

        @workflow(
            steps=[
                Step("forecast"),
                Gate(name="preferences", awaits=TripPreferences),
                Step("travel_plan"),
            ],
            edges=[
                Edge(source="forecast", target="preferences"),
                Edge(source="preferences", target="travel_plan"),
                Edge(source="travel_plan", target=END),
            ],
        )
        def trip_planner() -> str:
            calls.append("body")
            return "itinerary"

        app.register_dynamic_job("forecast", forecast)
        app.register_dynamic_job("travel_plan", travel_plan)
        app.register_dynamic_job("trip_planner", trip_planner)
        return app

    def test_a_gate_blocks_the_job_without_running_the_body(self) -> None:
        calls: list[str] = []
        result = self._app(calls).execute("trip_planner")

        assert result.status is RunStatus.BLOCKED
        assert result.status.resumable
        assert result.metadata["blocked_on"] == "preferences"
        assert calls == ["forecast"]

    def test_the_block_is_addressable_by_scope_id(self) -> None:
        """The scope id in the result is the handle a resumer needs."""
        result = self._app([]).execute("trip_planner", scope_id="run-1")

        assert result.metadata["workflow_scope"] == "run-1"
        gate = _state_store().get_gate("run-1", "preferences")
        assert gate is not None
        assert gate["model"] == "TripPreferences"

    def test_full_block_deposit_resume_cycle(self) -> None:
        calls: list[str] = []
        app = self._app(calls)

        blocked = app.execute("trip_planner", scope_id="run-1")
        assert blocked.status is RunStatus.BLOCKED

        _state_store().deposit_gate_payload("run-1", "preferences", {"budget": "high"})

        resumed = app.execute("trip_planner", scope_id="run-1")

        assert resumed.status is RunStatus.SUCCESS
        assert resumed.return_value == "itinerary"
        # forecast is memoized; only the post-gate step and the body run.
        assert calls == ["forecast", "travel_plan", "body"]

    def test_resuming_a_completed_scope_does_not_rerun_the_body(self) -> None:
        calls: list[str] = []
        app = self._app(calls)

        app.execute("trip_planner", scope_id="run-1")
        _state_store().deposit_gate_payload("run-1", "preferences", {"budget": "hi"})
        app.execute("trip_planner", scope_id="run-1")

        again = app.execute("trip_planner", scope_id="run-1")

        assert again.status is RunStatus.SUCCESS
        assert again.return_value == "itinerary"
        assert calls.count("body") == 1

    def test_a_fresh_invocation_starts_a_new_scope(self) -> None:
        """No scope_id means a new run, not a resume of the last one."""
        calls: list[str] = []
        app = self._app(calls)

        first = app.execute("trip_planner")
        second = app.execute("trip_planner")

        assert first.metadata["workflow_scope"] != second.metadata["workflow_scope"]
        assert calls == ["forecast", "forecast"]


class TestFailure:
    def test_a_failing_step_fails_the_workflow_job(self) -> None:
        app = FunctualizeApp(name="testapp")
        ran: list[str] = []

        def broken() -> None:
            raise RuntimeError("no network")

        def after() -> None:
            ran.append("after")

        @workflow(
            steps=[Step("broken"), Step("after")],
            edges=[
                Edge(source="broken", target="after"),
                Edge(source="after", target=END),
            ],
        )
        def flow() -> str:
            ran.append("body")
            return "done"

        app.register_dynamic_job("broken", broken)
        app.register_dynamic_job("after", after)
        app.register_dynamic_job("flow", flow)

        result = app.execute("flow")

        assert result.status is RunStatus.FAILURE
        assert not result.status.resumable
        assert ran == []


class TestNesting:
    def test_a_workflow_is_a_valid_step_of_another_workflow(self) -> None:
        """Nesting with no composition feature — Step(wf) is just Step(job)."""
        app = FunctualizeApp(name="testapp")
        order: list[str] = []

        def leaf() -> str:
            order.append("leaf")
            return "leaf-value"

        @workflow(steps=[Step("leaf")], edges=[Edge(source="leaf", target=END)])
        def inner() -> str:
            order.append("inner-body")
            return "inner-value"

        @workflow(steps=[Step("inner")], edges=[Edge(source="inner", target=END)])
        def outer() -> str:
            order.append("outer-body")
            return "outer-value"

        app.register_dynamic_job("leaf", leaf)
        app.register_dynamic_job("inner", inner)
        app.register_dynamic_job("outer", outer)

        result = app.execute("outer")

        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "outer-value"
        assert order == ["leaf", "inner-body", "outer-body"]

    def test_the_nested_workflow_runs_in_its_own_scope(self) -> None:
        """A child scope, so the inner walk's records never collide with the
        outer walk's — both have a step named by the same key otherwise."""
        app = FunctualizeApp(name="testapp")

        def leaf() -> str:
            return "v"

        @workflow(steps=[Step("leaf")], edges=[Edge(source="leaf", target=END)])
        def inner() -> str:
            return "inner-value"

        @workflow(steps=[Step("inner")], edges=[Edge(source="inner", target=END)])
        def outer() -> str:
            return "outer-value"

        app.register_dynamic_job("leaf", leaf)
        app.register_dynamic_job("inner", inner)
        app.register_dynamic_job("outer", outer)

        app.execute("outer", scope_id="outer-1")

        store = _state_store()
        scopes = store.scope_ids()
        assert "outer-1" in scopes
        # The inner workflow got a scope of its own.
        assert len(scopes) == 2

        outer_scope = store.get_scope("outer-1")
        assert outer_scope is not None
        assert set(outer_scope["steps"]) == {"inner::"}


class TestChaining:
    def test_a_workflows_result_is_an_ordinary_job_result(self) -> None:
        """Everything downstream sees a job, not a graph."""
        app = FunctualizeApp(name="testapp")

        def leaf() -> int:
            return 21

        @workflow(steps=[Step("leaf")], edges=[Edge(source="leaf", target=END)])
        def doubler() -> int:
            return 42

        app.register_dynamic_job("leaf", leaf)
        app.register_dynamic_job("doubler", doubler)

        result = app.execute("doubler")
        assert result.status is RunStatus.SUCCESS
        assert result.return_value == 42
        assert result.job_name == "doubler"

    def test_the_walk_records_survive_for_observers(self) -> None:
        """MCP reads these; they must be there after a normal run."""
        app = FunctualizeApp(name="testapp")

        def leaf() -> str:
            return "v"

        @workflow(steps=[Step("leaf")], edges=[Edge(source="leaf", target=END)])
        def flow() -> None: ...

        app.register_dynamic_job("leaf", leaf)
        app.register_dynamic_job("flow", flow)
        app.execute("flow", scope_id="run-1")

        scope = _state_store().get_scope("run-1")
        assert scope is not None
        assert scope["workflow"] == "flow"
        assert scope["status"] == "completed"
        assert scope["steps"]["leaf::"]["status"] == "success"
        assert scope["epilogue"]["status"] == "success"


class TestNonWorkflowJobsAreUntouched:
    def test_an_ordinary_job_writes_no_scope_records(self) -> None:
        """The prelude must be inert for every job that is not a workflow."""
        app = FunctualizeApp(name="testapp")

        def plain() -> str:
            return "ok"

        app.register_dynamic_job("plain", plain)
        result = app.execute("plain")

        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "ok"
        assert "workflow_scope" not in result.metadata
        assert _state_store().scope_ids() == []


class TestPartIMatrixGxWxW:
    """Part I cell G×W×W — a gate inside a *nested* workflow.

    Specified as "agent resumes the child scope-id; parent walk stays
    correctly blocked". Measured during the S9 audit as: child blocked
    correctly, **parent failed**. Two separate causes, both fixed here.
    """

    def _nested(self) -> FunctualizeApp:
        from pydantic import BaseModel

        from functualize.job import job

        class Sub(BaseModel):
            ok: bool

        @job
        def setup_vfs() -> list[str]:
            return ["src/a.py"]

        @workflow(
            steps=[Step(setup_vfs), Gate(name="edit", awaits=Sub)],
            edges=[
                Edge(source="setup-vfs", target="edit"),
                Edge(source="edit", target=END),
            ],
        )
        def child() -> str:
            return "child done"

        @workflow(steps=[Step(child)], edges=[Edge(source="child", target=END)])
        def parent() -> str:
            return "parent done"

        app = FunctualizeApp(name="gxwxw")
        for name, fn in [
            ("setup_vfs", setup_vfs),
            ("child", child),
            ("parent", parent),
        ]:
            app.register_dynamic_job(name, fn)
        return app

    def test_a_nested_gate_blocks_the_parent_rather_than_failing_it(self) -> None:
        """`BLOCKED` reached the parent as a plain exception, so the parent
        recorded the step failed and marked its own scope failed — after which
        resuming the child could never complete the parent."""
        app = self._nested()
        result = app.execute("parent", scope_id="G1")

        assert result.status is RunStatus.BLOCKED

        scope = StateStore.for_project(Path.cwd()).get_scope("G1") or {}
        assert scope.get("status") == "blocked"
        assert not (scope.get("steps") or {}), (
            "a blocked step must not be recorded as finished"
        )

    def test_the_child_scope_is_stable_across_re_entry(self) -> None:
        """Derived from the parent scope and step name, not freshly generated.

        A fresh scope per run meant an agent's deposited input belonged to a
        scope nothing would ever re-enter, so the gate was unresumable even
        once the block propagated correctly.
        """
        app = self._nested()
        app.execute("parent", scope_id="G2")
        app.execute("parent", scope_id="G2")

        store = StateStore.for_project(Path.cwd())
        children = [
            s
            for s in store.scope_ids()
            if (store.get_scope(s) or {}).get("workflow") == "child"
            and s.startswith("G2")
        ]
        assert children == ["G2::child"], f"expected one stable scope, got {children}"

    def test_resuming_the_child_completes_the_parent(self) -> None:
        """The whole point: the agent addresses the child, the parent finishes."""
        app = self._nested()
        assert app.execute("parent", scope_id="G3").status is RunStatus.BLOCKED

        store = StateStore.for_project(Path.cwd())
        assert store.deposit_gate_payload("G3::child", "edit", {"ok": True})

        resumed = app.execute("parent", scope_id="G3")
        assert resumed.status is RunStatus.SUCCESS
        assert resumed.return_value == "parent done"

    def test_a_nested_workflow_still_owns_its_own_scope(self) -> None:
        """Stability must not become sharing: two walks in one scope would
        merge their step records and epilogue slots, surfacing the inner
        body's return value as the outer's."""
        app = self._nested()
        app.execute("parent", scope_id="G4")

        store = StateStore.for_project(Path.cwd())
        parent_scope = store.get_scope("G4") or {}
        child_scope = store.get_scope("G4::child") or {}

        assert child_scope.get("workflow") == "child"
        assert parent_scope.get("workflow") == "parent"
        assert "setup-vfs::" in (child_scope.get("steps") or {})
        assert "setup-vfs::" not in (parent_scope.get("steps") or {})


class TestPartIMatrixGxD:
    """Part I cells G×D — deps meeting a paused scope (resolved question 9).

    Q9 splits the behavior by edge type: stale `Deps` re-run, while `Step`
    completions, branch choices, and gate inputs stay **stable**. These cross
    the same resume boundary the two S9 audit defects lived on, so they are
    pinned explicitly rather than assumed.

    All three passed on first measurement — recorded because "we checked" is
    worth as much as "we fixed", and a later change to the dependency pass or
    the replay path should have to break these deliberately.
    """

    def _paused(self, tmp_path: Path, dep_is_a_node: bool):
        from pydantic import BaseModel

        from functualize.job import Deps, Fingerprint, job
        from functualize.workflow import END, Edge, Gate, Step, workflow

        class Sub(BaseModel):
            ok: bool

        (tmp_path / "src.txt").write_text("v1")
        calls: list[str] = []

        @job(cache=Fingerprint(sources=["src.txt"]))
        def shared_dep() -> str:
            calls.append("dep")
            return "d"

        @job(deps=Deps("shared_dep"))
        def before_gate() -> str:
            calls.append("before")
            return "b"

        @job(deps=Deps("shared_dep"))
        def after_gate() -> str:
            calls.append("after")
            return "a"

        steps = [Step(before_gate), Gate(name="g", awaits=Sub), Step(after_gate)]
        edges = [
            Edge(source="before-gate", target="g"),
            Edge(source="g", target="after-gate"),
            Edge(source="after-gate", target=END),
        ]
        if dep_is_a_node:
            steps = [Step(shared_dep), Gate(name="g", awaits=Sub), Step(after_gate)]
            edges = [
                Edge(source="shared-dep", target="g"),
                Edge(source="g", target="after-gate"),
                Edge(source="after-gate", target=END),
            ]

        @workflow(steps=steps, edges=edges)
        def wf() -> str:
            return "done"

        app = FunctualizeApp(name="gxd")
        for name, fn in [
            ("shared_dep", shared_dep),
            ("before_gate", before_gate),
            ("after_gate", after_gate),
            ("wf", wf),
        ]:
            app.register_dynamic_job(name, fn)
        return app, calls

    def test_a_completed_step_replays_without_rerunning_its_deps(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """G×D cell 1. A replayed step never executes, so its deps cannot."""
        monkeypatch.chdir(tmp_path)
        app, calls = self._paused(tmp_path, dep_is_a_node=False)

        assert app.execute("wf", scope_id="X1").status is RunStatus.BLOCKED
        StateStore.for_project(Path.cwd()).deposit_gate_payload("X1", "g", {"ok": True})
        calls.clear()
        app.execute("wf", scope_id="X1")

        assert "before" not in calls, "a completed step must not run again"

    def test_a_stale_dep_reruns_for_a_step_that_has_not_run_yet(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """G×D cell 2. The dep went stale during the pause; the step after the
        gate has not run, so its dep is re-evaluated and re-runs."""
        import time

        monkeypatch.chdir(tmp_path)
        app, calls = self._paused(tmp_path, dep_is_a_node=False)

        assert app.execute("wf", scope_id="X2").status is RunStatus.BLOCKED
        time.sleep(0.02)
        (tmp_path / "src.txt").write_text("v2 CHANGED")
        StateStore.for_project(Path.cwd()).deposit_gate_payload("X2", "g", {"ok": True})
        calls.clear()

        result = app.execute("wf", scope_id="X2")
        assert result.status is RunStatus.SUCCESS
        assert calls.count("dep") == 1, f"stale dep should re-run once: {calls}"
        assert "after" in calls

    def test_a_node_that_is_also_a_dep_stays_stable_even_when_stale(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Where D×W and Q9 meet, and they agree.

        The scope-record skip added for D×W ignores staleness for a *node*.
        That is not a conflict with "stale Deps re-run": Q9 says a `Step`
        completion stays stable, and a node is a step. Pinned because the two
        rules look contradictory until you notice which one owns a node.
        """
        import time

        monkeypatch.chdir(tmp_path)
        app, calls = self._paused(tmp_path, dep_is_a_node=True)

        assert app.execute("wf", scope_id="X3").status is RunStatus.BLOCKED
        time.sleep(0.02)
        (tmp_path / "src.txt").write_text("v2 CHANGED")
        StateStore.for_project(Path.cwd()).deposit_gate_payload("X3", "g", {"ok": True})
        calls.clear()

        app.execute("wf", scope_id="X3")
        assert "dep" not in calls, (
            "a node completed in this scope stays completed, stale or not"
        )


class TestPartIMatrixWxI:
    """Part I cell W×I — a job body calls `invoke()` on a workflow job."""

    def test_invoking_a_workflow_runs_a_full_walk_in_a_child_scope(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from functualize.job import RunContext, job
        from functualize.workflow import END, Edge, Step, workflow

        monkeypatch.chdir(tmp_path)
        calls: list[str] = []

        @job
        def inner_step() -> str:
            calls.append("inner_step")
            return "i"

        @workflow(
            steps=[Step(inner_step)], edges=[Edge(source="inner-step", target=END)]
        )
        def child_wf() -> str:
            calls.append("child_epilogue")
            return "child done"

        @job
        def caller(rc: RunContext) -> str:
            calls.append("caller")
            return f"caller got: {rc.invoke('child-wf').return_value}"

        app = FunctualizeApp(name="wxi")
        for name, fn in [
            ("inner_step", inner_step),
            ("child_wf", child_wf),
            ("caller", caller),
        ]:
            app.register_dynamic_job(name, fn)

        result = app.execute("caller", scope_id="W1")

        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "caller got: child done"
        assert calls == ["caller", "inner_step", "child_epilogue"], (
            "the full walk runs, epilogue included"
        )

    def test_the_walk_gets_its_own_scope_not_the_callers(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """An ordinary caller has no scope of its own; the workflow makes one."""
        from functualize.job import RunContext, job
        from functualize.workflow import END, Edge, Step, workflow

        monkeypatch.chdir(tmp_path)

        @job
        def inner_step() -> str:
            return "i"

        @workflow(
            steps=[Step(inner_step)], edges=[Edge(source="inner-step", target=END)]
        )
        def child_wf() -> str:
            return "child done"

        @job
        def caller(rc: RunContext) -> str:
            return str(rc.invoke("child-wf").return_value)

        app = FunctualizeApp(name="wxi2")
        for name, fn in [
            ("inner_step", inner_step),
            ("child_wf", child_wf),
            ("caller", caller),
        ]:
            app.register_dynamic_job(name, fn)
        app.execute("caller", scope_id="W2")

        store = StateStore.for_project(Path.cwd())
        workflows = {
            (store.get_scope(s) or {}).get("workflow") for s in store.scope_ids()
        }
        assert "child-wf" in workflows
        assert "caller" not in workflows, "a plain job creates no walk scope"


class TestLiveStepValueFallback:
    """Resolved 19b — a step value that cannot be carried, inside a walk.

    Re-running is not the remedy here: the step already ran in this scope,
    and running it again would execute outside the walk's ordering and defeat
    the memoization the walk exists to provide. So the walk's in-process value
    is the fallback.

    The order is deliberately **record-first**. Live-first would leave the
    store path exercised only on resume, and a second path reached only in a
    rare case is exactly how the warm-boot divergences happened.
    """

    def _walk(self, tmp_path: Path):
        import threading

        from functualize.job import job
        from functualize.workflow import END, Edge, Step, workflow

        @job
        def open_handle():  # type: ignore[no-untyped-def]
            return threading.Lock()

        @job
        def uses(h: Annotated[object, FromJob("open-handle")] = None) -> str:
            return type(h).__name__

        @workflow(
            steps=[Step(open_handle), Step(uses)],
            edges=[
                Edge(source="open-handle", target="uses"),
                Edge(source="uses", target=END),
            ],
        )
        def wf(seen: Annotated[str, FromJob("uses")] = "MISSING") -> str:
            # The epilogue reports what the downstream step saw, so the
            # assertion reads a return value rather than the state file —
            # which keeps it independent of where the store happens to live.
            return seen

        app = FunctualizeApp(name="live-fallback")
        for name, fn in [("open_handle", open_handle), ("uses", uses), ("wf", wf)]:
            app.register_dynamic_job(name, fn)
        return app

    def test_an_unserializable_step_result_does_not_crash_the_walk(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The walker wrote `return_value` raw, so `json.dump` raised while
        persisting — after the step had already succeeded. Same defect T32
        fixed for fingerprints; step records were a second writer nobody
        classified.
        """
        monkeypatch.chdir(tmp_path)
        assert self._walk(tmp_path).execute("wf", scope_id="L1").status is (
            RunStatus.SUCCESS
        )

    def test_the_record_survives_even_though_the_value_cannot(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Position and status must persist regardless — a walk that cannot
        record where it got to cannot resume."""
        monkeypatch.chdir(tmp_path)
        self._walk(tmp_path).execute("wf", scope_id="L2")

        record = (StateStore.for_project(Path.cwd()).get_scope("L2") or {})["steps"][
            "open-handle::"
        ]
        assert record["status"] == "success"
        assert record["return_value"] is None
        assert record["return_value_reusable"] is False
        assert record["return_value_type"] == "lock"

    def test_the_next_step_gets_the_live_value(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The point of 19b: the record could not carry it, so the walk's own
        memory did."""
        monkeypatch.chdir(tmp_path)
        result = self._walk(tmp_path).execute("wf", scope_id="L3")

        assert result.return_value == "lock", (
            "the downstream step must receive the handle, not None"
        )

    def test_an_ordinary_value_still_comes_from_the_record(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Record-first: the live path must not take over the common case."""
        from functualize.job import job
        from functualize.workflow import END, Edge, Step, workflow

        monkeypatch.chdir(tmp_path)

        @job
        def produce() -> dict:
            return {"n": 1}

        @job
        def consume(v: Annotated[dict, FromJob("produce")] = None) -> str:
            return f"got {v}"

        @workflow(
            steps=[Step(produce), Step(consume)],
            edges=[
                Edge(source="produce", target="consume"),
                Edge(source="consume", target=END),
            ],
        )
        def wf2(seen: Annotated[str, FromJob("consume")] = "MISSING") -> str:
            return seen

        app = FunctualizeApp(name="record-first")
        for name, fn in [("produce", produce), ("consume", consume), ("wf2", wf2)]:
            app.register_dynamic_job(name, fn)
        result = app.execute("wf2", scope_id="L4")

        assert result.return_value == "got {'n': 1}", (
            "an ordinary value must still arrive via the record"
        )
