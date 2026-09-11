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
from functualize._engine.capabilities.prompt import Prompt  # noqa: TC001
from functualize._engine.capabilities.state import State  # noqa: TC001
from functualize._events.perf import perf_timeline
from functualize._types.run_request import RunRequest


@pytest.fixture
def state(tmp_path: Any) -> Any:
    """A real `State`, over a real ``scopes.json``.

    No in-memory double. A double standing in for the production collaborator
    at the seam under test is exactly how `Perf` shipped unwired for its whole
    life, and a test pays little for the real thing: 0.557 ms per unbatched
    `set` on an empty store. That is an **empty-store** figure, worth naming as
    such — it was once used to defend the design itself, and on a real 1 MB
    `scopes.json` the same `set` costs 58 ms
    (`.spec/features/scope-record-lifecycle/`).
    """
    from functualize._engine.capabilities.state import ScopeBackedStateStore, State
    from functualize._primitives.scope_store import ScopeStore

    return State(ScopeBackedStateStore(ScopeStore(tmp_path / "scopes.json"), "s"))


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
            seen["pattern filter"] = rc.state.keys("fetch.*")
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
        assert seen["pattern filter"] == ["fetch.rows"]

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


class TestKeysMatchesByGlob:
    """`keys(pattern)` is a glob, and `*` stops at a `.`.

    A bare prefix is a `startswith`, so `"fetch"` silently picks up
    `"fetchmeta.x"` — a *different* job's namespace. That is bad enough on its
    own; requiring a trailing dot to avoid it is worse, because the dot looks
    like a typo rather than a rule. The pattern form says what it means.
    """

    def _store(self, state: Any) -> Any:
        with state.batch():
            for key in ("fetch.rows", "fetch.ms", "fetchmeta.x", "fetch.io.bytes"):
                state.set(key, 1)
        return state

    def test_one_star_does_not_cross_the_separator(self, state: Any) -> None:
        assert sorted(self._store(state).keys("fetch.*")) == ["fetch.ms", "fetch.rows"]

    def test_one_star_cannot_reach_the_neighbouring_namespace(self, state: Any) -> None:
        """The whole reason for preferring the pattern over a prefix."""
        assert "fetchmeta.x" not in self._store(state).keys("fetch.*")

    def test_two_stars_cross_the_separator(self, state: Any) -> None:
        assert "fetch.io.bytes" in self._store(state).keys("fetch.**")

    def test_a_pattern_can_match_a_leaf_across_namespaces(self, state: Any) -> None:
        store = self._store(state)
        store.set("report.rows", 1)
        assert sorted(store.keys("*.rows")) == ["fetch.rows", "report.rows"]

    def test_the_matcher_is_the_one_the_event_bus_uses(self, state: Any) -> None:
        """One glob implementation, not two that agree today (ADR-021).

        `rc.events.on_event("job.*")` and perf-phase filtering already call
        this function; a second copy is the divergence this whole feature
        exists to remove.
        """
        from functualize._events._pattern_matcher import matches_pattern

        store = self._store(state)
        # SIM118 reads `store.keys()` as a dict call and would have us drop
        # it. `StateStore` is not a dict and defines no `__iter__`, so the
        # suggested fix raises TypeError.
        every_key = store.keys()  # noqa: SIM118
        assert sorted(store.keys("fetch.*")) == sorted(
            k for k in every_key if matches_pattern(k, "fetch.*")
        )

    def test_an_empty_pattern_returns_everything(self, state: Any) -> None:
        state.set("a", 1)
        state.set("b.c", 2)
        assert sorted(state.keys()) == ["a", "b.c"]


class TestStateIsDurable:
    """State survives the process. The in-memory store never could.

    `WorkflowScope` held the old store and `app._scope_registry` holds the
    scopes, and that registry is reset to `{}` at boot — so a workflow that
    blocked at a gate and resumed *in a new process* came back with its step
    records intact (those live in `scopes.json`) and its state silently empty.
    State was the one thing that did not survive, which is the least defensible
    split available, and it is why there is no in-memory tier now.
    """

    def test_a_value_written_in_one_process_is_read_in_the_next(
        self, tmp_path: Any
    ) -> None:
        import subprocess
        import sys
        import textwrap

        (tmp_path / ".functualize").mkdir()
        program = tmp_path / "prog.py"
        program.write_text(
            textwrap.dedent("""
                import sys
                from functualize import FunctualizeApp, RunContext
                from functualize._types.run_request import RunRequest

                app = FunctualizeApp(name="probe")

                def writer(rc: RunContext) -> str:
                    rc.state.set("fetch.rows", 500)
                    return "ok"

                def reader(rc: RunContext) -> str:
                    print("READ:", rc.state.get("fetch.rows"))
                    return "ok"

                app.register_dynamic_job("writer", writer)
                app.register_dynamic_job("reader", reader)
                app.execute(RunRequest(
                    job_name=sys.argv[1],
                    surface="app.execute",
                    workflow_scope_id="shared-scope",
                ))
            """)
        )

        def run(job: str) -> str:
            done = subprocess.run(
                [sys.executable, str(program), job],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                check=False,
            )
            assert done.returncode == 0, done.stderr[-800:]
            return done.stdout

        run("writer")
        assert "READ: 500" in run("reader"), (
            "a second process did not see the first one's write — state is "
            "back to being per-process, which is the defect this replaced"
        )
        assert (tmp_path / ".functualize" / "scopes.json").exists()

    def test_state_without_a_scope_says_so_instead_of_pretending(self) -> None:
        """No silent in-memory stand-in — an error naming the cause.

        A stand-in would accept writes nothing will ever read, which is the
        failure mode being removed rather than relocated.
        """
        from functualize._engine.capabilities.state import (
            State,
            StateUnavailableError,
        )

        with pytest.raises(StateUnavailableError, match="outside a run"):
            State(None).set("k", "v")


class TestSubscriptAccessFindsCapabilities:
    """`rc[T]` and `T in rc` see what the job is holding.

    Both consulted only the DI registry, where a per-invocation capability
    never appears — so `rc[Log]` raised `MissingProviderError` and `Log in rc`
    was False while a `log: Log` parameter had the object in hand. That is the
    duality rule broken on the one accessor that is generic over every
    capability (ADR-021).
    """

    def _seen(self) -> dict[str, Any]:
        app = FunctualizeApp(name="subscript")
        seen: dict[str, Any] = {}

        def j(rc: RunContext, log: Log, state: State) -> str:
            seen["rc[Log] is log"] = rc[Log] is log
            seen["Log in rc"] = Log in rc
            seen["rc[State] is state"] = rc[State] is state
            seen["State in rc"] = State in rc
            return "ok"

        app.register_dynamic_job("j", j)
        assert _run(app, "j").status.value == "Success"
        return seen

    def test_a_held_capability_is_found_by_subscript(self) -> None:
        seen = self._seen()
        assert seen["rc[Log] is log"] is True
        assert seen["rc[State] is state"] is True

    def test_a_held_capability_reports_as_present(self) -> None:
        seen = self._seen()
        assert seen["Log in rc"] is True
        assert seen["State in rc"] is True

    def test_an_unheld_type_still_reports_absent(self) -> None:
        """The lookup must not become "yes" for everything.

        Without this the previous two tests pass on a `__contains__` that
        returns True unconditionally.
        """
        app = FunctualizeApp(name="subscript")
        seen: dict[str, Any] = {}

        class NotRegistered:
            pass

        def j(rc: RunContext) -> str:
            seen["absent"] = NotRegistered in rc
            return "ok"

        app.register_dynamic_job("j", j)
        assert _run(app, "j").status.value == "Success"
        assert seen["absent"] is False

    def test_a_job_that_never_asked_does_not_get_one(self) -> None:
        """The map holds what the job declared, not every capability.

        `_cap_or_none` never constructs — `Sources` and `Freshness` are
        injected empty and completed after the pre-flight decision, so a
        resolver that helpfully built one would hand back an empty map with no
        error.
        """
        from functualize._engine.capabilities.sources import Sources

        app = FunctualizeApp(name="subscript")
        seen: dict[str, Any] = {}

        def j(rc: RunContext) -> str:
            seen["sources"] = Sources in rc
            return "ok"

        app.register_dynamic_job("j", j)
        assert _run(app, "j").status.value == "Success"
        assert seen["sources"] is False


class TestTheDualityRuleIsEnforcedByTheRegistry:
    """The rule, parametrized over `CAPABILITY_SPECS` rather than a list here.

    **This is the difference between a rule and a habit.** The Constitution and
    `contributor/guides/wiring-discipline.md` both stated the duality rule in
    prose for the project's whole life, and five of six capabilities violated
    it anyway — because "every user-declarable capability has an end-to-end
    test" was read as *decorator* declarations, and because nothing enumerated
    the capabilities to check coverage against.

    Driving off the registry (ADR-014) fixes exactly that: a capability added
    tomorrow is covered the day its `CapabilitySpec` is written, and a
    capability that legitimately cannot share declares `shared_with_rc=False`
    where a reader can see it — rather than being quietly absent from a
    hand-written list.
    """

    def _specs(self) -> list[Any]:
        from functualize._engine.capabilities.registry import CAPABILITY_SPECS

        return [
            spec
            for spec in CAPABILITY_SPECS
            if spec.rc_accessor is not None and spec.type is not None
        ]

    def test_at_least_one_capability_declares_an_accessor(self) -> None:
        """Guards the parametrized test below against passing vacuously.

        If `rc_accessor` were never set, every test here would iterate an empty
        list and report success — which is the shape of a test that enforces
        nothing.
        """
        assert self._specs(), (
            "no capability declares rc_accessor; the duality check below would "
            "be iterating nothing"
        )

    def test_every_declared_accessor_reaches_the_injected_object(self) -> None:
        """`rc.<accessor>` is the object the DI parameter got — for all of them."""
        app = FunctualizeApp(name="registry")
        specs = self._specs()
        seen: dict[str, bool] = {}

        def j(
            rc: RunContext, log: Log, state: State, inv: Invoke, prompt: Prompt
        ) -> str:
            injected = {Log: log, State: state, Invoke: inv, Prompt: prompt}
            for spec in specs:
                if not spec.shared_with_rc:
                    continue
                target: Any = rc
                for part in spec.rc_accessor.split("."):
                    target = getattr(target, part)
                if callable(target) and not hasattr(target, "__self__"):
                    pass
                reached = target() if callable(target) else target
                seen[spec.name] = reached is injected.get(spec.type)
            return "ok"

        app.register_dynamic_job("j", j)
        assert _run(app, "j").status.value == "Success"

        drifted = [name for name, same in seen.items() if not same]
        assert not drifted, (
            f"{drifted} reached a different object through rc than through DI — "
            "the two doors have drifted (ADR-021)"
        )
        assert set(seen) == {s.name for s in specs if s.shared_with_rc}

    def test_an_exemption_is_declared_rather_than_implied(self) -> None:
        """A capability that cannot share says so on its spec.

        `shared_with_rc=False` is the only way out of the check above. That
        keeps an exemption visible in the registry instead of implied by an
        omission — ADR-021 lists the five classes that qualify and the
        one-sentence test for whether something really is one.
        """
        from functualize._engine.capabilities.registry import CAPABILITY_SPECS

        exempt = [s.name for s in CAPABILITY_SPECS if not s.shared_with_rc]
        assert exempt == [], (
            f"{exempt} declare an exemption from the duality rule; that is "
            "allowed, but ADR-021 requires a recorded reason — update this "
            "test with it when one is added"
        )


class TestAnInjectedPromptCanActuallyPrompt:
    """The `prompt: Prompt` door reaches the live collector (T11).

    Identity is not enough here. Before this task the two doors were two
    classes, and the injected one was **inert** — its registry factory was
    ``lambda ctx: Prompt()``, so ``_provider`` was ``None`` forever and every
    call raised `InputNotAvailable` while ``rc.prompts`` answered from the same
    registered surface. An identity check alone would have gone on passing if
    someone reconnected the two objects without reconnecting the collector, so
    this asserts the *answer*, through a collector that records being called.
    """

    class _Recorder:
        """A headless surface that can collect — the minimum a prompt needs."""

        needs_terminal = False

        def __init__(self, answer: Any) -> None:
            self.answer = answer
            self.asked: list[str] = []

        def collect(self, request: Any) -> Any:
            from functualize._types.interactivity import PromptResponse

            self.asked.append(request.question)
            return PromptResponse(value=self.answer, source="recorder")

    def test_both_doors_reach_the_registered_collector(self) -> None:
        app = FunctualizeApp(name="prompting")
        recorder = self._Recorder(True)
        app._surfaces.append(recorder)
        answers: dict[str, Any] = {}

        def j(rc: RunContext, prompt: Prompt) -> str:
            answers["rc"] = rc.prompts.confirm("through rc?")
            answers["di"] = prompt.confirm("through di?")
            return "ok"

        app.register_dynamic_job("j", j)
        assert _run(app, "j").status.value == "Success"

        assert answers == {"rc": True, "di": True}
        assert recorder.asked == ["through rc?", "through di?"], (
            "the collector was not consulted by both doors — one of them "
            "answered from somewhere else"
        )

    def test_a_collector_pushed_after_di_resolution_still_answers(self) -> None:
        """Resolution is per call, not per construction.

        DI runs before the orchestrator pushes anything, so a `Prompt` that
        bound its collector at construction would miss the surface that owns
        the terminal — which is the usual case, not an edge one.
        """
        app = FunctualizeApp(name="late-push")
        late = self._Recorder("blue")
        seen: dict[str, Any] = {}

        def j(prompt: Prompt) -> str:
            # Nothing could collect when `prompt` was built.
            app._surfaces.append(late)
            seen["answer"] = prompt.choice("colour?", ["red", "blue"])
            return "ok"

        app.register_dynamic_job("j", j)
        assert _run(app, "j").status.value == "Success"

        assert seen["answer"] == "blue"
        assert late.asked == ["colour?"]

    def test_asking_where_nothing_can_answer_raises_rather_than_defaults(
        self,
    ) -> None:
        """A required prompt with no collector is an error, not a `False`.

        Silently defaulting is how a non-interactive run appears to have been
        confirmed. This is the guarantee `rc.prompts` always had and the
        injected `Prompt` now shares.
        """
        from functualize._types.interactivity import InputNotAvailable

        app = FunctualizeApp(name="nobody-home")
        outcome: dict[str, Any] = {}

        def j(prompt: Prompt) -> str:
            try:
                prompt.confirm("destroy production?", destructive=True)
            except InputNotAvailable as exc:
                outcome["raised"] = str(exc)
            else:
                outcome["raised"] = None
            # An explicit default is the way to say what non-interactive means.
            outcome["defaulted"] = prompt.confirm("proceed?", default=False)
            return "ok"

        app.register_dynamic_job("j", j)
        assert _run(app, "j").status.value == "Success"

        assert outcome["raised"] is not None
        assert "destroy production?" in outcome["raised"]
        assert outcome["defaulted"] is False
