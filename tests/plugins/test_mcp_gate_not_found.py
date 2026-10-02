"""The MCP tools refuse an unknown gate with the gates that exist (T3).

The three gate-taking tools wear the unknown-gate guard under the
unreadable-store guard, so an agent that names a gate a workflow does not
have gets an envelope it can act on — the gate list — instead of a
traceback or a silent empty result. The raisers here are monkeypatched, the
standing transitional arrangement; the checkpoint task proves each arm
against the real raiser.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from functualize_mcp._workflow_tools import WorkflowToolProvider
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.app.utils import GateNotFoundError, ScopeStore
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    """Each test gets its own state file, resolved from a fresh cwd."""
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    yield


class Approval(BaseModel):
    approved: bool


def _app() -> FunctualizeApp:
    app = FunctualizeApp(name="testapp")

    def build() -> str:
        return "artifact"

    def deploy() -> str:
        return "deployed"

    @workflow(
        steps=[
            Step("build"),
            Gate(name="approve_refund", awaits=Approval),
            Step("deploy"),
        ],
        edges=[
            Edge(source="build", target="approve_refund"),
            Edge(source="approve_refund", target="deploy"),
            Edge(source="deploy", target=END),
        ],
    )
    def release() -> str:
        return "shipped"

    app.register_dynamic_job("build", build)
    app.register_dynamic_job("deploy", deploy)
    app.register_dynamic_job("release", release)
    return app


@pytest.fixture
def blocked() -> FunctualizeApp:
    app = _app()
    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="rel-1")
    )
    return app


def _raiser(*args: object, **kwargs: object) -> object:
    raise GateNotFoundError("nope", scope_id="rel-1", known=["approve-refund"])


@pytest.fixture
def refuse_unknown_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every lifted function the three tools consult, raising the C-1 error.

    `answer_gate` and `get_gate_draft` resolve their target before calling
    the answer path, and `resume_workflow` advances through `resume_scope`,
    so all four module-level bindings are patched.
    """
    monkeypatch.setattr("functualize_mcp._workflow_tools.resolve_gate", _raiser)
    monkeypatch.setattr("functualize_mcp._workflow_tools.answer_gate", _raiser)
    monkeypatch.setattr("functualize_mcp._workflow_tools.gate_draft", _raiser)
    monkeypatch.setattr("functualize_mcp._workflow_tools.resume_scope", _raiser)


class TestAnswerGateRefuses:
    async def test_unknown_gate_returns_the_gate_list(
        self, blocked: FunctualizeApp, refuse_unknown_gate: None
    ) -> None:
        provider = WorkflowToolProvider(
            blocked, store=ScopeStore.for_project(Path.cwd())
        )

        result = await provider._answer_gate(
            {"approved": True}, workflow_id="rel-1", gate="nope"
        )

        assert result["error"] == "gate_not_found"
        assert result["gates"] == ["approve-refund"]
        assert "nope" in result["message"]


class TestGetGateDraftRefuses:
    async def test_unknown_gate_returns_the_gate_list(
        self, blocked: FunctualizeApp, refuse_unknown_gate: None
    ) -> None:
        provider = WorkflowToolProvider(
            blocked, store=ScopeStore.for_project(Path.cwd())
        )

        result = await provider._get_gate_draft(workflow_id="rel-1", gate="nope")

        assert result["error"] == "gate_not_found"
        assert result["gates"] == ["approve-refund"]
        assert "nope" in result["message"]


class TestResumeWorkflowRefuses:
    async def test_unknown_gate_returns_the_gate_list(
        self, blocked: FunctualizeApp, refuse_unknown_gate: None
    ) -> None:
        provider = WorkflowToolProvider(
            blocked, store=ScopeStore.for_project(Path.cwd())
        )

        result = await provider._resume_workflow(
            workflow_id="rel-1", input={"approved": True}, gate="nope"
        )

        assert result["error"] == "gate_not_found"
        assert result["gates"] == ["approve-refund"]
        assert "nope" in result["message"]
