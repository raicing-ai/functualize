"""Recorded decisions have one operator projection on both runtime stores."""

from __future__ import annotations

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
