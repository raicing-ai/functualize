"""Read the selected workflow store from a booted app."""

from functualize.app import FunctualizeApp
from functualize.app.utils import selected_workflow_store
from functualize.plugin import WorkflowQuery


def test_an_operator_can_read_the_selected_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = FunctualizeApp("workflow-reader")

    runtime = app.workflow_runtime_store()
    assert runtime.profile.name == "documents"
    assert runtime.workflows.resumable(WorkflowQuery()) == ()
    assert selected_workflow_store(app).scope_ids() == []
