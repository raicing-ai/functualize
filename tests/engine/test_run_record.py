"""Every run through `engine.run()` leaves a record — including the ones history drops.

Two logs, two questions, and the difference is the reason for having both:

- **The history ring** answers *"what did I ask for"*. Capped at 200, top-level
  only, so a deep workflow cannot evict a user's own launches. Its rules are
  `_records_history`'s and this feature does not touch them — `durable-run-layer`
  T2's gate exists to prove that.
- **The run log** answers *"what happened in this project"*. Every run, children
  included, because a child with no record makes the tree unanswerable.

The parentage is the half that is easy to get subtly wrong, and the mechanism
matters: `parent_run_id` rides on the **request**, not in a `ContextVar`.
`rc.invoke_parallel` runs its items on a `ThreadPoolExecutor` and a fresh thread
starts with an empty context — so the batch items, which are exactly the children
whose parentage the log most needs, are the ones a context variable would lose.
`TestParallelItemsKeepTheirParent` is that assertion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests._support.engine_run import register

from functualize._app.state import AppState
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry
from functualize._primitives.di import DIRegistry
from functualize._primitives.run_store import RunStore
from functualize._primitives.state_store import StateStore
from functualize._types.enums import RunStatus
from functualize._types.run_request import RunRequest
from functualize.job import Deps, Invoke, job


@pytest.fixture(autouse=True)
def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A throwaway project with a state directory, like any real one."""
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield project
    AppState.reset()


@pytest.fixture
def engine(_project: Path) -> JobExecutionEngine:
    return JobExecutionEngine(
        di_registry=DIRegistry(),
        event_bus=EventBus(),
        hook_registry=HookRegistry(),
        middleware_chain=ExecutionMiddlewareChain(),
        state_root=_project,
    )


@pytest.fixture
def runs(engine: JobExecutionEngine) -> RunStore:
    return RunStore.beside_state(StateStore.for_project(engine.state_root).path)


class TestTheRecordOpensAndCloses:
    def test_a_successful_run_is_recorded(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        def build() -> str:
            return "built"

        register(engine, "build", build)
        engine.run(RunRequest(job_name="build", surface="func.job"))

        recent = runs.recent_runs()
        assert len(recent) == 1
        assert recent[0]["job"] == "build"
        assert recent[0]["status"] == "success"
        assert recent[0]["ended_at"]

    def test_a_failing_run_is_recorded_with_its_status(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        """A record is an observation, so the interesting runs are the ones
        that did not go well."""

        def boom() -> str:
            raise RuntimeError("boom")

        register(engine, "boom", boom)
        result = engine.run(RunRequest(job_name="boom", surface="func.job"))

        assert result.status is RunStatus.FAILURE
        assert runs.recent_runs()[0]["status"] == "failure"

    def test_it_carries_the_surface(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        """AC-2. "Which surface started this run" is answerable from the record
        rather than inferred from what else is in it."""

        def ping() -> str:
            return "pong"

        register(engine, "ping", ping)
        engine.run(RunRequest(job_name="ping", surface="func.job"))
        engine.run(RunRequest(job_name="ping", surface="mcp.tool"))

        surfaces = [r["surface"] for r in runs.recent_runs()]
        assert surfaces == ["mcp.tool", "func.job"], "newest first"

    def test_no_argument_values_reach_the_record(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        """The history ring's rule. A run log is read by more people than a
        job's caller, and an argument may be a secret."""

        def deploy(token: str = "") -> str:
            return "deployed"

        register(engine, "deploy", deploy)
        engine.run(
            RunRequest(
                job_name="deploy", surface="func.job", kwargs={"token": "hunter2"}
            )
        )

        record = runs.recent_runs()[0]
        assert record["args_hash"]
        assert "hunter2" not in runs.path.read_text()


class TestChildrenAreRecordedAndPlaced:
    def test_a_nested_invoke_child_names_its_parent(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        """The task's named test: a child gets a record with `parent_run_id`
        set — and does **not** appear in the history ring."""

        def child() -> str:
            return "child"

        def parent(invoke: Invoke) -> str:
            invoke("child")
            return "parent"

        register(engine, "child", child)
        register(engine, "parent", parent)
        result = engine.run(RunRequest(job_name="parent", surface="func.job"))
        assert result.status is RunStatus.SUCCESS, result.exception

        by_job = {r["job"]: r for r in runs.recent_runs()}
        assert set(by_job) == {"parent", "child"}
        assert by_job["child"]["parent_run_id"] == by_job["parent"]["run_id"]
        assert by_job["parent"]["parent_run_id"] is None
        assert by_job["child"]["invoke_depth"] == 1

    def test_the_child_is_absent_from_history(self, engine: JobExecutionEngine) -> None:
        """The other half of the same test, and the point of two logs.

        The ring is capped at 200 and top-level only precisely so a deep
        workflow cannot evict what a user launched. The run log records the
        child; the ring must not.
        """

        def child() -> str:
            return "child"

        def parent(invoke: Invoke) -> str:
            invoke("child")
            return "parent"

        register(engine, "child", child)
        register(engine, "parent", parent)
        result = engine.run(RunRequest(job_name="parent", surface="func.job"))
        assert result.status is RunStatus.SUCCESS, result.exception

        store = StateStore.for_project(engine.state_root)
        jobs = [entry.get("job") for entry in store.get_history()]
        assert "parent" in jobs
        assert "child" not in jobs, (
            "the history ring recorded a nested child; that is the ring's rule "
            "changing, which this feature must not do"
        )

    def test_a_dependency_names_its_dependent(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        @job
        def upstream() -> str:
            return "up"

        @job(deps=Deps("upstream"))
        def downstream() -> str:
            return "down"

        register(engine, "upstream", upstream)
        # `dependencies=` as well as the decorator: the job **graph** is built
        # from `RegisteredJob.dependencies`, which discovery fills from the
        # declaration. A hand-registered entry has to say it twice, and a test
        # that says it once gets a green run with no dependency — which is what
        # this test looked like before it asserted the upstream had a record.
        register(engine, "downstream", downstream, dependencies=("upstream",))
        result = engine.run(RunRequest(job_name="downstream", surface="func.job"))
        assert result.status is RunStatus.SUCCESS, result.exception

        by_job = {r["job"]: r for r in runs.recent_runs()}
        assert set(by_job) == {"upstream", "downstream"}, sorted(by_job)
        assert by_job["upstream"]["parent_run_id"] == by_job["downstream"]["run_id"]


class TestParallelItemsKeepTheirParent:
    """The case a `ContextVar` would lose, which is why the field is on the request.

    `Invoke.parallel` submits to a `ThreadPoolExecutor`, and a fresh thread
    starts with an **empty** context — so a context variable holding the current
    run id would be `None` in every worker, and a batch's items would all look
    like top-level runs. They are the children whose parentage the log most
    needs, so the mechanism that loses them there is the wrong mechanism.
    """

    def test_every_item_names_the_run_that_launched_the_batch(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        def item(n: int = 0) -> int:
            return n

        def batch(invoke: Invoke) -> str:
            invoke.parallel([("item", {"n": 1}), ("item", {"n": 2})])
            return "batched"

        register(engine, "item", item)
        register(engine, "batch", batch)
        engine.run(RunRequest(job_name="batch", surface="func.job"))

        records = runs.recent_runs()
        parent = next(r for r in records if r["job"] == "batch")
        items = [r for r in records if r["job"] == "item"]

        assert len(items) == 2, [r["job"] for r in records]
        assert {i["parent_run_id"] for i in items} == {parent["run_id"]}


def test_a_run_survives_a_store_that_cannot_be_written(
    engine: JobExecutionEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An observation is never worth a run.

    The falsifier for every test above: if recording were mandatory, this file
    would be asserting that the log works *and* silently making the engine
    fragile. A store that raises must cost the record, not the job.
    """
    import functualize._primitives.run_store as run_store

    def _explode(*_a: Any, **_kw: Any) -> Any:
        raise OSError("disk on fire")

    monkeypatch.setattr(run_store.RunStore, "open_run", _explode)
    monkeypatch.setattr(run_store.RunStore, "close_run", _explode)

    def build() -> str:
        return "built"

    register(engine, "build", build)
    result = engine.run(RunRequest(job_name="build", surface="func.job"))

    assert result.status is RunStatus.SUCCESS
    assert result.return_value == "built"
