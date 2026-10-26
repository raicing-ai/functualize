"""An old runtime store refuses each operator surface instead of hiding routes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from functualize_mcp._workflow_tools import WorkflowToolProvider
from functualize_substrate_sqlite import SQLiteSubstratePlugin
from functualize_substrate_sqlite._readers import SqlWorkflowReader

from functualize._cli.builtins import register_builtin_commands
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize.app import ConfigSources, FunctualizeApp, JobSources, PluginSources
from functualize.app.adapters.click_params import create_job_click_command
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Step, workflow


@pytest.fixture
def older_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".functualize").mkdir()
    monkeypatch.chdir(tmp_path)
    app = FunctualizeApp(
        name="routes",
        job_sources=JobSources(functions=[]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain(
                [DefaultSource({"runtime_store": {"url": "sqlite:"}})]
            )
        ),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[SQLiteSubstratePlugin()]
        ),
    )
    app.register_dynamic_job("work", lambda: "done")

    @workflow(steps=[Step("work")], edges=[Edge("work", END)])
    def release() -> str:
        return "released"

    app.register_dynamic_job("release", release)
    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="route")
    )
    assert app.workflow_runtime_store().profile.name == "sqlite"
    monkeypatch.delattr(SqlWorkflowReader, "branches")
    return app, release


def test_builtin_workflow_show_exits_two_with_upgrade_message(older_store) -> None:
    app, _release = older_store
    root = click.Group(name="func")
    register_builtin_commands(root)

    result = CliRunner().invoke(
        root, ["builtin", "workflow", "show", "route"], obj={"app": app}
    )

    assert result.exit_code == 2, result.output
    assert "Error: " in result.output
    assert "runtime store 'sqlite'" in result.output
    assert "WorkflowReader.branches is missing" in result.output
    assert "Upgrade the plugin" in result.output


def test_mcp_workflow_tools_return_unreadable_error(older_store) -> None:
    app, _release = older_store
    provider = WorkflowToolProvider(app)

    async def call_tools() -> dict[str, dict[str, object]]:
        return {
            "get_workflow_state": await provider._get_workflow_state("route"),
            "list_workflows": await provider._list_workflows(),
            "resume_workflow": await provider._resume_workflow("route", {}),
        }

    for name, result in asyncio.run(call_tools()).items():
        assert result["error"] == "scope_store_unreadable", (name, result)
        assert "WorkflowReader.branches is missing" in str(result["message"])


def test_wf_show_exits_two_without_running_the_job(older_store) -> None:
    app, release = older_store
    command = create_job_click_command("release", release, app=app, surface="app.cli")

    result = CliRunner().invoke(command, ["--wf-show", "route"])

    assert result.exit_code == 2, result.output
    assert "WorkflowReader.branches is missing" in result.output
