"""End to end: every surface answers to the declared spelling (T7).

No monkeypatching and no source change — the resolver and the raisers the
earlier waves wired drive real MCP tool calls, real `builtin workflow`
invocations, and a real fused-flag subprocess against a scratch project.
The declared spelling is `approve_refund`; the walk parks it under
`approve-refund`; everything here must bridge the two, and a name that
matches nothing must fail loudly without a traceback anywhere.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Generator
from pathlib import Path

import click
import pytest
from functualize_mcp._workflow_tools import WorkflowToolProvider
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._cli.builtins import register_builtin_commands
from functualize.app.core import FunctualizeApp
from functualize.app.utils import ScopeStore
from functualize.job import RunStatus
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow

pytestmark = pytest.mark.anyio

PROJECT_ROOT = Path(__file__).parent.parent.parent


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


class Approval(BaseModel):
    approved: bool


@pytest.fixture
def app() -> FunctualizeApp:
    instance = FunctualizeApp(name="release")

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
        return "release complete"

    instance.register_dynamic_job("build", build)
    instance.register_dynamic_job("deploy", deploy)
    instance.register_dynamic_job("release", release)
    return instance


@pytest.fixture
def blocked(app: FunctualizeApp) -> FunctualizeApp:
    result = app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="rel-1")
    )
    assert result.status is RunStatus.BLOCKED
    return app


def _provider(app: FunctualizeApp) -> WorkflowToolProvider:
    return WorkflowToolProvider(app, store=ScopeStore.for_project(Path.cwd()))


def _run_cli(app: FunctualizeApp, args: list[str]) -> int:
    """Invoke `func builtin …` the way BUILTIN mode does: obj carries the app."""
    root = click.Group(name="func")
    register_builtin_commands(root)
    try:
        root.main(args=args, prog_name="func", standalone_mode=False, obj={"app": app})
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    return 0


class TestMcpSurface:
    """AC-3: the agent tools accept the declared spelling, end to end."""

    async def test_answer_gate_accepts_the_declared_spelling(
        self, blocked: FunctualizeApp
    ) -> None:
        result = await _provider(blocked)._answer_gate(
            {"approved": True}, gate="approve_refund"
        )

        assert result["status"] == "answered"
        assert result["gate"] == "approve-refund"

    async def test_get_gate_draft_accepts_the_declared_spelling(
        self, blocked: FunctualizeApp
    ) -> None:
        result = await _provider(blocked)._get_gate_draft(
            workflow_id="rel-1", gate="approve_refund"
        )

        assert "error" not in result
        assert result["gate"] == "approve-refund"

    async def test_resume_workflow_walks_past_the_gate(
        self, blocked: FunctualizeApp
    ) -> None:
        result = await _provider(blocked)._resume_workflow(
            workflow_id="rel-1", input={"approved": True}, gate="approve_refund"
        )

        assert result["status"] == "success"

    async def test_list_workflows_blocked_on_resolves(
        self, blocked: FunctualizeApp
    ) -> None:
        result = await _provider(blocked)._list_workflows(blocked_on="approve_refund")

        assert [w["workflow_id"] for w in result["workflows"]] == ["rel-1"]


class TestMcpUnknownGate:
    """AC-11 over MCP: the unknown gate names the gates that exist."""

    async def test_answer_gate(self, blocked: FunctualizeApp) -> None:
        result = await _provider(blocked)._answer_gate(
            {}, workflow_id="rel-1", gate="nope"
        )

        assert result["error"] == "gate_not_found"
        assert result["gates"] == ["approve-refund"]
        assert "nope" in result["message"]

    async def test_get_gate_draft(self, blocked: FunctualizeApp) -> None:
        result = await _provider(blocked)._get_gate_draft(
            workflow_id="rel-1", gate="nope"
        )

        assert result["error"] == "gate_not_found"
        assert result["gates"] == ["approve-refund"]

    async def test_resume_workflow(self, blocked: FunctualizeApp) -> None:
        result = await _provider(blocked)._resume_workflow(
            workflow_id="rel-1", input={}, gate="nope"
        )

        assert result["error"] == "gate_not_found"
        assert result["gates"] == ["approve-refund"]


class TestCliSurface:
    """AC-4 and AC-11 over the CLI: declared spelling works, unknown is loud."""

    def test_answer_by_declared_name_then_resume_finishes(
        self, blocked: FunctualizeApp, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(
            blocked,
            [
                "builtin",
                "workflow",
                "answer",
                "rel-1",
                "approve_refund",
                "--input",
                '{"approved": true}',
            ],
        )
        assert code == 0, capsys.readouterr().err

        code = _run_cli(blocked, ["builtin", "workflow", "resume", "rel-1"])
        assert code == 0, capsys.readouterr().err
        capsys.readouterr()

        _run_cli(blocked, ["builtin", "workflow", "list", "--format", "json"])
        assert json.loads(capsys.readouterr().out)["workflows"] == []

    def test_unknown_gate_on_answer_exits_one_without_a_traceback(
        self, blocked: FunctualizeApp, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(
            blocked, ["builtin", "workflow", "answer", "rel-1", "nope", "--input", "{}"]
        )

        assert code == 1
        captured = capsys.readouterr()
        assert "Error: Workflow 'rel-1' has no gate 'nope'" in captured.err
        assert "approve-refund" in captured.err
        assert "Traceback" not in captured.out + captured.err

    def test_unknown_gate_on_resume_exits_one_without_a_traceback(
        self, blocked: FunctualizeApp, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(
            blocked,
            [
                "builtin",
                "workflow",
                "resume",
                "rel-1",
                "--input",
                "{}",
                "--gate",
                "nope",
            ],
        )

        assert code == 1
        captured = capsys.readouterr()
        assert "Error: Workflow 'rel-1' has no gate 'nope'" in captured.err
        assert "approve-refund" in captured.err
        assert "Traceback" not in captured.out + captured.err


_RELEASE_JOB = """
from pydantic import BaseModel

from functualize import workflow
from functualize.job import Log, job
from functualize.workflow import END, Edge, Gate, Step


class Approval(BaseModel):
    approved: bool


@job
def build(log: Log) -> str:
    log("BUILD RAN")
    return "artifact"


@job
def deploy(log: Log) -> str:
    log("DEPLOY RAN")
    return "deployed"


@workflow(
    steps=[Step(build), Gate(name="approve_refund", awaits=Approval), Step(deploy)],
    edges=[
        Edge("build", "approve_refund"),
        Edge("approve_refund", "deploy"),
        Edge("deploy", END),
    ],
)
def release(log: Log) -> str:
    log("WALK BODY RAN")
    return "done"
"""


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    (tmp_path / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\nroot = true\n'
    )
    (tmp_path / ".functualize").mkdir()
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "release.py").write_text(_RELEASE_JOB)
    return tmp_path


def _child_env(scratch: Path) -> dict[str, str]:
    """The environment for a `func` subprocess: its own home, all four roots.

    Not hygiene — required. The autouse home fixture points `HOME` at a fixed
    path shared by every checkout on the machine, and a subprocess inherits
    it; `func` registers itself in `<config>/functualize/install.json` on
    every run and that registry is append-only by design, so a child writing
    there contaminates every future run. `_home` sits under the per-test
    scratch, so nothing survives the test.
    """
    env = dict(os.environ)
    home = scratch / "_home"
    home.mkdir(exist_ok=True)
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    return env


def _func(scratch: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args],
        capture_output=True,
        text=True,
        cwd=str(scratch),
        env=_child_env(scratch),
        timeout=180,
    )


def _scope_of(result: subprocess.CompletedProcess[str]) -> str:
    match = re.search(r"scope '([\w.-]+)'", result.stdout + result.stderr)
    assert match is not None, result.stdout + result.stderr
    return match.group(1)


class TestFusedFlags:
    """AC-4, the fused half: a real `func` process, cold and against the cache."""

    def test_wf_gate_by_declared_spelling_records_and_walks_on(
        self, scratch: Path
    ) -> None:
        blocked_run = _func(scratch, "release")
        assert blocked_run.returncode == 5, blocked_run.stdout + blocked_run.stderr
        scope = _scope_of(blocked_run)

        resumed = _func(
            scratch,
            "release",
            "--wf-resume",
            scope,
            "--wf-input",
            '{"approved": true}',
            "--wf-gate",
            "approve_refund",
        )
        blob = resumed.stdout + resumed.stderr
        assert resumed.returncode == 0, blob
        assert "WALK BODY RAN" in blob, blob
        assert "DEPLOY RAN" in blob, blob

        status = _func(scratch, "release", "--wf-status")
        assert scope not in status.stdout, status.stdout + status.stderr

    def test_an_unknown_wf_gate_refuses_without_a_traceback(
        self, scratch: Path
    ) -> None:
        """AC-11 through the fused flags, with the real raiser: exit 1, the
        Error line naming the gates that exist, and the walk not started."""
        blocked_run = _func(scratch, "release")
        assert blocked_run.returncode == 5, blocked_run.stdout + blocked_run.stderr
        scope = _scope_of(blocked_run)

        refused = _func(
            scratch,
            "release",
            "--wf-resume",
            scope,
            "--wf-input",
            "{}",
            "--wf-gate",
            "nope",
        )
        blob = refused.stdout + refused.stderr

        assert refused.returncode == 1, blob
        assert "Error: Workflow" in blob and "has no gate 'nope'" in blob, blob
        assert "approve-refund" in blob, blob
        assert "Traceback" not in blob, blob
        assert "WALK BODY RAN" not in blob, blob

        # The refusal left the scope untouched and still waiting.
        still = _func(scratch, "release", "--wf-status")
        assert scope in still.stdout, still.stdout + still.stderr
