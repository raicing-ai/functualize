"""`Gate.tools` as a permission, enforced at MCP dispatch.

Ratified 2026-07-20 (resolved question 14). `Gate(name, awaits, tools)` names
what an agent may use while resolving that gate, and a job tool call arriving
while the gate waits is refused unless the job is named.

Enforcement sits in `_execute_job`, the single point every per-job tool funnels
through. The predecessor to this was a `validate_tool_call` helper that tools
were expected to call themselves; it had no callers, and a check a caller can
skip by not calling it is not a permission. So the tests here drive the real
dispatch path rather than the policy object alone — the policy being correct
and the policy being *consulted* are different claims.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from functualize_mcp._server import _execute_job
from functualize_mcp._workflow_tools import GateToolPolicy, WorkflowToolProvider
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.app.utils import StateStore
from functualize.workflow import END, Edge, Gate, Step, workflow


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


class Approval(BaseModel):
    approved: bool


def _store() -> StateStore:
    return StateStore.for_project(Path.cwd())


def _app(tools: list[str] | None, *, name: str = "release") -> FunctualizeApp:
    """An app whose workflow blocks at a gate declaring ``tools``."""
    app = FunctualizeApp(name="gatepolicy")
    ran: list[str] = []

    def build() -> str:
        ran.append("build")
        return "artifact"

    def deploy() -> str:
        ran.append("deploy")
        return "deployed"

    def unrelated() -> str:
        ran.append("unrelated")
        return "did a thing"

    @workflow(
        steps=[
            Step("build"),
            Gate(name="approval", awaits=Approval, tools=tools or []),
            Step("deploy"),
        ],
        edges=[
            Edge(source="build", target="approval"),
            Edge(source="approval", target="deploy"),
            Edge(source="deploy", target=END),
        ],
    )
    def release() -> str:
        return "released"

    app.register_dynamic_job("build", build)
    app.register_dynamic_job("deploy", deploy)
    app.register_dynamic_job("unrelated", unrelated)
    app.register_dynamic_job(name, release)
    app.ran = ran  # type: ignore[attr-defined]
    return app


def _policy(app: FunctualizeApp) -> GateToolPolicy:
    return GateToolPolicy(app, store=_store())


class TestNoRestriction:
    def test_nothing_is_restricted_with_no_blocked_gate(self) -> None:
        app = _app(["build"])
        assert _policy(app).allowed_tools() is None
        assert _policy(app).permitted("anything")

    def test_a_gate_declaring_no_tools_restricts_nothing(self) -> None:
        """The documented meaning of an empty list: no restriction. Reading it
        as "permit nothing" would make the common `Gate(name, awaits)` form
        freeze every tool the moment it blocked."""
        app = _app([])
        app.execute("release", scope_id="run-1")

        assert _policy(app).allowed_tools() is None
        assert _policy(app).permitted("unrelated")

    def test_a_resolved_gate_stops_restricting(self) -> None:
        app = _app(["build"])
        app.execute("release", scope_id="run-1")
        assert not _policy(app).permitted("unrelated")

        _store().deposit_gate_payload("run-1", "approval", {"approved": True})

        assert _policy(app).allowed_tools() is None

    def test_a_cancelled_scope_stops_restricting(self) -> None:
        """Otherwise an abandoned workflow would hold the toolset hostage."""
        app = _app(["build"])
        app.execute("release", scope_id="run-1")
        _store().set_scope_status("run-1", "cancelled")

        assert _policy(app).allowed_tools() is None


class TestRestriction:
    def test_a_listed_tool_is_permitted(self) -> None:
        app = _app(["build"])
        app.execute("release", scope_id="run-1")

        assert _policy(app).permitted("build")

    def test_an_unlisted_tool_is_refused(self) -> None:
        app = _app(["build"])
        app.execute("release", scope_id="run-1")

        assert not _policy(app).permitted("unrelated")

    def test_the_refusal_names_what_is_allowed(self) -> None:
        """A refusal that does not say what would work costs the agent a turn
        to discover by trial."""
        app = _app(["build", "deploy"])
        app.execute("release", scope_id="run-1")

        refusal = _policy(app).refusal("unrelated")

        assert refusal["error"] == "tool_not_permitted"
        assert refusal["allowed_tools"] == ["build", "deploy"]


class TestMultipleScopes:
    def test_two_restricted_gates_union_their_lists(self) -> None:
        """A tool call carries no scope id, so the policy cannot know which
        workflow it is for. Intersecting would let two unrelated workflows
        deadlock each other."""
        app = _app(["build"])
        app.execute("release", scope_id="run-1")

        store = _store()
        store.ensure_scope("run-2", "other")
        store.set_scope_status("run-2", "blocked")
        store.put_gate(
            "run-2",
            "sign_off",
            {
                "model": "Approval",
                "input_schema": {},
                "tools": ["deploy"],
                "payload": None,
                "blocked_at": "",
            },
        )

        assert _policy(app).allowed_tools() == {"build", "deploy"}

    def test_one_unrestricted_gate_lifts_the_restriction(self) -> None:
        """A gate that declares no tools is not asking for a restriction, so
        it must not be silently tightened by an unrelated workflow's list."""
        app = _app(["build"])
        app.execute("release", scope_id="run-1")

        store = _store()
        store.ensure_scope("run-2", "other")
        store.set_scope_status("run-2", "blocked")
        store.put_gate(
            "run-2",
            "sign_off",
            {
                "model": "Approval",
                "input_schema": {},
                "tools": [],
                "payload": None,
                "blocked_at": "",
            },
        )

        assert _policy(app).allowed_tools() is None


class TestDispatchEnforcement:
    """The claim the policy object alone cannot support: dispatch consults it."""

    def test_dispatch_refuses_an_unlisted_job(self) -> None:
        app = _app(["build"])
        app.execute("release", scope_id="run-1")
        app.ran.clear()  # type: ignore[attr-defined]

        result = _execute_job(app, "unrelated", {}, _policy(app))

        assert result["error"] == "tool_not_permitted"
        assert app.ran == []  # type: ignore[attr-defined]

    def test_dispatch_runs_a_listed_job(self) -> None:
        app = _app(["unrelated"])
        app.execute("release", scope_id="run-1")
        app.ran.clear()  # type: ignore[attr-defined]

        result = _execute_job(app, "unrelated", {}, _policy(app))

        assert result["return_value"] == "did a thing"
        assert app.ran == ["unrelated"]  # type: ignore[attr-defined]

    def test_dispatch_without_a_policy_enforces_nothing(self) -> None:
        """Direct callers with no workflow state to consult are unaffected."""
        app = _app(["build"])
        app.execute("release", scope_id="run-1")
        app.ran.clear()  # type: ignore[attr-defined]

        assert _execute_job(app, "unrelated", {})["return_value"] == "did a thing"


class TestWorkflowToolsAreNeverRefused:
    def test_the_agent_can_still_answer_the_gate_that_blocks_it(self) -> None:
        """Load-bearing: the workflow tools do not route through dispatch, so
        a gate cannot lock an agent out of resolving that same gate. Without
        this the restriction would be a deadlock, not a permission.
        """
        app = _app(["nothing_useful"])
        app.execute("release", scope_id="run-1")
        tools = WorkflowToolProvider(app, store=_store())

        # Refused at dispatch...
        assert not _policy(app).permitted("deploy")

        # ...yet the way out is still open.
        import asyncio

        state = asyncio.run(tools._get_workflow_state("run-1"))
        assert state["pending_gates"][0]["gate"] == "approval"

        accepted = asyncio.run(tools._resume_gate("approval", {"approved": True}))
        assert accepted["status"] == "input_accepted"

        # And resolving it lifts the restriction.
        assert _policy(app).allowed_tools() is None
