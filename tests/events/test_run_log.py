"""Events are persisted against the run that emitted them.

`durable-run-layer`/T4. Spec AC-4, AC-5, AC-6.

The bus emitted and forgot: nothing in `src/` or `plugins/` wrote an event
anywhere, so a run's own account of itself lasted as long as the process. This
pins the subscriber that keeps it, and the three constraints that shape it —
the bus gains no I/O, no write lands on the emit path, and a run with nothing
listening costs nothing.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest  # noqa: TC002

from functualize import FunctualizeApp, RunContext
from functualize._events.run_log import (
    RunLogSubscriber,
    current_run_id,
    pop_run,
    push_run,
)
from functualize._primitives.run_format import EVENTS_PER_RUN_LIMIT
from functualize._primitives.run_store import RunStore
from functualize._types.run_request import RunRequest
from functualize.app.utils import list_runs, run_events


def _store() -> RunStore:
    return RunStore.for_project(Path.cwd())


def _by_job() -> dict[str, dict[str, Any]]:
    return {row["job"]: row for row in list_runs(_store())}


def _events_of(job: str) -> list[str]:
    row = _by_job()[job]
    return [e.get("event") for e in (run_events(_store(), row["run_id"]) or [])]


class TestEventsLandOnTheirRun:
    """AC-4, through a real run rather than a hand-built record."""

    def test_a_jobs_event_is_persisted(self) -> None:
        app = FunctualizeApp(name="run-log")

        def emitter(rc: RunContext) -> str:
            rc.events.emit("demo.thing.happened", "resource", n=1)
            return "ok"

        app.register_dynamic_job("emitter", emitter)
        app.execute(RunRequest(job_name="emitter", surface="app.execute"))

        assert "demo.thing.happened" in _events_of("emitter")

    def test_the_payload_survives(self) -> None:
        app = FunctualizeApp(name="payload")

        def emitter(rc: RunContext) -> str:
            rc.events.emit("demo.thing.happened", "res", answer=42, who="me")
            return "ok"

        app.register_dynamic_job("emitter", emitter)
        app.execute(RunRequest(job_name="emitter", surface="app.execute"))

        row = _by_job()["emitter"]
        events = run_events(_store(), row["run_id"]) or []
        mine = next(e for e in events if e["event"] == "demo.thing.happened")
        assert mine["payload"] == {"answer": 42, "who": "me"}
        assert mine["resource"] == "res"

    def test_events_are_ordered_by_seq(self) -> None:
        """Ordered by the store's sequence, never by timestamp.

        Two processes on two clocks cannot order by time; `seq` is assigned by
        the store and is monotonic per run.
        """
        app = FunctualizeApp(name="ordered")

        def emitter(rc: RunContext) -> str:
            for i in range(5):
                rc.events.emit("demo.step.done", "res", i=i)
            return "ok"

        app.register_dynamic_job("emitter", emitter)
        app.execute(RunRequest(job_name="emitter", surface="app.execute"))

        events = run_events(_store(), _by_job()["emitter"]["run_id"]) or []
        assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
        steps = [e["payload"]["i"] for e in events if e["event"] == "demo.step.done"]
        assert steps == [0, 1, 2, 3, 4]


class TestEachRunGetsItsOwn:
    """The attribution question, which is the hard part of this feature."""

    def test_a_childs_events_do_not_leak_into_its_parent(self) -> None:
        app = FunctualizeApp(name="nested")

        def child(rc: RunContext) -> str:
            rc.events.emit("demo.child.did", "c")
            return "ok"

        def parent(rc: RunContext) -> str:
            rc.events.emit("demo.parent.did", "p")
            rc.invoke("child")
            return "ok"

        app.register_dynamic_job("child", child)
        app.register_dynamic_job("parent", parent)
        app.execute(RunRequest(job_name="parent", surface="app.execute"))

        parent_events, child_events = _events_of("parent"), _events_of("child")
        assert "demo.parent.did" in parent_events
        assert "demo.child.did" in child_events
        assert "demo.child.did" not in parent_events, (
            "the child's event was filed under the parent — the innermost run "
            "on the thread is the one that owns it"
        )
        assert "demo.parent.did" not in child_events

    def test_a_parallel_items_events_reach_its_own_run(self) -> None:
        """The case a `ContextVar` would get wrong, and why this is thread-local.

        `invoke_parallel` runs items on worker threads. A `ContextVar` set in
        the parent is **not** inherited by a thread it did not create, so a
        child would read an empty context and its events would be filed under
        nothing. The stack is pushed by `engine.run()`, which executes *on* the
        worker — so the worker pushes its own.
        """
        app = FunctualizeApp(name="parallel")

        def item(rc: RunContext, tag: str = "") -> str:
            rc.events.emit("demo.item.ran", tag)
            return tag

        def fan(rc: RunContext) -> str:
            rc.invoke_parallel([("item", {"tag": "a"}), ("item", {"tag": "b"})])
            return "ok"

        app.register_dynamic_job("item", item)
        app.register_dynamic_job("fan", fan)
        app.execute(RunRequest(job_name="fan", surface="app.execute"))

        item_runs = [r for r in list_runs(_store()) if r["job"] == "item"]
        assert len(item_runs) == 2, f"expected two batch items, got {len(item_runs)}"
        for row in item_runs:
            names = [e["event"] for e in (run_events(_store(), row["run_id"]) or [])]
            assert "demo.item.ran" in names, (
                "a parallel item's event did not reach its own run — the run id "
                "is not visible on the worker thread"
            )


class TestTheEmitPathStaysCheap:
    def test_the_bus_does_no_file_io(self) -> None:
        """AC-5, asserted against the source rather than the behaviour.

        The behaviour test would pass if the write moved somewhere equally
        wrong. This is the same shape as the task's own gate: persistence is a
        subscriber, and `bus.py` must not learn about files.
        """
        bus_source = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "functualize"
            / "_events"
            / "bus.py"
        ).read_text()
        for forbidden in ("open(", "json.dump", "write_text", "Path("):
            assert forbidden not in bus_source, (
                f"`{forbidden}` appeared in _events/bus.py — persistence is a "
                f"subscriber, and the bus stays fire-and-forget (AC-5)"
            )

    def test_a_run_with_no_subscriber_writes_no_events(self, tmp_path: Path) -> None:
        """AC-6. With nothing subscribed the bus returns before building an event.

        Exercised by emitting on a bare bus rather than by unsubscribing the
        app's, so this measures the property rather than the teardown.
        """
        from functualize._events.bus import EventBus

        bus = EventBus()
        assert not bus.has_subscribers
        for _ in range(100):
            bus.emit("demo.thing.happened", "res", n=1)

        assert not list(tmp_path.rglob("*.json")), (
            "emitting with no subscriber wrote something"
        )

    def test_buffering_means_one_write_per_run(self) -> None:
        """No file lock on the emit path — the reason events are buffered.

        Counted as *store writes*, not as elapsed time: a timing assertion here
        would be flaky, and the claim is structural.
        """
        writes: list[str] = []

        class _CountingStore:
            def __init__(self, real: RunStore) -> None:
                self._real = real

            def batch(self) -> Any:
                writes.append("batch")
                return self._real.batch()

            def append_event(self, run_id: str, event: dict[str, Any]) -> int:
                return self._real.append_event(run_id, event)

        real = _store()
        subscriber = RunLogSubscriber(lambda: _CountingStore(real))

        push_run("run-x")
        try:
            for i in range(50):
                subscriber(_FakeEvent(f"demo.step.n{i}"))
        finally:
            pop_run("run-x")

        assert writes == [], "an event reached the store before the run ended"
        subscriber.close_run("run-x")
        assert writes == ["batch"], f"expected exactly one batched write: {writes}"


class _FakeEvent:
    """The three fields the subscriber reads, without booting a bus."""

    def __init__(self, name: str) -> None:
        self.event_name = name
        self.resource = ""
        self.payload: dict[str, Any] = {}
        self.trace_id = None
        self.span_id = None


class TestTheBufferIsBounded:
    def test_a_runs_events_are_capped(self) -> None:
        """Risk R-c. A long walk emits without bound; the log must not.

        Capped **in memory**, so an over-long run costs nothing extra on disk
        either — the cap is not a trim applied after the fact.
        """
        subscriber = RunLogSubscriber(lambda: _store(), limit=10)
        push_run("run-y")
        try:
            for i in range(25):
                subscriber(_FakeEvent(f"demo.step.n{i}"))
        finally:
            pop_run("run-y")

        buffered = subscriber._buffers["run-y"]
        assert len(buffered) == 10
        assert buffered[-1]["event"] == "demo.step.n24", "the newest must survive"
        assert buffered[0]["event"] == "demo.step.n15", "the oldest must go first"

    def test_the_default_cap_is_the_stores(self) -> None:
        """One number, not two. A buffer larger than the store's ring would
        write events the store immediately discards."""
        assert RunLogSubscriber(lambda: _store())._limit == EVENTS_PER_RUN_LIMIT


class TestTheRunStack:
    """The mechanism, tested directly because its edges are easy to get wrong."""

    def test_push_and_pop_nest(self) -> None:
        assert current_run_id() is None
        push_run("a")
        push_run("b")
        assert current_run_id() == "b"
        pop_run("b")
        assert current_run_id() == "a"
        pop_run("a")
        assert current_run_id() is None

    def test_a_none_id_pushes_nothing(self) -> None:
        """An unrecordable run must not shadow the run enclosing it.

        Popping unconditionally in a `finally` would corrupt the stack the
        first time a push was skipped — which is why `pop_run` matches on the
        value.
        """
        push_run("outer")
        try:
            push_run(None)
            assert current_run_id() == "outer"
            pop_run(None)
            assert current_run_id() == "outer"
        finally:
            pop_run("outer")
        assert current_run_id() is None

    def test_each_thread_has_its_own(self) -> None:
        seen: dict[str, str | None] = {}
        push_run("main")
        try:

            def look() -> None:
                seen["other"] = current_run_id()

            thread = threading.Thread(target=look)
            thread.start()
            thread.join(timeout=5)
        finally:
            pop_run("main")

        assert seen["other"] is None, (
            "a thread inherited another thread's run — events would be filed "
            "under a run that is not executing there"
        )


class TestItNeverDisturbsARun:
    def test_a_store_that_cannot_be_written_does_not_fail_the_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An observation is never worth a run.

        Same guarantee the run record itself has: a full disk must not turn a
        job that did its work into a visible failure.
        """

        def _explode() -> Any:
            raise OSError("disk full")

        app = FunctualizeApp(name="broken-log")

        def emitter(rc: RunContext) -> str:
            rc.events.emit("demo.thing.happened", "res")
            return "ok"

        app.register_dynamic_job("emitter", emitter)
        subscriber = app.run_log
        assert subscriber is not None, "the app booted without a run log"
        monkeypatch.setattr(subscriber, "_store_for", _explode)

        result = app.execute(RunRequest(job_name="emitter", surface="app.execute"))
        assert result.status.value == "Success"

    def test_a_malformed_event_is_skipped_not_raised(self) -> None:
        subscriber = RunLogSubscriber(lambda: _store())
        push_run("run-z")
        try:
            subscriber(object())  # type: ignore[arg-type]
        finally:
            pop_run("run-z")
        assert subscriber._buffers.get("run-z") in (None, [])


class TestEventsOutsideARunAreDropped:
    def test_nothing_is_buffered_with_an_empty_stack(self) -> None:
        """Boot, discovery and CLI parsing belong to the *process*, not a run.

        Inventing a run for them would make the log claim something false.
        """
        subscriber = RunLogSubscriber(lambda: _store())
        subscriber(_FakeEvent("demo.boot.happened"))
        assert subscriber._buffers == {}


class TestTheLogIsReachableFromTheSurfaces:
    def test_the_cli_shows_a_runs_events(self) -> None:
        from click.testing import CliRunner

        app = FunctualizeApp(name="cli-events")

        def emitter(rc: RunContext) -> str:
            rc.events.emit("demo.thing.happened", "res")
            return "ok"

        app.register_dynamic_job("emitter", emitter)
        app.execute(RunRequest(job_name="emitter", surface="app.execute"))
        run_id = _by_job()["emitter"]["run_id"]

        result = CliRunner().invoke(
            app.cli_command,
            ["builtin", "run", "show", run_id, "--events", "--format", "json"],
            catch_exceptions=False,
        )
        payload = json.loads(result.output)
        assert any(e["event"] == "demo.thing.happened" for e in payload["events"])
