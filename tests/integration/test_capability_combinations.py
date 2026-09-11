"""Every DI capability at once, across a multi-step workflow, observed only
from the outside.

The rule this file holds itself to: **nothing is asserted by reaching into an
object.** No mocks, no doubles, no reading a private attribute to see whether
something happened. Every claim is checked through a channel a user also has —

===================  =========================================================
channel              what it proves
===================  =========================================================
``state``            a later job read what an earlier one wrote
the event bus        the run emitted what it said it emitted
the run log          parentage: who invoked whom, and in which batch
the perf timeline    both doors wrote to one timeline
the job's return     the body ran and saw what it should have
===================  =========================================================

That constraint is the whole point. `Perf` shipped unwired for its entire life
because every test that exercised it used `NoopPerf`, a double that accepts
anything silently — a test which supplies its own collaborators cannot detect
that production supplies none (ADR-021, `contributor/guides/wiring-discipline.md`).

The topology is deliberately awkward: a workflow whose steps invoke, whose
invocations fan out in parallel, whose parallel items write state their parent
reads, and whose epilogue has to see all of it. Each of those is a separate
seam that has been broken at least once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from functualize import END, Edge, FunctualizeApp, RunContext, Step, workflow

# Real imports, not a TYPE_CHECKING block: under `from __future__ import
# annotations` these are strings, and the DI resolution plan resolves them with
# `get_type_hints` against module globals. In a TYPE_CHECKING block every job
# below would silently receive no capability — which is the failure this file
# exists to catch.
from functualize._engine.capabilities.invoke import Invoke  # noqa: TC001
from functualize._engine.capabilities.job_context import JobContext  # noqa: TC001
from functualize._engine.capabilities.log import Log  # noqa: TC001
from functualize._engine.capabilities.perf import Perf  # noqa: TC001
from functualize._engine.capabilities.state import State  # noqa: TC001
from functualize._events.perf import perf_timeline
from functualize._types.run_request import RunRequest


@pytest.fixture
def timeline_on() -> Any:
    was = perf_timeline.enabled
    perf_timeline.enabled = True
    yield
    perf_timeline.enabled = was


@pytest.fixture
def project(tmp_path: Path, monkeypatch: Any) -> Path:
    """A real project directory, so the stores are real files."""
    (tmp_path / ".functualize").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _build(app: FunctualizeApp) -> None:
    """A workflow whose steps invoke, fan out, and share state.

    ingest ──> transform ──> fanout ──> report ──> END
                   │            │
                   │            └─ invoke_parallel: worker × 3
                   └─ invoke: enrich
    """

    def enrich(state: State, log: Log) -> str:
        """Invoked by a step. Writes where its caller can see it."""
        log("enriching")
        state.set("enrich.ran", True)
        return "enriched"

    def worker(state: State, jc: JobContext, slot: str = "x") -> str:
        """A parallel item. Its writes must reach the parent's store.

        `invoke_parallel` hands items to a thread pool, and a fresh thread
        starts with an empty context — which is why the run identity travels on
        the request rather than in a ContextVar, and why this assertion is
        worth having.
        """
        state.set(f"worker.{slot}", jc.name)
        return slot

    def ingest(rc: RunContext, state: State, perf: Perf, log: Log) -> str:
        perf.mark_start("ingest")
        log("ingesting")
        state.set("ingest.rows", 500)
        state.set("ingest.source", "fixture")
        # Three segments: the bus enforces `{domain}.{resource}.{action}`.
        rc.events.emit("pipeline.rows.ingested", resource="rows", count=500)
        perf.mark_end("ingest")
        return "ingested"

    def transform(rc: RunContext, state: State, inv: Invoke) -> str:
        """Reads the previous step's state, then invokes a child of its own."""
        rows = state.get("ingest.rows")
        state.set("transform.doubled", rows * 2)
        inv("enrich")
        # Both doors, same store: written through the parameter, read through
        # the context.
        assert rc.state.get("enrich.ran") is True
        return "transformed"

    def fanout(rc: RunContext) -> str:
        results = rc.invoke_parallel([("worker", {"slot": s}) for s in ("a", "b", "c")])
        rc.state.set("fanout.count", len(results))
        return "fanned"

    def report(rc: RunContext, state: State, perf: Perf) -> str:
        perf.mark_start("report")
        # Everything every earlier job wrote, through either door, is here.
        state.set("report.seen", sorted(state.keys()))
        perf.mark_end("report")
        return "reported"

    @workflow(
        steps=[
            Step("ingest"),
            Step("transform"),
            Step("fanout"),
            Step("report"),
        ],
        edges=[
            Edge("ingest", "transform"),
            Edge("transform", "fanout"),
            Edge("fanout", "report"),
            Edge("report", END),
        ],
    )
    def pipeline(rc: RunContext) -> dict[str, Any]:
        """The epilogue. Runs after the walk, and must see all of it."""
        return {
            "keys": sorted(rc.state.keys()),
            "doubled": rc.state.get("transform.doubled"),
            "workers": sorted(rc.state.keys("worker.*")),
            "fanout_count": rc.state.get("fanout.count"),
        }

    for name, fn in (
        ("enrich", enrich),
        ("worker", worker),
        ("ingest", ingest),
        ("transform", transform),
        ("fanout", fanout),
        ("report", report),
        ("pipeline", pipeline),
    ):
        app.register_dynamic_job(name, fn)


@pytest.fixture
def run(project: Path, timeline_on: Any) -> Any:
    """Execute the pipeline once and hand back only external observations."""
    app = FunctualizeApp(name="combo")
    events: list[tuple[str, dict[str, Any]]] = []

    @app.hooks.on_event("pipeline.*")
    def _collect(event: Any) -> None:
        events.append((event.event_name, dict(event.payload)))

    _build(app)
    result = app.execute(
        RunRequest(
            job_name="pipeline", surface="app.execute", workflow_scope_id="combo"
        )
    )
    assert result.status.value == "Success", result.exception
    return {"app": app, "result": result, "events": events, "project": project}


class TestStateTravelsEveryHop:
    """A value written anywhere in the run is readable everywhere after it."""

    def test_a_step_reads_the_previous_steps_write(self, run: Any) -> None:
        assert run["result"].return_value["doubled"] == 1000

    def test_an_invoked_childs_write_reaches_its_caller(self, run: Any) -> None:
        """`transform` asserted this inline; the epilogue confirms it persisted."""
        assert "enrich.ran" in run["result"].return_value["keys"]

    def test_parallel_items_write_into_the_parents_store(self, run: Any) -> None:
        """Three worker threads, one store, three keys.

        The thread pool is the interesting part: a fresh worker thread has an
        empty context, so anything carried contextually would be missing here.
        """
        assert run["result"].return_value["workers"] == [
            "worker.a",
            "worker.b",
            "worker.c",
        ]

    def test_the_epilogue_sees_every_step(self, run: Any) -> None:
        keys = run["result"].return_value["keys"]
        for expected in (
            "ingest.rows",
            "transform.doubled",
            "enrich.ran",
            "fanout.count",
            "report.seen",
        ):
            assert expected in keys, f"{expected} missing from {keys}"

    def test_the_glob_separates_namespaces_under_real_load(self, run: Any) -> None:
        """`worker.*` must not pick up `report.seen` or `fanout.count`."""
        assert all(
            k.startswith("worker.") for k in run["result"].return_value["workers"]
        )


class TestTheRunEmittedWhatItSaid:
    """Observed through the event bus, which is what a user subscribes to."""

    def test_a_job_emitted_event_reaches_a_subscriber(self, run: Any) -> None:
        names = [name for name, _ in run["events"]]
        assert "pipeline.rows.ingested" in names

    def test_the_payload_survives_the_trip(self, run: Any) -> None:
        payload = next(p for n, p in run["events"] if n == "pipeline.rows.ingested")
        assert payload["count"] == 500


class TestTheRunLogRecordsParentage:
    """Who invoked whom, read back from ``runs.json`` — not from an object."""

    def _store(self, run: Any) -> Any:
        from functualize._primitives.run_store import RunStore

        return RunStore.beside_fresh(run["app"].execution_engine._state_store().path)

    def test_the_log_recorded_the_run(self, run: Any) -> None:
        assert self._store(run).run_ids(), "no run was recorded at all"

    def test_every_job_that_ran_appears(self, run: Any) -> None:
        store = self._store(run)
        names = {(store.get_run(rid) or {}).get("job") for rid in store.run_ids()}
        for expected in ("pipeline", "ingest", "transform", "fanout", "report"):
            assert expected in names, f"{expected} missing from {sorted(names)}"

    def test_parallel_items_are_recorded_under_their_parent(self, run: Any) -> None:
        """The case a ContextVar could not have carried."""
        store = self._store(run)
        fanout_ids = [
            rid
            for rid in store.run_ids()
            if (store.get_run(rid) or {}).get("job") == "fanout"
        ]
        assert fanout_ids, "fanout was never recorded"
        children = store.children_of(fanout_ids[0])
        worker_children = [c for c in children if c.get("job") == "worker"]
        assert len(worker_children) == 3, (
            f"expected 3 worker children of fanout, got {len(worker_children)}"
        )

    def test_an_invoked_child_names_its_caller(self, run: Any) -> None:
        store = self._store(run)
        transform_ids = [
            rid
            for rid in store.run_ids()
            if (store.get_run(rid) or {}).get("job") == "transform"
        ]
        assert transform_ids
        names = {c.get("job") for c in store.children_of(transform_ids[0])}
        assert "enrich" in names


class TestPerfIsOneTimeline:
    """Marks made through the DI door and the rc door, seen together."""

    def test_marks_from_several_jobs_land_in_one_report(self, run: Any) -> None:
        recorded = {phase.name for phase in perf_timeline.report().phases}
        assert {"ingest.ingest", "report.report"} <= recorded, (
            f"expected marks from both jobs, saw {sorted(recorded)}"
        )


class TestTheSeamsThatBreak:
    """Combinations that have each been broken at least once."""

    def test_a_capability_declared_before_runcontext_still_resolves(
        self, project: Path
    ) -> None:
        """Parameter order must not matter.

        The DI factory runs during parameter resolution, so a capability listed
        before `rc` is built while the RunContext does not yet exist. Capturing
        it eagerly captured `None`.
        """
        app = FunctualizeApp(name="order")
        seen: dict[str, Any] = {}

        def job(inv: Invoke, state: State, perf: Perf, log: Log, rc: RunContext) -> str:
            seen["same_state"] = rc.state is state
            seen["invoke_usable"] = callable(inv)
            return "ok"

        app.register_dynamic_job("job", job)
        result = app.execute(
            RunRequest(job_name="job", surface="app.execute", workflow_scope_id="order")
        )
        assert result.status.value == "Success", result.exception
        assert seen["same_state"] is True, (
            "rc.state and a `state:` parameter were different objects"
        )

    def test_a_failing_step_does_not_lose_the_earlier_steps_state(
        self, project: Path
    ) -> None:
        """The run fails; what already happened is still recorded.

        This is the case the in-memory store handled worst — a run that stops
        partway is exactly when someone needs to see how far it got.
        """
        app = FunctualizeApp(name="broken")

        def good(state: State) -> str:
            state.set("good.done", True)
            return "ok"

        def bad(state: State) -> str:
            state.set("bad.reached", True)
            raise RuntimeError("deliberate")

        @workflow(
            steps=[Step("good"), Step("bad")],
            edges=[Edge("good", "bad"), Edge("bad", END)],
        )
        def flow(rc: RunContext) -> str:
            return "never"

        for name, fn in (("good", good), ("bad", bad), ("flow", flow)):
            app.register_dynamic_job(name, fn)

        result = app.execute(
            RunRequest(
                job_name="flow", surface="app.execute", workflow_scope_id="broken"
            )
        )
        assert result.status.value != "Success"

        # Read it back the way a later process would: a fresh store over the
        # same file, not the objects the failed run left behind.
        from functualize._primitives.scope_store import ScopeStore

        scopes = ScopeStore.beside_fresh(app.execution_engine._state_store().path)
        state = scopes.state_snapshot("broken")
        assert state.get("good.done") is True, (
            "a completed step's state was lost because a later step failed"
        )
        assert state.get("bad.reached") is True, (
            "the failing step's own write was rolled back; state is not "
            "transactional and must not pretend to be"
        )


class TestAPlainJobIsNotAWorkflow:
    """A job that never walked a graph must not appear as a running workflow.

    Every run gets a scope, because that is where `rc.state` lives, and the
    record is written lazily on first store. So `func myjob` calling
    `rc.state.set(...)` leaves a record — correctly — but it walked no graph,
    has no steps, and nothing will ever mark it finished. Listed as a workflow
    it was a phantom that could not be resumed and could not be purged, since
    `workflow purge` refuses running scopes.
    """

    def test_a_job_that_never_touches_state_writes_no_record(
        self, project: Path
    ) -> None:
        """Lazily written, so the common case costs nothing."""
        from functualize._primitives.scope_store import ScopeStore

        app = FunctualizeApp(name="plain")

        def plain() -> str:
            return "ok"

        app.register_dynamic_job("plain", plain)
        for _ in range(3):
            assert (
                app.execute(
                    RunRequest(job_name="plain", surface="app.execute")
                ).status.value
                == "Success"
            )

        scopes = ScopeStore.beside_fresh(app.execution_engine._state_store().path)
        assert scopes.scope_ids() == [], (
            "three runs that stored nothing still wrote scope records"
        )

    def test_a_plain_jobs_state_is_not_listed_as_a_workflow(
        self, project: Path
    ) -> None:
        from functualize._primitives.fresh_store import FreshStore
        from functualize.app.utils import list_scopes

        app = FunctualizeApp(name="plain")

        def writes(rc: RunContext) -> str:
            rc.state.set("k", 1)
            return "ok"

        app.register_dynamic_job("writes", writes)
        assert (
            app.execute(
                RunRequest(job_name="writes", surface="app.execute")
            ).status.value
            == "Success"
        )

        store = FreshStore(app.execution_engine._state_store().path)
        assert list_scopes(app, store) == [], (
            "a plain job's state record was listed as a running workflow"
        )

    def test_a_real_workflow_is_still_listed(self, project: Path) -> None:
        """The filter must not hide the thing the command exists for.

        Without this the previous test passes by listing nothing at all.
        """
        from functualize._primitives.fresh_store import FreshStore
        from functualize.app.utils import list_scopes

        app = FunctualizeApp(name="real")
        _build(app)
        assert (
            app.execute(
                RunRequest(
                    job_name="pipeline",
                    surface="app.execute",
                    workflow_scope_id="listed",
                )
            ).status.value
            == "Success"
        )
        store = FreshStore(app.execution_engine._state_store().path)
        rows = list_scopes(app, store, state="completed")
        assert any(r["workflow_id"] == "listed" for r in rows), (
            f"the real workflow vanished from the listing: {rows}"
        )
