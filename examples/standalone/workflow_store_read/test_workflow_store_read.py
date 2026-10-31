"""Read the selected workflow store from a booted app."""

from pathlib import Path

import pytest

from functualize.app import FunctualizeApp, JobSources
from functualize.app.utils import selected_workflow_store
from functualize.plugin import WorkflowQuery
from functualize.types import RunRequest
from functualize.workflow import END, ConditionalEdge, Edge, Step, workflow


def test_an_operator_can_read_the_selected_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = FunctualizeApp("workflow-reader")

    runtime = app.workflow_runtime_store()
    assert runtime.profile.name == "documents"
    assert runtime.workflows.resumable(WorkflowQuery()) == ()
    assert selected_workflow_store(app).scope_ids() == []


@workflow(
    steps=[Step("triage"), Step("hotfix"), Step("backlog")],
    edges=[
        ConditionalEdge(
            source="triage",
            condition=lambda severity: "hotfix" if severity == "high" else "backlog",
            targets={"hotfix": "hotfix", "backlog": "backlog"},
        ),
        Edge(source="hotfix", target=END),
        Edge(source="backlog", target=END),
    ],
)
def incident() -> str:
    return "handled"


@pytest.mark.parametrize("store", ["documents", "sqlite"])
def test_a_store_lists_a_scopes_recorded_decisions(tmp_path, monkeypatch, store):
    """`workflows.branches` returns every decision record of one scope, raw.

    One call per scope, in the order the walk recorded them, on every store —
    the read a custom operator surface makes to show where a walk went.
    """
    monkeypatch.chdir(tmp_path)
    if store == "sqlite":
        pytest.importorskip("functualize_substrate_sqlite")
        Path("config.base.toml").write_text('[runtime_store]\nurl = "sqlite:"\n')
    app = FunctualizeApp("incident-desk", job_sources=JobSources(directories=[]))
    app.register_dynamic_job("triage", lambda: "high")
    app.register_dynamic_job("hotfix", lambda: "patched")
    app.register_dynamic_job("backlog", lambda: "queued")
    app.register_dynamic_job("incident", incident)

    result = app.execute(
        RunRequest(
            job_name="incident", surface="app.execute", workflow_scope_id="inc-1"
        )
    )
    assert result.exception is None, result.exception

    runtime = app.workflow_runtime_store()
    assert runtime.profile.name == store
    assert dict(runtime.workflows.branches("inc-1")) == {"triage": "hotfix"}
    assert dict(runtime.workflows.branches("no-such-scope")) == {}
