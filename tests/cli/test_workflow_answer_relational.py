"""The answer surfaces on a relational selected store (row 3.2).

`func builtin workflow answer` / `resume`, the fused `--wf-resume --wf-input`
and the MCP `answer_gate` / `get_gate_draft` / `resume_workflow` tools all
resolve their store through ``selected_workflow_store``. With SQLite selected
that is the ``RuntimeStore`` port, so an answer lands where the walk that
blocked reads it, and the legacy scope document is never consulted. The
production call paths these tests drive::

    func builtin workflow answer  → _workflow_operator_store → answer_gate (port seam)
    func builtin workflow resume  → _workflow_operator_store → resume_scope → walk
    --wf-input                    → workflow_flags._record → resolve_gate → answer_gate
    MCP answer_gate / resume_workflow → operator_store → answer_gate / resume_scope

The relational input path that ``_record_port_input`` used to serve goes
through the one ``answer_gate`` now; the ``--wf-input`` cases below are the
proof that removing it dropped nothing — an invalid input still exits as a
usage error, and is still recorded.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner, Result
from functualize_mcp._workflow_tools import WorkflowToolProvider
from functualize_substrate_sqlite import SQLiteSubstratePlugin
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._cli.builtins import register_builtin_commands
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._primitives.scope_store import ScopeStore
from functualize._types.gate_resolution import EvaluationOutcome
from functualize._types.persistence import RuntimeStore
from functualize.app.adapters.workflow_flags import apply_workflow_flags
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.app.core import FunctualizeApp
from functualize.app.utils import selected_workflow_store
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow

SCOPE = "rel-1"


class Approval(BaseModel):
    approved: bool
    reason: str


def build() -> str:
    return "artifact"


def deploy() -> str:
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
    return "shipped"


@pytest.fixture(autouse=True)
def _reset() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeApp:
    """A SQLite-selected project with `release` blocked at its gate."""
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    instance = FunctualizeApp(
        "relational",
        job_sources=JobSources(functions=[build, deploy, release]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain(
                [DefaultSource({"runtime_store": {"url": "sqlite:"}})]
            )
        ),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[SQLiteSubstratePlugin()]
        ),
    )
    instance.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id=SCOPE)
    )
    store = instance.workflow_runtime_store()
    view = store.workflows.workflow(SCOPE)
    assert view is not None and view.status == "blocked"
    return instance


def _store(app: FunctualizeApp) -> RuntimeStore:
    store = selected_workflow_store(app)
    assert isinstance(store, RuntimeStore)
    return store


def _cli(app: FunctualizeApp, *args: str) -> Result:
    root = click.Group(name="func")
    register_builtin_commands(root)
    return CliRunner().invoke(root, ["builtin", "workflow", *args], obj={"app": app})


def _never_in_the_scope_document(app: FunctualizeApp) -> None:
    """The legacy scope document holds no record of the relational scope."""
    assert ScopeStore(app.substrate).get_scope(SCOPE) is None


def _outcomes(app: FunctualizeApp) -> list[EvaluationOutcome]:
    store = _store(app)
    request = store.inputs.for_gate(SCOPE, "approve")
    assert request is not None
    return [
        c.evaluation.outcome for c in store.inputs.candidates_for(request.request_id)
    ]


class TestCliAnswerAndResume:
    def test_answer_records_on_the_selected_store_and_resume_advances(
        self, app: FunctualizeApp
    ) -> None:
        answered = _cli(
            app,
            "answer",
            SCOPE,
            "approve",
            "--input",
            '{"approved": true, "reason": "reviewed"}',
            "--format",
            "json",
        )

        assert answered.exit_code == 0, answered.output
        payload = json.loads(answered.output)
        assert payload["status"] == "answered"
        resolution = payload["resolution"]
        store = _store(app)
        request = store.inputs.request(resolution["request_id"])
        assert request is not None and request.status == "accepted"
        decision = store.inputs.decision(request.request_id)
        assert decision is not None
        assert resolution["accepted_id"] == decision.accepted_id
        _never_in_the_scope_document(app)

        resumed = _cli(app, "resume", SCOPE, "--format", "json")

        assert resumed.exit_code == 0, resumed.output
        assert json.loads(resumed.output)["status"] == "success"
        view = store.workflows.workflow(SCOPE)
        assert view is not None and view.status == "completed"
        consumed = store.inputs.request(request.request_id)
        assert consumed is not None and consumed.status == "consumed"
        _never_in_the_scope_document(app)

    def test_show_reads_the_draft_the_last_submission_holds(
        self, app: FunctualizeApp
    ) -> None:
        partial = _cli(app, "answer", SCOPE, "approve", "--set", "approved=true")
        assert partial.exit_code == 0, partial.output

        shown = _cli(app, "answer", SCOPE, "approve", "--show", "--format", "json")

        assert shown.exit_code == 0, shown.output
        report = json.loads(shown.output)
        assert report["draft"] == {"approved": True}
        assert [entry["field"] for entry in report["missing"]] == ["reason"]
        assert _outcomes(app) == [EvaluationOutcome.INVALID]

    def test_resume_with_fused_input_answers_and_advances(
        self, app: FunctualizeApp
    ) -> None:
        resumed = _cli(
            app,
            "resume",
            SCOPE,
            "--input",
            '{"approved": true, "reason": "fused"}',
            "--format",
            "json",
        )

        assert resumed.exit_code == 0, resumed.output
        assert json.loads(resumed.output)["status"] == "success"
        assert _outcomes(app) == [EvaluationOutcome.ACCEPTED]
        _never_in_the_scope_document(app)

    @pytest.mark.parametrize(
        ("args", "code"),
        [
            (
                ("answer", SCOPE, "approve", "--set", "approved=true", "--no-commit"),
                "draft_requires_commit",
            ),
            (("resume", SCOPE, "--retry-epilogue"), "epilogue_retry_unsupported"),
        ],
        ids=["no-commit", "retry-epilogue"],
    )
    def test_what_the_port_cannot_hold_is_a_usage_refusal(
        self, app: FunctualizeApp, args: tuple[str, ...], code: str
    ) -> None:
        result = _cli(app, *args, "--format", "json")

        assert result.exit_code == 2, result.output
        assert json.loads(result.output)["error"] == code
        view = _store(app).workflows.workflow(SCOPE)
        assert view is not None and view.status == "blocked"
        assert _outcomes(app) == []


class TestWfInput:
    """The relational input path ``_record_port_input`` used to serve."""

    def test_a_valid_input_is_answered_through_the_selected_store(
        self, app: FunctualizeApp
    ) -> None:
        scope_id = apply_workflow_flags(
            app,
            "release",
            {
                "wf_resume": SCOPE,
                "wf_input": '{"approved": true, "reason": "flag"}',
                "wf_gate": "approve",
            },
        )

        assert scope_id == SCOPE
        assert _outcomes(app) == [EvaluationOutcome.ACCEPTED]
        store = _store(app)
        request = store.inputs.for_gate(SCOPE, "approve")
        assert request is not None and store.inputs.decision(request.request_id)
        _never_in_the_scope_document(app)

    def test_an_invalid_input_exits_as_usage_and_is_recorded(
        self, app: FunctualizeApp, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as raised:
            apply_workflow_flags(
                app,
                "release",
                {"wf_resume": SCOPE, "wf_input": '{"approved": "maybe"}'},
            )

        assert raised.value.code == 2
        assert "not valid" in capsys.readouterr().out
        assert _outcomes(app) == [EvaluationOutcome.INVALID]

    def test_an_unknown_gate_exits_one(
        self, app: FunctualizeApp, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as raised:
            apply_workflow_flags(
                app,
                "release",
                {"wf_resume": SCOPE, "wf_input": "{}", "wf_gate": "nope"},
            )

        assert raised.value.code == 1
        assert "nope" in capsys.readouterr().err
        assert _outcomes(app) == []


class TestMcpGateTools:
    def test_answer_draft_and_resume_use_the_selected_store(
        self, app: FunctualizeApp
    ) -> None:
        provider = WorkflowToolProvider(app)

        draft = asyncio.run(provider._get_gate_draft(workflow_id=SCOPE))
        assert draft["gate"] == "approve" and draft["complete"] is False

        answered = asyncio.run(
            provider._answer_gate(
                {"approved": True, "reason": "agent"}, workflow_id=SCOPE
            )
        )
        assert answered["status"] == "answered", answered
        store = _store(app)
        request = store.inputs.for_gate(SCOPE, "approve")
        assert request is not None
        [candidate] = store.inputs.candidates_for(request.request_id)
        assert (candidate.channel, candidate.resolver_class) == ("mcp", "agent")

        resumed: dict[str, Any] = asyncio.run(
            provider._resume_workflow(workflow_id=SCOPE)
        )
        assert resumed["status"] == "success", resumed
        view = store.workflows.workflow(SCOPE)
        assert view is not None and view.status == "completed"
        _never_in_the_scope_document(app)
