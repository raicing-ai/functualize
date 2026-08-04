"""The whole agent-driven loop, end to end (§A.7, §D.7, contracts §4).

Each of the pieces has its own tests. This file asserts the one thing none of
them can: that an agent holding *only* MCP tools and a scope id can take a
workflow from blocked to finished, using nothing it was not told by a previous
call in the same sequence.

The loop under test:

    run → BLOCKED → list_active_workflows → get_workflow_state
        → resume_gate(bad input) → rejected, still blocked
        → resume_gate(good input) → accepted
        → run again → SUCCESS

The discovery half matters as much as the resume half. An agent that has to be
told the gate name or its schema out of band is not driving the workflow — the
graph is. So the test threads values forward: the gate name it deposits into
comes from `list_active_workflows`, and the payload it builds comes from the
JSON schema `get_workflow_state` returned.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from functualize_mcp._workflow_tools import WorkflowToolProvider
from pydantic import BaseModel, Field

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.app.utils import StateStore
from functualize.job import RunStatus
from functualize.workflow import END, Edge, Gate, Step, workflow

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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


class Deployment(BaseModel):
    """What the gate needs before the release can proceed."""

    environment: str = Field(description="Target environment")
    replicas: int = Field(description="Replica count")
    notes: str = "none"


@pytest.fixture
def app() -> FunctualizeApp:
    instance = FunctualizeApp(name="release")
    ran: list[str] = []

    def build() -> str:
        ran.append("build")
        return "artifact-1"

    def deploy() -> str:
        ran.append("deploy")
        return "deployed"

    @workflow(
        steps=[
            Step("build"),
            Gate(name="approval", awaits=Deployment, tools=["build"]),
            Step("deploy"),
        ],
        edges=[
            Edge(source="build", target="approval"),
            Edge(source="approval", target="deploy"),
            Edge(source="deploy", target=END),
        ],
    )
    def release() -> str:
        ran.append("body")
        return "release complete"

    instance.register_dynamic_job("build", build)
    instance.register_dynamic_job("deploy", deploy)
    instance.register_dynamic_job("release", release)
    instance.ran = ran  # type: ignore[attr-defined]
    return instance


def _provider(app: FunctualizeApp) -> WorkflowToolProvider:
    return WorkflowToolProvider(app, store=StateStore.for_project(Path.cwd()))


async def test_an_agent_can_drive_a_blocked_workflow_to_completion(
    app: FunctualizeApp,
) -> None:
    tools = _provider(app)

    # 1. A run blocks. This is the only thing the agent is told out of band.
    blocked = app.execute("release", scope_id="rel-1")
    assert blocked.status is RunStatus.BLOCKED
    assert app.ran == ["build"]  # type: ignore[attr-defined]

    # 2. The agent finds the work without being handed a scope id.
    active = await tools._list_active_workflows()
    assert [w["workflow_id"] for w in active["workflows"]] == ["rel-1"]
    workflow_id = active["workflows"][0]["workflow_id"]

    # 3. It inspects the scope and learns the gate name and the graph.
    state = await tools._get_workflow_state(workflow_id)
    assert state["status"] == "blocked"
    assert state["current_position"] == "approval"
    # The agent learns what `build` produced, not merely that it ran — the
    # difference between driving the workflow and being told about it.
    assert state["results"]["build"]["return_value"] == "artifact-1"
    assert state["steps"] == [
        {"step": "build"},
        {"gate": "approval", "model": "Deployment"},
        {"step": "deploy"},
    ]

    gate_name = state["pending_gates"][0]["gate"]
    schema = state["pending_gates"][0]["input_schema"]
    required = state["pending_gates"][0]["unresolved_fields"]
    assert sorted(required) == ["environment", "replicas"]
    assert [t["tool"] for t in state["pending_gates"][0]["tools"]] == ["build"]

    # 4. A wrong guess is rejected and changes nothing.
    rejected = await tools._resume_gate(gate_name, {"environment": "prod"})
    assert rejected["error"] == "validation_error"
    still_blocked = await tools._get_workflow_state(workflow_id)
    assert still_blocked["status"] == "blocked"
    assert still_blocked["pending_gates"][0]["gate"] == gate_name

    # 5. Input built from the published schema is accepted.
    payload = {name: _example_for(schema, name) for name in required}
    accepted = await tools._resume_gate(gate_name, payload)
    assert accepted["status"] == "input_accepted"
    assert accepted["workflow_id"] == workflow_id

    # Accepting input runs nothing — the walk has not moved.
    assert app.ran == ["build"]  # type: ignore[attr-defined]

    # 6. Re-running the job replays the walk and finishes it.
    done = app.execute("release", scope_id=workflow_id)
    assert done.status is RunStatus.SUCCESS
    assert done.return_value == "release complete"
    # `build` is memoized for this scope; only the rest runs.
    assert app.ran == ["build", "deploy", "body"]  # type: ignore[attr-defined]

    # 7. The finished scope drops out of the agent's work queue.
    after = await tools._list_active_workflows()
    assert after["workflows"] == []


async def test_a_cancelled_workflow_leaves_the_loop(app: FunctualizeApp) -> None:
    """The escape hatch: an agent that cannot answer a gate can abandon it,
    and the scope stops appearing as outstanding work."""
    tools = _provider(app)
    app.execute("release", scope_id="rel-1")

    cancelled = await tools._cancel_workflow("rel-1")
    assert cancelled["status"] == "cancelled"

    assert (await tools._list_active_workflows())["workflows"] == []
    # And the gate can no longer be answered.
    assert (await tools._resume_gate("approval", {}))["error"] == "gate_not_found"


async def test_two_blocked_runs_are_driven_independently(
    app: FunctualizeApp,
) -> None:
    """Scope-addressed resume is what makes concurrent runs safe: answering
    one must not advance the other."""
    tools = _provider(app)
    app.execute("release", scope_id="rel-1")
    app.execute("release", scope_id="rel-2")

    # The gate name alone is ambiguous across two scopes.
    ambiguous = await tools._resume_gate(
        "approval", {"environment": "prod", "replicas": 3}
    )
    assert ambiguous["error"] == "ambiguous_gate"

    # Naming the scope resolves it.
    accepted = await tools._resume_workflow(
        "rel-2", {"environment": "prod", "replicas": 3}
    )
    assert accepted["status"] == "input_accepted"

    assert app.execute("release", scope_id="rel-2").status is RunStatus.SUCCESS
    assert app.execute("release", scope_id="rel-1").status is RunStatus.BLOCKED


def _example_for(schema: dict, field: str) -> object:
    """Build a plausible value for a field from its published JSON schema.

    Deliberately schema-driven rather than hardcoded: it is what an agent has
    to do, and it fails loudly if the published schema stops describing the
    model the gate actually validates against.
    """
    spec = schema["properties"][field]
    return {"string": "prod", "integer": 3, "number": 1.0, "boolean": True}[
        spec["type"]
    ]
