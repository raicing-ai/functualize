"""The CLI refuses an unknown gate by name, not by traceback (T2).

`workflow answer`/`resume` and the fused `--wf-resume --wf-input --wf-gate`
learn to translate `GateNotFoundError` here — before any production code
raises it. The raisers in this file are monkeypatched, the standing
transitional arrangement: the resolver that raises in production lands with
the gate-name-resolution resolver tasks, and the checkpoint task proves each
arm against the real raiser.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import click
import pytest
from click.testing import CliRunner, Result
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._cli.builtins import register_builtin_commands
from functualize.app.adapters.workflow_flags import apply_workflow_flags
from functualize.app.core import FunctualizeApp
from functualize.app.utils import GateNotFoundError
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
def app(project: Path) -> FunctualizeApp:
    instance = FunctualizeApp(name="testapp")

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

    instance.register_dynamic_job("build", build)
    instance.register_dynamic_job("deploy", deploy)
    instance.register_dynamic_job("release", release)
    return instance


@pytest.fixture
def blocked(app: FunctualizeApp) -> FunctualizeApp:
    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="rel-1")
    )
    return app


def _raiser(*args: object, **kwargs: object) -> object:
    raise GateNotFoundError("nope", scope_id="rel-1", known=["approve-refund"])


@pytest.fixture
def refuse_unknown_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every import home the CLI paths reach, raising the unknown-gate error.

    `workflow answer` imports `answer_gate`/`gate_draft` from
    `functualize.app.utils` at call time; `workflow resume` reaches
    `answer_gate` through the module-global binding in the resume module, so
    both homes are patched.
    """
    monkeypatch.setattr("functualize.app.utils.answer_gate", _raiser)
    monkeypatch.setattr("functualize.app.utils.gate_draft", _raiser)
    monkeypatch.setattr("functualize.app.utils.resolve_gate", _raiser)
    monkeypatch.setattr("functualize.app._workflow_control.answer_gate", _raiser)


def _invoke(app: FunctualizeApp, args: list[str]) -> Result:
    root = click.Group(name="func")
    register_builtin_commands(root)
    return CliRunner().invoke(root, args, obj={"app": app})


class TestWorkflowAnswer:
    def test_answer_exits_one_with_the_error_line(
        self, blocked: FunctualizeApp, refuse_unknown_gate: None
    ) -> None:
        result = _invoke(
            blocked,
            ["builtin", "workflow", "answer", "rel-1", "nope", "--input", "{}"],
        )

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "Error: Workflow 'rel-1' has no gate 'nope'" in result.output
        assert "approve-refund" in result.output

    def test_show_exits_one_with_the_error_line(
        self, blocked: FunctualizeApp, refuse_unknown_gate: None
    ) -> None:
        result = _invoke(
            blocked,
            ["builtin", "workflow", "answer", "rel-1", "nope", "--show"],
        )

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "Error: Workflow 'rel-1' has no gate 'nope'" in result.output
        assert "approve-refund" in result.output


class TestWorkflowResume:
    def test_resume_with_gate_exits_one_with_the_error_line(
        self, blocked: FunctualizeApp, refuse_unknown_gate: None
    ) -> None:
        result = _invoke(
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

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "Error: Workflow 'rel-1' has no gate 'nope'" in result.output
        assert "approve-refund" in result.output


class TestFusedFlags:
    def test_wf_resume_with_input_and_gate_exits_one(
        self,
        blocked: FunctualizeApp,
        refuse_unknown_gate: None,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as raised:
            apply_workflow_flags(
                blocked,
                "release",
                {"wf_resume": "rel-1", "wf_input": "{}", "wf_gate": "nope"},
            )

        assert raised.value.code == 1
        err = capsys.readouterr().err
        assert "Error: Workflow 'rel-1' has no gate 'nope'" in err
        assert "approve-refund" in err
