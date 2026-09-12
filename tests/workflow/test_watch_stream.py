"""`watch` renders what the walk emitted, and nothing it could infer instead.

`workflow-graph-semantics`/T5. Spec AC-10, AC-11, AC-12. pi-workflows parity
test **5**.

The defect this closes is not "there is no watch command". It is that the only
way to build one, before F5, was a loop that re-read the scope record and worked
out what must have changed — and a difference between two readings is a **guess
about the interval between them**. It cannot tell a step that ran from one that
was replayed; it misses anything that started and finished inside one read; and
on a loop it cannot tell a second pass from the first. Risk **R-e** names that
shape: *a polling loop wearing a stream's clothes*.

So the property pinned here is narrow and checkable: **everything a watcher
renders came from an emit call.** `TestNothingIsInferred` is the half that
fails when someone reconstructs — remove the walker's emits and the stream is
empty, not merely less detailed.

`watch_scope` does ask the store repeatedly for "everything after seq N", and
that is a poll. There is no blocking read over a document store and there must
not be one over a substrate that is a table. What survives is the part that
matters, and the sabotage is what proves it survived.

AC-12 is the sentence `_workflow_view.derived_state` has carried all along:
*"a resumed walk reports `blocked` for its whole duration… live-versus-parked
needs a lease."* `walk_is_live` is that answered, and `TestAParkedScopeSaysSo`
is why it had to be: without it, watching a finished workflow waits for ever.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from functualize._engine.workflow_walker import WorkflowWalker
from functualize._events.bus import EventBus
from functualize._events.walk_log import install_walk_log
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.workflow import END, Edge, Loop, Step, WorkflowDeclaration
from functualize.app._workflow_view import walk_is_live, watch_scope


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    return ScopeStore(JsonFileSubstrate(tmp_path))


@pytest.fixture
def bus(store: ScopeStore) -> EventBus:
    """A bus with the walk log installed, writing to ``store``."""
    b = EventBus()
    install_walk_log(b, lambda: store)
    return b


class _Runner:
    def __init__(self, *failing: str) -> None:
        self.failing = set(failing)
        self.calls: list[str] = []

    def __call__(self, name: str) -> str:
        self.calls.append(name)
        if name in self.failing:
            raise RuntimeError(f"{name} blew up")
        return name


def _line() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("first"), Step("second")),
        edges=(
            Edge(source="first", target="second"),
            Edge(source="second", target=END),
        ),
    )


def _walk(
    store: ScopeStore,
    bus: EventBus | None,
    declaration: WorkflowDeclaration | None = None,
    *,
    runner: _Runner | None = None,
    scope_id: str = "s1",
) -> Any:
    return WorkflowWalker(
        declaration or _line(),
        store,
        scope_id,
        run_step=runner or _Runner(),
        emit=bus.emit if bus is not None else None,
    ).run()


def _names(events: list[dict[str, Any]]) -> list[str]:
    return [str(e["event"]).removeprefix("workflow.") for e in events]


def _nodes(events: list[dict[str, Any]]) -> list[str]:
    return [str((e.get("payload") or {}).get("node", "")) for e in events]


# ----------------------------------------------------------------------
# The two properties that make a watch *terminate*, and they come first
# because of what breaking them does.
#
# Neither fails a test when it breaks — both **hang** every test that watches
# anything, and a sweep that times out names no property at all. A cursor that
# does not move re-yields the whole log for ever; a scope that always looks
# live is waited on for ever. So each is asserted here, as directly as it can
# be, before anything that calls `watch_scope` on a real walk: under `-x` the
# run stops at the assertion that says which one broke.
# ----------------------------------------------------------------------


class TestTheCursorMovesForward:
    """`after` is a cursor, and asked of the store rather than of the watcher.

    Deliberately *not* through `watch_scope`: the failure this catches is the
    one that makes `watch_scope` never return, so a test that had to run it to
    completion could not report it.
    """

    def test_events_after_a_sequence_exclude_it(self, store: ScopeStore) -> None:
        store.ensure_scope("s1", "demo")
        for name in ("a", "b", "c"):
            store.append_event("s1", {"event": f"workflow.step.{name}"})

        assert [e["seq"] for e in store.events_for("s1")] == [1, 2, 3]
        assert [e["seq"] for e in store.events_for("s1", after=2)] == [3]
        assert store.events_for("s1", after=3) == []

    def test_the_sequence_never_restarts(self, store: ScopeStore) -> None:
        """What lets a watcher resume without comparing timestamps — which two
        processes on two clocks cannot do reliably."""
        store.ensure_scope("s1", "demo")
        first = [store.append_event("s1", {"event": "workflow.step.start"})]
        first.append(store.append_event("s1", {"event": "workflow.step.end"}))
        assert first == [1, 2]


# ----------------------------------------------------------------------
# AC-12 — parked, not running
# ----------------------------------------------------------------------


class TestAParkedScopeSaysSo:
    def test_a_scope_nobody_holds_is_not_live(self, store: ScopeStore) -> None:
        store.ensure_scope("s1", "demo")
        assert walk_is_live(store.get_scope("s1")) is False

    def test_a_held_scope_is_live(self, store: ScopeStore) -> None:
        store.ensure_scope("s1", "demo")
        store.claim_scope("s1", owner="me")
        assert walk_is_live(store.get_scope("s1")) is True

    def test_a_lapsed_lease_is_not_live(self, store: ScopeStore) -> None:
        """The difference from `_lease_has_lapsed`, which this must not be.

        That helper answers "was this abandoned", and treats an absent lease as
        no. This one answers "is anybody walking it", and both an expired lease
        and an absent one mean no.
        """
        store.ensure_scope("s1", "demo")
        store.claim_scope("s1", owner="dead", seconds=1)
        scope = store.get_scope("s1")
        past = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
        lease = {**scope["lease"], "expires_at": past}
        store._mutate(  # noqa: SLF001
            lambda env: env["scopes"]["s1"].__setitem__("lease", lease)
        )
        assert walk_is_live(store.get_scope("s1")) is False

    def test_watching_a_parked_scope_returns_instead_of_waiting(
        self, store: ScopeStore, bus: EventBus
    ) -> None:
        """The reason AC-12 is a requirement and not a nicety.

        A released lease is *expired in place*, so every finished scope looks
        the same as an abandoned one. Without this, `watch` on a workflow that
        ended an hour ago would print its history and then hang for ever.
        """
        _walk(store, bus)
        naps: list[float] = []
        seen = list(watch_scope(store, "s1", sleep=naps.append))
        assert seen, "the finished walk's history was not rendered"
        assert naps == [], f"it slept waiting for a walk nobody is running: {naps}"

    def test_a_live_scope_is_waited_on(self, store: ScopeStore, bus: EventBus) -> None:
        """The other direction: a held scope is followed, not abandoned early.

        A watcher that returned the moment the log went quiet would stop
        between two steps of a slow workflow, which is when someone is most
        likely to be watching it.
        """
        _walk(store, bus)
        store.claim_scope("s1", owner="still-here")

        naps: list[float] = []
        seen = list(
            watch_scope(
                store,
                "s1",
                timeout=1.0,
                sleep=naps.append,
                # Time moves only once something has waited, so the timeout
                # cannot fire before the wait it is meant to bound.
                clock=lambda: 99.0 if naps else 0.0,
            )
        )
        assert seen
        assert naps, "a live scope was not waited on"

    def test_a_vanished_scope_ends_the_watch(self, store: ScopeStore) -> None:
        assert list(watch_scope(store, "gone", sleep=lambda _: None)) == []


# ----------------------------------------------------------------------
# AC-11 — the walker emits, and that is the only source
# ----------------------------------------------------------------------


class TestTheWalkerEmits:
    def test_a_walk_reports_its_start_and_its_end(
        self, store: ScopeStore, bus: EventBus
    ) -> None:
        _walk(store, bus)
        assert _names(store.events_for("s1"))[0] == "walk.start"
        assert _names(store.events_for("s1"))[-1] == "walk.end"

    def test_every_node_reports_a_start_and_an_end(
        self, store: ScopeStore, bus: EventBus
    ) -> None:
        _walk(store, bus)
        events = store.events_for("s1")
        starts = [
            n
            for n, e in zip(_nodes(events), _names(events), strict=True)
            if e == "step.start"
        ]
        ends = [
            n
            for n, e in zip(_nodes(events), _names(events), strict=True)
            if e == "step.end"
        ]
        assert starts == ["first", "second"]
        assert ends == ["first", "second"]

    def test_the_sequence_is_monotonic(self, store: ScopeStore, bus: EventBus) -> None:
        """What lets a watcher resume without comparing timestamps — which two
        processes on two clocks cannot do reliably."""
        _walk(store, bus)
        seqs = [e["seq"] for e in store.events_for("s1")]
        assert seqs == sorted(seqs) == list(range(1, len(seqs) + 1))

    def test_a_replayed_step_says_so(self, store: ScopeStore, bus: EventBus) -> None:
        """The distinction a record diff cannot make.

        After a resume the step record reads `success` either way. Only the
        walk knows whether it *ran* this time, and only because it said so.
        """
        _walk(store, bus)
        before = len(store.events_for("s1"))
        _walk(store, bus)

        outcomes = [
            (e.get("payload") or {}).get("outcome")
            for e in store.events_for("s1", after=before)
            if e["event"] == "workflow.step.end"
        ]
        assert outcomes == ["replayed", "replayed"], outcomes

    def test_a_failure_reports_the_node_that_stopped(
        self, store: ScopeStore, bus: EventBus
    ) -> None:
        _walk(store, bus, runner=_Runner("second"))
        end = store.events_for("s1")[-1]
        assert end["event"] == "workflow.walk.end"
        assert (end.get("payload") or {}).get("outcome") == "failed"
        assert (end.get("payload") or {}).get("node") == "second"

    def test_each_loop_pass_is_distinguishable(
        self, store: ScopeStore, bus: EventBus
    ) -> None:
        """The other thing a record diff cannot see.

        Both passes write the same node name; only the iteration separates
        them, and only the event carries it while the walk is still going.
        """
        declaration = WorkflowDeclaration(
            nodes=(Step("body"),),
            edges=(
                Edge(source="body", target=END),
                Loop(source="body", target="body", max_iterations=3),
            ),
        )
        _walk(store, bus, declaration, scope_id="loop")

        passes = [
            (e.get("payload") or {}).get("iteration")
            for e in store.events_for("loop")
            if e["event"] == "workflow.step.start"
        ]
        assert passes == [0, 1, 2], passes


class TestNothingIsInferred:
    """The half that fails when someone reconstructs instead of following.

    Not a style check. A walker with no `emit` wired is the ordinary case —
    every other test in this suite builds one — so "the stream is empty when
    nothing emitted" is the property, and it is exactly what the R-e sabotage
    removes.
    """

    def test_a_walk_that_emits_nothing_is_watched_as_nothing(
        self, store: ScopeStore
    ) -> None:
        _walk(store, None)
        assert store.events_for("s1") == []
        assert list(watch_scope(store, "s1", sleep=lambda _: None)) == []

    def test_the_scope_still_advanced(self, store: ScopeStore) -> None:
        """The guard on the test above: an empty stream must mean *silence*,
        not a walk that never ran."""
        _walk(store, None)
        assert store.get_scope("s1")["status"] == "completed"

    def test_the_subscriber_files_by_scope_not_by_name(
        self, store: ScopeStore, bus: EventBus
    ) -> None:
        """Two runs of one workflow must not land in each other's log.

        `resource` is the workflow's name, which is what a reader wants to see
        and is not unique. The scope id in the payload is the address.
        """
        _walk(store, bus, scope_id="a")
        _walk(store, bus, scope_id="b")
        assert len(store.events_for("a")) == len(store.events_for("b")) > 0

    def test_an_event_without_a_scope_is_dropped(
        self, store: ScopeStore, bus: EventBus
    ) -> None:
        """Dropped, not filed under a placeholder.

        Asserting on one scope id would pass however the event were misfiled;
        the store's whole index is what shows that nothing was written at all.
        """
        bus.emit("workflow.walk.start", resource="nowhere")
        assert store.scope_ids() == []


# ----------------------------------------------------------------------
# AC-10 — following a live walk, including through a resume
# ----------------------------------------------------------------------


class TestWatchFollows:
    def test_it_yields_what_the_walk_emitted_in_order(
        self, store: ScopeStore, bus: EventBus
    ) -> None:
        _walk(store, bus)
        seen = list(watch_scope(store, "s1", sleep=lambda _: None))
        assert _names(seen) == _names(store.events_for("s1"))

    def test_after_resumes_a_watch(self, store: ScopeStore, bus: EventBus) -> None:
        _walk(store, bus)
        first = list(watch_scope(store, "s1", sleep=lambda _: None))
        _walk(store, bus)

        rest = list(
            watch_scope(store, "s1", after=first[-1]["seq"], sleep=lambda _: None)
        )
        assert rest, "a second walk emitted nothing a resumed watch could see"
        assert [e["seq"] for e in rest] == sorted(e["seq"] for e in rest)
        assert min(e["seq"] for e in rest) > first[-1]["seq"]

    def test_it_sees_a_resume_as_more_of_the_same_stream(
        self, store: ScopeStore, bus: EventBus
    ) -> None:
        """AC-10's "including through a resume".

        The scope outlives the runs that advance it, which is why the log is on
        the scope: one watcher, one sequence, however many processes it took.
        """
        _walk(store, bus, runner=_Runner("second"))
        store.set_scope_status("s1", "running")
        _walk(store, bus)

        seqs = [e["seq"] for e in store.events_for("s1")]
        assert seqs == list(range(1, len(seqs) + 1))


class TestTheWiringIsReal:
    """The one test that would fail if nothing were connected.

    **Last in the file deliberately.** It types the command with no
    `--timeout`, which is how it proves AC-12 — a parked scope ends the watch
    rather than waiting on a walk nobody is running. Sabotage `walk_is_live` and
    this hangs instead of failing, so the cheap property tests above it have to
    run first: under `-x` the sweep stops at the named assertion, which says
    *which* property broke. A run that hangs says nothing.

    Every other test in this file hands `bus.emit` to the walker by hand and
    installs the subscriber by hand, so all of them would still pass with the
    engine wired to nothing — the walker would emit into a bus the application
    never built, and `watch` would render an empty log for every real run.

    This one goes the whole way: a real `@workflow` through `app.execute`, the
    bus and subscriber the boot sequence installs, the scope store the engine
    resolves, and the `watch` command a person types.
    """

    @staticmethod
    def _app(project: Path) -> Any:
        from functualize._app.state import AppState
        from functualize.app.core import FunctualizeApp

        AppState.reset()
        instance = FunctualizeApp(name="watched")
        instance.register_dynamic_job("build", lambda: "artifact")
        instance.register_dynamic_job("ship", lambda: "shipped")

        from functualize.workflow import workflow

        @workflow(
            steps=[Step("build"), Step("ship")],
            edges=[
                Edge(source="build", target="ship"),
                Edge(source="ship", target=END),
            ],
        )
        def release() -> str:
            return "done"

        instance.register_dynamic_job("release", release)
        return instance

    def test_a_real_run_leaves_a_watchable_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._app.state import AppState
        from functualize.types import RunRequest

        project = tmp_path / "project"
        (project / ".functualize").mkdir(parents=True)
        monkeypatch.chdir(project)
        app = self._app(project)
        try:
            app.execute(
                RunRequest(
                    job_name="release",
                    surface="app.execute",
                    workflow_scope_id="rel-1",
                )
            )
            events = app.execution_engine._scope_store().events_for("rel-1")
        finally:
            AppState.reset()

        assert _names(events)[0] == "walk.start"
        assert "build" in _nodes(events)
        assert "ship" in _nodes(events)
        assert _names(events)[-1] == "walk.end"

    def test_the_watch_command_renders_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        import click

        from functualize._app.state import AppState
        from functualize._cli.builtins import register_builtin_commands
        from functualize.types import RunRequest

        project = tmp_path / "project"
        (project / ".functualize").mkdir(parents=True)
        monkeypatch.chdir(project)
        app = self._app(project)
        try:
            app.execute(
                RunRequest(
                    job_name="release",
                    surface="app.execute",
                    workflow_scope_id="rel-1",
                )
            )
            capsys.readouterr()
            root = click.Group(name="func")
            register_builtin_commands(root)
            root.main(
                args=["builtin", "workflow", "watch", "rel-1"],
                prog_name="func",
                standalone_mode=False,
                obj={"app": app},
            )
            out = capsys.readouterr().out
        finally:
            AppState.reset()

        assert "parked" in out, out
        assert "walk.start" in out, out
        assert "build" in out, out
        assert "walk.end" in out, out
