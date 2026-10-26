"""Recorded decisions have one operator projection on both runtime stores."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from functualize._engine.workflow_walker import WalkOutcome, WorkflowWalker
from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.workflow import WorkflowDeclaration
from functualize.app._workflow_view import describe_scope, list_scopes
from functualize.plugin import Claimed, ClaimWorkflow, RecordBranch, RuntimeStoreConfig
from functualize.workflow import END, ConditionalEdge, Edge, OnFailure, Step

if TYPE_CHECKING:
    from functualize.plugin import RuntimeStore


class _App:
    def get_job(self, name: str) -> None:
        del name
        return None


def _store(backend: str, root: Path) -> RuntimeStore:
    if backend == "documents":
        return DocumentRuntimeStore(JsonFileSubstrate(root))
    sqlite = pytest.importorskip("functualize_substrate_sqlite")
    return (
        sqlite.SqliteRuntimeStoreFactory()
        .prepare(
            RuntimeStoreConfig(
                url=f"sqlite://{root / 'state.db'}", scheme="sqlite", project_root=root
            )
        )
        .store
    )


def _record(store: RuntimeStore, *decisions: tuple[str, str]) -> None:
    now = datetime.now(UTC)
    with store.transaction() as tx:
        outcome = tx.workflows.claim(ClaimWorkflow("release", "operator", now, 300))
    assert isinstance(outcome, Claimed)
    with store.transaction() as tx:
        for key, target in decisions:
            tx.workflows.record_branch(
                RecordBranch("release", outcome.generation, key, target, now)
            )


@pytest.mark.parametrize("backend", ["documents", "sqlite"])
def test_choices_and_failure_routes_are_separate_and_ordered(
    backend: str, tmp_path: Path
) -> None:
    store = _store(backend, tmp_path)
    try:
        _record(
            store,
            ("score-submission", "approve"),
            ("publish\x00onfailure", "rollback"),
            ("check", "review"),
            ("archive\x00onfailure", "\x00end"),
        )
        detail = describe_scope(_App(), store, "release")
        assert detail is not None
        assert list(detail["branches"].items()) == [
            ("score-submission", "approve"),
            ("check", "review"),
        ]
        assert list(detail["failure_routes"].items()) == [
            ("publish", "rollback"),
            ("archive", "END"),
        ]
        assert "\x00" not in repr((detail["branches"], detail["failure_routes"]))
        assert list_scopes(_App(), store)[0] == detail
    finally:
        store.close()


@pytest.mark.parametrize("backend", ["documents", "sqlite"])
def test_no_decisions_projects_two_empty_maps(backend: str, tmp_path: Path) -> None:
    store = _store(backend, tmp_path)
    try:
        _record(store)
        detail = describe_scope(_App(), store, "release")
        assert detail is not None
        assert detail["branches"] == {}
        assert detail["failure_routes"] == {}
    finally:
        store.close()


@pytest.mark.parametrize("backend", ["documents", "sqlite"])
def test_notification_marker_is_not_a_route(backend: str, tmp_path: Path) -> None:
    store = _store(backend, tmp_path)
    try:
        _record(store, ("\x00notify\x00completed\x00\x00ops", "sent"))
        detail = describe_scope(_App(), store, "release")
        assert detail is not None
        assert detail["branches"] == {}
        assert detail["failure_routes"] == {}
    finally:
        store.close()


@pytest.mark.parametrize("backend", ["documents", "sqlite"])
@pytest.mark.parametrize("failure_target", ["rollback", END])
def test_a_walk_projects_its_recorded_route(
    backend: str, failure_target: str, tmp_path: Path
) -> None:
    store = _store(backend, tmp_path)
    graph = WorkflowDeclaration(
        nodes=(
            Step("score-submission"),
            Step("approve"),
            Step("publish"),
            Step("rollback"),
        ),
        edges=(
            ConditionalEdge(
                source="score-submission",
                condition=lambda value: "approve",
                targets={"approve": "approve"},
            ),
            Edge(source="approve", target="publish"),
            Edge(source="publish", target=END),
            OnFailure(source="publish", target=failure_target),
            Edge(source="rollback", target=END),
        ),
    )

    def run_step(name: str) -> str:
        if name == "publish":
            raise RuntimeError("publish failed")
        return name

    try:
        report = WorkflowWalker(
            graph, "release", run_step=run_step, runtime_store=store
        ).run()
        assert report.outcome is WalkOutcome.COMPLETED
        detail = describe_scope(_App(), store, "release")
        assert detail is not None
        assert detail["branches"] == {"score-submission": "approve"}
        assert detail["failure_routes"] == {
            "publish": "END" if failure_target is END else "rollback"
        }
    finally:
        store.close()


def test_cli_subprocess_names_recorded_and_empty_routes(tmp_path: Path) -> None:
    """Drive the text renderer through the builtin CLI in an isolated child."""
    script = """
import click
from datetime import UTC, datetime
from functualize._cli.builtins import register_builtin_commands
from functualize.app.core import FunctualizeApp
from functualize.plugin import RecordBranch
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Step, workflow

app = FunctualizeApp(name="routes")
app.register_dynamic_job("work", lambda: "done")
@workflow(steps=[Step("work")], edges=[Edge(source="work", target=END)])
def release():
    return "released"
app.register_dynamic_job("release", release)
for scope_id in ("empty", "chosen"):
    app.execute(RunRequest(job_name="release", surface="app.execute", workflow_scope_id=scope_id))
runtime = app.workflow_runtime_store()
view = runtime.workflows.workflow("chosen")
assert view is not None and view.generation is not None
with runtime.transaction() as tx:
    tx.workflows.record_branch(RecordBranch("chosen", view.generation, "work", "done", datetime.now(UTC)))
root = click.Group(name="func")
register_builtin_commands(root)
for scope_id in ("empty", "chosen"):
    root.main(args=["builtin", "workflow", "show", scope_id], prog_name="func", standalone_mode=False, obj={"app": app})
"""
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CACHE_HOME=str(home / ".cache"),
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Branches: -" in result.stdout
    assert "Branches: work -> done" in result.stdout
    assert result.stdout.count("Failure routes: -") == 2
