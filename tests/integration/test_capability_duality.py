"""The Constitution's *DI + RunContext Duality* rule, as executable tests.

> The DI registry and RunContext resolve from the **same underlying capability
> map** — they are two access paths, not competing systems.
> (`.spec/CONSTITUTION.md` → *DI + RunContext Duality*)

That rule was prose for its whole life, and five of the six capabilities that
have both access paths violated it. Each test below declares the capability the
way a user would, drives it through **both** doors, and observes the consequence
through the public entry point — no doubles, no mocks, no hand-built
collaborators.

The distinction matters more than it looks. Every capability here already had
unit tests, and they all passed, because a unit test constructs its subject
directly and a test double answers whatever the test wants to hear. `Perf` is
the clearest case: every test that called `perf.mark()` called it on `NoopPerf`,
the double that accepts everything silently, while the real injected `Perf`
raised `NotImplementedError` on every method for its entire life. A test that
supplies its own collaborators cannot detect that production supplies none
(`contributor/guides/wiring-discipline.md`).
"""

from __future__ import annotations

from typing import Any

import pytest

from functualize import FunctualizeApp, RunContext

# Real imports, not a TYPE_CHECKING block: with `from __future__ import
# annotations` every annotation is a string, and the DI resolution plan reads
# them back with `get_type_hints`, which looks them up in module globals. Under
# TC001's suggestion these jobs would resolve nothing and silently take no
# capability at all — the failure this whole file exists to catch.
from functualize._engine.capabilities.invoke import Invoke  # noqa: TC001
from functualize._engine.capabilities.log import Log  # noqa: TC001
from functualize._engine.capabilities.perf import Perf  # noqa: TC001
from functualize._events.perf import perf_timeline
from functualize._types.run_request import RunRequest


def _run(app: FunctualizeApp, name: str) -> Any:
    """Execute through the public entry point, as every surface does."""
    return app.execute(RunRequest(job_name=name, surface="app.execute"))


class TestInvokeHooksSeeTheSameParent:
    """`INVOKE_*` hooks receive the run's context through either door.

    The DI factory runs *during* parameter resolution, so for a job written
    ``def j(inv: Invoke, rc: RunContext)`` the RunContext does not exist yet
    when `inv` is built. Capturing it eagerly therefore captured ``None``, and
    every hook reached through an `inv:` parameter got ``None`` as its parent
    while the identical hook reached through ``rc.invoke`` got the context.
    """

    def _app(self, seen: list[str]) -> FunctualizeApp:
        app = FunctualizeApp(name="duality")

        @app.hooks.on_invoke_start
        def _start(rc: Any, job_name: str, kwargs: dict, depth: int) -> None:
            seen.append(type(rc).__name__)

        def child() -> str:
            return "ok"

        def via_rc(rc: RunContext) -> str:
            rc.invoke("child")
            return "done"

        # Deliberately declared *before* `rc`: this is the order that fails
        # when the capability captures its context at construction time.
        def via_di(inv: Invoke, rc: RunContext) -> str:
            inv("child")
            return "done"

        app.register_dynamic_job("child", child)
        app.register_dynamic_job("via_rc", via_rc)
        app.register_dynamic_job("via_di", via_di)
        return app

    def test_the_runcontext_door_reaches_the_hook(self) -> None:
        seen: list[str] = []
        assert _run(self._app(seen), "via_rc").status.value == "Success"
        assert seen == ["RunContext"]

    def test_the_di_door_reaches_the_hook_with_the_same_parent(self) -> None:
        seen: list[str] = []
        assert _run(self._app(seen), "via_di").status.value == "Success"
        assert seen == ["RunContext"], (
            "an `inv: Invoke` parameter fired INVOKE_START with parent=None; a "
            "hook calling rc.log() or rc.name raises there and works via "
            "rc.invoke()"
        )


class TestPerfWritesToOneTimeline:
    """A mark is a mark, whichever door made it.

    Both assertions are needed and they fail for different reasons: the first
    catches an unwired capability (the real defect — the factory returned the
    raising stub), the second catches a *wired but separate* one, which is what
    a second implementation of the prefixing rules would produce.
    """

    @pytest.fixture
    def timeline_on(self) -> Any:
        was = perf_timeline.enabled
        perf_timeline.enabled = True
        yield
        perf_timeline.enabled = was

    def test_an_injected_perf_records_rather_than_raising(
        self, timeline_on: Any
    ) -> None:
        app = FunctualizeApp(name="duality")

        def j(perf: Perf) -> str:
            perf.mark_start("work")
            perf.mark_end("work")
            return "ok"

        app.register_dynamic_job("j", j)
        result = _run(app, "j")
        assert result.status.value == "Success", (
            f"an injected Perf raised rather than recording: {result.exception}"
        )

    def test_both_doors_land_in_one_timeline(self, timeline_on: Any) -> None:
        app = FunctualizeApp(name="duality")
        seen: dict[str, list[str]] = {}

        def j(rc: RunContext, perf: Perf) -> str:
            perf.mark_start("via_di")
            perf.mark_end("via_di")
            rc.events.perf_mark_start("via_rc")
            rc.events.perf_mark_end("via_rc")
            seen["rc"] = sorted(p.name for p in rc.events.get_perf_phases())
            seen["di"] = sorted(p.name for p in perf.phases())
            return "ok"

        app.register_dynamic_job("j", j)
        assert _run(app, "j").status.value == "Success"
        assert seen["rc"] == seen["di"], "the two doors reported different phases"
        # Containment, not equality: `perf_timeline` is a module-level
        # singleton, so marks from any earlier same-named job in this process
        # are still in it. That leak is a separate defect (the timeline is
        # global mutable state, which the Constitution forbids) — asserting
        # equality here would make this test fail for that reason instead of
        # for the one it exists to check.
        assert {"j.via_di", "j.via_rc"} <= set(seen["rc"]), (
            "a mark made through one door was invisible to the other"
        )


class TestLogSharesOneSink:
    """The duality rule's one pre-existing implementation, held in place.

    `rc.log()` reads the job's own `Log` out of the live capability map, so it
    cannot drift to a different sink than the job's `log:` parameter. This is
    the behaviour every other capability was measured against.
    """

    def test_rc_log_and_an_injected_log_are_one_object(self) -> None:
        app = FunctualizeApp(name="duality")
        same: list[bool] = []

        def j(rc: RunContext, log: Log) -> str:
            same.append(rc._log_sink() is log)
            return "ok"

        app.register_dynamic_job("j", j)
        assert _run(app, "j").status.value == "Success"
        assert same == [True]


class TestADerivedContextKeepsItsWiring:
    """`wiring.with_plugin_config` returns a context that can still work.

    It used to rebuild the RunContext from the fields it happened to remember,
    and dropped seven: the derived context had no engine (so `invoke` raised),
    no run id, no cwd, and an `_invoke_depth` reset to 0 — which silently
    defeats the recursion guard for everything downstream of it.
    """

    def test_the_derived_context_can_still_invoke(self) -> None:
        app = FunctualizeApp(name="duality")
        ran: list[str] = []

        def child() -> str:
            ran.append("child")
            return "ok"

        def parent(rc: RunContext) -> str:
            derived = rc._derive()
            derived.invoke("child")
            return "done"

        app.register_dynamic_job("child", child)
        app.register_dynamic_job("parent", parent)
        result = _run(app, "parent")
        assert result.status.value == "Success", result.exception
        assert ran == ["child"]

    def test_the_derived_context_keeps_every_wiring_field(self) -> None:
        app = FunctualizeApp(name="duality")
        drifted: list[str] = []

        def j(rc: RunContext) -> str:
            derived = rc._derive()
            for attr in (
                "_run_id",
                "_parent_request",
                "_execution_engine",
                "_invoke_depth",
                "_max_invoke_depth",
                "_cwd",
                "_job_directory",
                "_workflow_scope",
                "_di_registry",
                "_caps",
            ):
                if getattr(derived, attr) is not getattr(rc, attr):
                    drifted.append(attr)
            return "ok"

        app.register_dynamic_job("j", j)
        assert _run(app, "j").status.value == "Success"
        assert drifted == [], f"deriving a context dropped {drifted}"


class TestStateCarriesAcrossOneRun:
    """State written by one job in a run is readable by the next.

    `rc.state` returns the scope's store only `if self._workflow_scope is not
    None`, and `nested_request` resets `parent_scope` unless a caller states
    it. The workflow orchestrator stated the scope *id* and not the scope
    *object*, so every step arrived with no scope, lazily built a private
    store, and wrote into something nothing would ever read — silently, with
    no test and no doc describing the behaviour either way.

    The run is the boundary (ADR-021): jobs within one run share, two runs
    share nothing.
    """

    def _app(self, seen: dict[str, Any]) -> FunctualizeApp:
        from functualize import END, Edge, Step, workflow

        app = FunctualizeApp(name="duality")

        def s1(rc: RunContext) -> str:
            rc.state.set("fetch.rows", 500)
            return "ok"

        def s2(rc: RunContext) -> str:
            seen["step sees earlier step"] = rc.state.get("fetch.rows")
            seen["prefix filter"] = rc.state.keys("fetch.")
            return "ok"

        @workflow(
            steps=[Step("s1"), Step("s2")],
            edges=[Edge("s1", "s2"), Edge("s2", END)],
        )
        def flow(rc: RunContext) -> str:
            seen["epilogue sees step"] = rc.state.get("fetch.rows")
            return "done"

        for name, fn in (("s1", s1), ("s2", s2), ("flow", flow)):
            app.register_dynamic_job(name, fn)
        return app

    def test_a_later_step_reads_an_earlier_steps_write(self) -> None:
        seen: dict[str, Any] = {}
        assert _run(self._app(seen), "flow").status.value == "Success"
        assert seen["step sees earlier step"] == 500

    def test_the_epilogue_reads_the_steps_writes(self) -> None:
        seen: dict[str, Any] = {}
        assert _run(self._app(seen), "flow").status.value == "Success"
        assert seen["epilogue sees step"] == 500

    def test_the_documented_key_convention_is_usable(self) -> None:
        """`"fetch.rows"` + `keys("fetch.")` — a convention, not a namespace API.

        One flat store per run is the maintainer's decision, so two steps can
        pick the same key name. The remedy is a string prefix rather than a
        second concept, which only works if `keys` can filter by one.
        """
        seen: dict[str, Any] = {}
        assert _run(self._app(seen), "flow").status.value == "Success"
        assert seen["prefix filter"] == ["fetch.rows"]

    def test_two_runs_of_one_workflow_share_nothing(self) -> None:
        """The run is the boundary — the half that makes sharing safe."""
        seen_a: dict[str, Any] = {}
        app = self._app(seen_a)
        assert _run(app, "flow").status.value == "Success"

        leaked: dict[str, Any] = {}

        def probe(rc: RunContext) -> str:
            leaked["value"] = rc.state.get("fetch.rows")
            return "ok"

        app.register_dynamic_job("probe", probe)
        assert _run(app, "probe").status.value == "Success"
        assert leaked["value"] is None, (
            "a later, unrelated run saw the workflow's state — the scope is "
            "supposed to bound sharing to one run"
        )


class TestThePrefixConventionHasASharpEdge:
    """`keys(prefix)` is `str.startswith`, so the separator is load-bearing.

    Choosing a convention over a namespace API costs one concept instead of
    two, and this is the bill: `keys("fetch")` also matches `"fetchmeta.x"` —
    another job's key. The docstring shows the separator in every example for
    this reason, and this test is what keeps that claim true.
    """

    def test_the_separator_is_what_bounds_the_namespace(self) -> None:
        from functualize._engine.capabilities.state_store import StateStore

        store = StateStore()
        for key in ("fetch.rows", "fetch.ms", "fetchmeta.x", "report.rows"):
            store.set(key, 1)

        assert sorted(store.keys("fetch.")) == ["fetch.ms", "fetch.rows"]
        assert "fetchmeta.x" in store.keys("fetch"), (
            "if this ever stops being true, keys() has become a namespace "
            "lookup and the docstring's warning is now wrong"
        )

    def test_an_empty_prefix_returns_everything(self) -> None:
        from functualize._engine.capabilities.state_store import StateStore

        store = StateStore()
        store.set("a", 1)
        store.set("b.c", 2)
        assert sorted(store.keys()) == ["a", "b.c"]
