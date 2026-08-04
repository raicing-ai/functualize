"""D2b — `func builtin workflow` CLI parity with the MCP workflow tools.

The load-bearing claim: the CLI `resume` and the MCP `resume_gate` tool advance
a blocked workflow through the **same** lifted `deposit_gate_input`, not two
implementations that can drift. So this file drives the whole loop over the CLI
(mirror of the S4 MCP loop test) *and* asserts both surfaces route through the
one function.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import click
import pytest
from pydantic import BaseModel, Field

from functualize._app.state import AppState
from functualize._cli.builtins import register_builtin_commands
from functualize.app.core import FunctualizeApp
from functualize.app.utils import StateStore
from functualize.job import RunStatus
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
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    yield


class Deployment(BaseModel):
    environment: str = Field(description="Target environment")
    replicas: int = Field(description="Replica count")


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


def _run_cli(app: FunctualizeApp, args: list[str]) -> int:
    """Invoke `func builtin …` the way BUILTIN mode does: obj carries the app."""
    root = click.Group(name="func")
    register_builtin_commands(root)
    try:
        root.main(
            args=args,
            prog_name="func",
            standalone_mode=False,
            obj={"app": app},
        )
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    return 0


class TestCliDrivesABlockedWorkflow:
    def test_blocked_then_cli_resume_then_rerun_completes(
        self, app: FunctualizeApp, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Mirror of the S4 MCP loop, driven entirely over the CLI."""
        blocked = app.execute("release", scope_id="rel-1")
        assert blocked.status is RunStatus.BLOCKED

        # `list` sees the blocked scope.
        assert _run_cli(app, ["builtin", "workflow", "list", "--format", "json"]) == 0
        listing = json.loads(capsys.readouterr().out)
        assert listing["workflows"][0]["workflow_id"] == "rel-1"
        assert listing["workflows"][0]["pending_gates"] == ["approval"]

        # `resume` deposits the gate input.
        code = _run_cli(
            app,
            [
                "builtin",
                "workflow",
                "resume",
                "rel-1",
                "approval",
                "--input",
                json.dumps({"environment": "prod", "replicas": 3}),
            ],
        )
        assert code == 0
        assert "Input accepted" in capsys.readouterr().out

        # Re-running the job replays past the answered gate to completion.
        done = app.execute("release", scope_id="rel-1")
        assert done.status is RunStatus.SUCCESS
        assert app.ran.count("deploy") == 1  # type: ignore[attr-defined]

    def test_resume_rejects_invalid_input_and_deposits_nothing(
        self, app: FunctualizeApp, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app.execute("release", scope_id="rel-1")

        # `replicas` is required and typed int; a bad payload must be refused.
        code = _run_cli(
            app,
            [
                "builtin",
                "workflow",
                "resume",
                "rel-1",
                "approval",
                "--input",
                json.dumps({"environment": "prod"}),
            ],
        )
        assert code == 1
        assert "does not satisfy" in capsys.readouterr().err.lower()

        # Still blocked — the run does not complete on a re-run.
        assert app.execute("release", scope_id="rel-1").status is RunStatus.BLOCKED

    def test_state_reports_the_scope(
        self, app: FunctualizeApp, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app.execute("release", scope_id="rel-1")
        assert (
            _run_cli(app, ["builtin", "workflow", "state", "rel-1", "--format", "json"])
            == 0
        )
        detail = json.loads(capsys.readouterr().out)
        assert detail["status"] == "blocked"
        assert detail["pending_gates"] == ["approval"]

    def test_cancel_marks_the_scope_cancelled(self, app: FunctualizeApp) -> None:
        app.execute("release", scope_id="rel-1")
        assert _run_cli(app, ["builtin", "workflow", "cancel", "rel-1"]) == 0
        scope = StateStore.for_project(Path.cwd()).get_scope("rel-1")
        assert scope is not None and scope["status"] == "cancelled"

    def test_state_of_unknown_scope_errors(self, app: FunctualizeApp) -> None:
        assert _run_cli(app, ["builtin", "workflow", "state", "nope"]) == 1


class TestParityIsOneFunction:
    """MCP `resume_gate` and CLI `resume` call the SAME lifted function.

    Not "two functions that behave the same" — the acceptance is a single
    implementation. Patch the lifted symbol and confirm both surfaces route
    through it.
    """

    async def test_both_surfaces_call_deposit_gate_input(
        self, app: FunctualizeApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize_mcp._workflow_tools import WorkflowToolProvider

        app.execute("release", scope_id="rel-1")

        calls: list[str] = []
        sentinel = {"status": "input_accepted", "gate": "approval", "message": "ok"}

        def _spy(app_arg, store, scope_id, gate, payload):  # noqa: ANN001, ANN202
            calls.append(scope_id)
            return sentinel

        # Both the MCP tool module and the builtins module import the symbol
        # from the same public home; patch it at the source module.
        monkeypatch.setattr("functualize.app._workflow_resume.deposit_gate_input", _spy)
        monkeypatch.setattr("functualize.app.utils.deposit_gate_input", _spy)
        monkeypatch.setattr("functualize_mcp._workflow_tools.deposit_gate_input", _spy)

        # MCP path.
        provider = WorkflowToolProvider(app, store=StateStore.for_project(Path.cwd()))
        await provider._resume_gate("approval", {"environment": "prod", "replicas": 3})

        # CLI path.
        import functualize._cli.builtins as builtins_mod

        monkeypatch.setattr(builtins_mod, "deposit_gate_input", _spy, raising=False)
        _run_cli(
            app,
            [
                "builtin",
                "workflow",
                "resume",
                "rel-1",
                "approval",
                "--input",
                json.dumps({"environment": "prod", "replicas": 3}),
            ],
        )

        assert calls.count("rel-1") == 2, "both surfaces routed through the lift"
