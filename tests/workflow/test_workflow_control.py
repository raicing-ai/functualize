"""The advance verb, and the funnel it must not bypass.

Before this, **nothing anywhere advanced a blocked walk** except re-invoking
the job process — which an agent over MCP cannot do. Every verb called `resume`
on every surface was a deposit.

Making `resume` advance turns the CLI into a second job-executing door. The MCP
adapter enforces its gate-tool policy at `_execute_job`, "the one place a
job-executing call cannot get past"; a CLI that called `app.execute` directly
would leave that policy as theatre. So every path goes through
`guarded_execute`, and these tests are what hold that.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app._workflow_control import guarded_execute
from functualize.app.core import FunctualizeApp
from functualize.app.utils import (
    GateToolPolicy,
    StateStore,
    advanceable_scopes,
    answer_gate,
    cancel_scope,
    purge_scopes,
    resolve_advanceable,
    resume_scope,
)
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow


class Approval(BaseModel):
    approved: bool


@pytest.fixture(autouse=True)
def _reset() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def calls() -> list[str]:
    return []


@pytest.fixture
def app(project: Path, calls: list[str]) -> FunctualizeApp:
    instance = FunctualizeApp(name="testapp")

    def build() -> str:
        calls.append("build")
        return "artifact"

    def deploy() -> str:
        calls.append("deploy")
        return "deployed"

    @workflow(
        steps=[Step("build"), Gate(name="approve", awaits=Approval), Step("deploy")],
        edges=[
            Edge(source="build", target="approve"),
            Edge(source="approve", target="deploy"),
            Edge(source="deploy", target=END),
        ],
    )
    def release() -> str:
        calls.append("body")
        return "shipped"

    instance.register_dynamic_job("build", build)
    instance.register_dynamic_job("deploy", deploy)
    instance.register_dynamic_job("release", release)
    return instance


@pytest.fixture
def store(app: FunctualizeApp, project: Path, calls: list[str]) -> StateStore:
    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="rel-1")
    )
    calls.clear()
    return StateStore.for_project(project)


class TestResumeAdvances:
    """AC-16. The verb this whole feature exists for."""

    def test_an_answered_scope_walks_to_completion(
        self, app: FunctualizeApp, store: StateStore, calls: list[str]
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})

        result = resume_scope(app, store, "rel-1")

        assert result["status"] == "success"
        assert calls == ["deploy", "body"], "a step that had not run, ran"

    def test_it_can_answer_and_advance_in_one_call(
        self, app: FunctualizeApp, store: StateStore, calls: list[str]
    ) -> None:
        """The fusion that makes `--wf-resume --wf-input` worth having."""
        result = resume_scope(app, store, "rel-1", input={"approved": True})

        assert result["status"] == "success"
        assert calls == ["deploy", "body"]

    def test_a_fused_answer_goes_through_the_same_validation(
        self, app: FunctualizeApp, store: StateStore, calls: list[str]
    ) -> None:
        result = resume_scope(app, store, "rel-1", input={"approved": "nope"})

        assert result["status"] == "drafted"
        assert calls == [], "it walked on input the gate had not accepted"

    def test_an_incomplete_answer_does_not_advance_and_says_so(
        self, app: FunctualizeApp, store: StateStore, calls: list[str]
    ) -> None:
        """Advancing on a still-blocked gate would return the caller exactly
        where they started, with no explanation."""
        result = resume_scope(app, store, "rel-1", input={})

        assert result["status"] == "drafted"
        assert "not advanced" in result["message"]
        assert calls == []

    def test_a_completed_step_is_not_re_run(
        self, app: FunctualizeApp, store: StateStore, calls: list[str]
    ) -> None:
        resume_scope(app, store, "rel-1", input={"approved": True})
        assert "build" not in calls

    def test_it_carries_the_projection(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        result = resume_scope(app, store, "rel-1", input={"approved": True})
        assert result["scope"]["state"] == "completed"

    def test_an_unknown_scope_errors(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        assert resume_scope(app, store, "nope")["error"] == "workflow_not_found"

    def test_a_cancelled_scope_refuses(
        self, app: FunctualizeApp, store: StateStore, calls: list[str]
    ) -> None:
        """AC-5. Terminal means terminal."""
        cancel_scope(store, "rel-1")

        result = resume_scope(app, store, "rel-1")

        assert result["error"] == "scope_cancelled"
        assert calls == []


class TestRetryEpilogue:
    def test_it_clears_a_recorded_epilogue_so_the_body_runs_again(
        self, app: FunctualizeApp, store: StateStore, calls: list[str]
    ) -> None:
        """The sticky-body case: a walk that reached END and whose body then
        failed is `completed` with a failed epilogue, and without this it can
        never run again. Failed *steps* need no equivalent — they already
        re-run on resume."""
        resume_scope(app, store, "rel-1", input={"approved": True})
        assert calls == ["deploy", "body"]
        calls.clear()

        # Without the flag, the recorded epilogue holds.
        resume_scope(app, store, "rel-1")
        assert "body" not in calls

        resume_scope(app, store, "rel-1", retry_epilogue=True)
        assert "body" in calls


class TestAmbiguityNeverGuesses:
    """AC-17, AC-18."""

    def test_exactly_one_advanceable_scope_is_used(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        assert resolve_advanceable(store, None, "release") == "rel-1"

    def test_several_are_listed_never_picked(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """Never "newest wins" — `blocked_at` resets on every re-block, so
        recency is not computable even if it were wanted."""
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-2"
            )
        )

        result = resolve_advanceable(store, None, "release")

        assert result["error"] == "ambiguous_scope"
        assert sorted(result["candidates"]) == ["rel-1", "rel-2"]

    def test_none_names_the_survey_verb(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        cancel_scope(store, "rel-1")
        result = resolve_advanceable(store, None, "release")
        assert result["error"] == "no_advanceable_scope"
        assert "workflow list" in result["message"]

    def test_an_unknown_id_errors_rather_than_creating_a_scope(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """The phantom-run defect: `--scope-id <typo>` silently started a new
        run under the typo'd id, because the runner does
        `scope_id or new_scope_id()` and the walk calls `ensure_scope`."""
        result = resolve_advanceable(store, "typo-id", "release")

        assert result["error"] == "workflow_not_found"
        assert "typo-id" not in store.scope_ids()

    def test_it_filters_by_workflow(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        store.ensure_scope("other-1", "something-else")
        assert advanceable_scopes(store, "release") == ["rel-1"]


class TestTheFunnelCannotBeBypassed:
    """The reason `guarded_execute` exists. `_gate_refusal`'s own comment: an
    agent refused `deploy` as a tool just calls `run_job("deploy")` and the
    gate policy is theatre."""

    def test_resume_is_never_refused_by_the_gate_policy(
        self, app: FunctualizeApp, store: StateStore, calls: list[str]
    ) -> None:
        """The workflow's own continuation is exempt, deliberately.

        The allow-list is built from the *gate's* `tools`, so a gate declaring
        `tools=["build"]` would refuse `release` — and the walk that is the only
        way out of the block could never run. Found by writing the test: an
        earlier cut passed the policy here and every gate that declared a tool
        made its own workflow unresumable.

        `GateToolPolicy` has always stated this rule for the read tools, for
        the same reason: an actor that could not inspect, answer or continue
        the gate blocking it would have no way out at all.
        """
        result = resume_scope(app, store, "rel-1", input={"approved": True})

        assert result["status"] == "success"
        assert calls == ["deploy", "body"]

    def test_a_gate_declaring_tools_does_not_block_its_own_resume(
        self, project: Path, calls: list[str]
    ) -> None:
        """The exact shape that failed: the gate names a tool, so the union
        allow-list is {that tool} and the workflow is not in it."""
        instance = FunctualizeApp(name="toolapp")

        def build() -> str:
            calls.append("build")
            return "artifact"

        def deploy() -> str:
            calls.append("deploy")
            return "deployed"

        @workflow(
            steps=[
                Step("build"),
                Gate(name="approve", awaits=Approval, tools=["build"]),
                Step("deploy"),
            ],
            edges=[
                Edge(source="build", target="approve"),
                Edge(source="approve", target="deploy"),
                Edge(source="deploy", target=END),
            ],
        )
        def gated() -> str:
            calls.append("body")
            return "shipped"

        instance.register_dynamic_job("build", build)
        instance.register_dynamic_job("deploy", deploy)
        instance.register_dynamic_job("gated", gated)

        instance.execute(
            RunRequest(job_name="gated", surface="app.execute", workflow_scope_id="g-1")
        )
        gated_store = StateStore.for_project(project)
        calls.clear()

        result = resume_scope(instance, gated_store, "g-1", input={"approved": True})

        assert result["status"] == "success"
        assert calls == ["deploy", "body"]

    def test_a_gate_tool_call_is_governed(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """What the policy is actually for: an actor running *other* jobs while
        a gate waits."""
        from functualize.app.utils import call_gate_tool

        class RefuseEverything(GateToolPolicy):
            def permitted(self, tool_name: str) -> bool:
                return False

            def allowed_tools(self) -> set[str]:
                return set()

        result = call_gate_tool(
            app,
            store,
            "rel-1",
            "build",
            policy=RefuseEverything(app, store=store),
        )
        assert result["error"] == "tool_not_permitted"

    def test_a_refusal_is_raised_not_returned_from_guarded_execute(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """So a caller that forgot to handle it fails loudly rather than
        running the job anyway."""

        class RefuseEverything(GateToolPolicy):
            def permitted(self, tool_name: str) -> bool:
                return False

            def allowed_tools(self) -> set[str]:
                return set()

        with pytest.raises(PermissionError):
            guarded_execute(
                app,
                store,
                "release",
                scope_id="rel-1",
                policy=RefuseEverything(app, store=store),
            )

    def test_no_policy_means_no_restriction(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """Direct callers with no workflow state to consult must still work."""
        assert guarded_execute(app, store, "build", policy=None) is not None


class TestPurge:
    def test_it_removes_finished_scopes(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        resume_scope(app, store, "rel-1", input={"approved": True})

        result = purge_scopes(store)

        assert result["removed"] == ["rel-1"]
        assert store.scope_ids() == []

    def test_it_refuses_to_touch_a_live_scope(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """A hard delete with no backup, unlike `state clear --scopes` which
        moves the whole file aside. A mistyped filter must not be able to
        destroy a run somebody is waiting on."""
        assert purge_scopes(store)["removed"] == []
        assert store.scope_ids() == ["rel-1"]

    def test_a_live_state_cannot_even_be_named(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        result = purge_scopes(store, state="waiting")
        assert result["error"] == "invalid_state"

    def test_it_filters_by_state(self, app: FunctualizeApp, store: StateStore) -> None:
        resume_scope(app, store, "rel-1", input={"approved": True})
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-2"
            )
        )
        cancel_scope(store, "rel-2")

        assert purge_scopes(store, state="cancelled")["removed"] == ["rel-2"]
        assert store.scope_ids() == ["rel-1"]

    def test_a_scope_with_no_timestamps_is_never_aged_out(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """It cannot be aged, and treating it as infinitely old would purge
        exactly the records whose history is least known."""
        store.ensure_scope("bare", "release")
        store.set_scope_status("bare", "completed")

        assert purge_scopes(store, older_than_days=0)["removed"] == []

    def test_a_recent_scope_survives_an_age_filter(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        resume_scope(app, store, "rel-1", input={"approved": True})
        assert purge_scopes(store, older_than_days=7)["removed"] == []


class TestTheControlVerbsNameTheirDoor:
    """`guarded_execute` stamped every run `app.execute` — rre F9.

    `func builtin workflow resume`, an MCP workflow tool, and a plain
    `request_for` call all reached `guarded_execute`, which hardcoded
    `surface="app.execute"`. So the three were **indistinguishable in the one
    field whose entire purpose is telling them apart**, and `RunRequest`'s own
    docstring says a door must name itself.

    `func.builtin` came back to the surface vocabulary to make this sayable. It
    had been deleted on 2026-09-10 as "a label nothing can produce", and the
    deletion recorded the condition for its return: *"if a later door needs
    one, it comes back together with the code that produces it."* This is that
    code.

    The default stays `app.execute`, because a caller that says nothing about
    its door genuinely **is** a programmatic one — which is also what every
    test in this file is.
    """

    def test_the_cli_resume_says_it_came_from_func_builtin(
        self, app: FunctualizeApp, store: StateStore, calls: list[str]
    ) -> None:
        captured: list[Any] = []
        original = app.execute

        def _spy(request: Any, **kw: Any) -> Any:
            captured.append(request)
            return original(request, **kw)

        app.execute = _spy  # type: ignore[method-assign]
        answer_gate(app, store, "rel-1", "approve", {"approved": True})

        resume_scope(app, store, "rel-1", surface="func.builtin")

        assert captured, "the resume never reached the engine"
        assert captured[0].surface == "func.builtin"

    def test_a_programmatic_resume_still_says_app_execute(
        self, app: FunctualizeApp, store: StateStore, calls: list[str]
    ) -> None:
        """The falsifier: the default must not have become the CLI's door."""
        captured: list[Any] = []
        original = app.execute

        def _spy(request: Any, **kw: Any) -> Any:
            captured.append(request)
            return original(request, **kw)

        app.execute = _spy  # type: ignore[method-assign]
        answer_gate(app, store, "rel-1", "approve", {"approved": True})

        resume_scope(app, store, "rel-1")

        assert captured and captured[0].surface == "app.execute"

    def test_the_returned_door_is_a_declared_one(self) -> None:
        """`func.builtin` is back in the vocabulary *and* in the policy table.

        A surface added to the `Literal` and not to `SURFACE_POLICY` raises on
        its first run; one added to neither is a `RunRequest` validation error.
        Either way the door has to be declared before it can be used.
        """
        from functualize._types.run_request import RUN_SURFACES, SURFACE_POLICY

        assert "func.builtin" in RUN_SURFACES
        assert "func.builtin" in SURFACE_POLICY
        assert SURFACE_POLICY["func.builtin"].owns_stdin is False, (
            "a control verb must not resolve Stdin markers — `func builtin "
            "workflow resume` would read the user's terminal"
        )
