"""The lifted projection, and the derived state it computes.

Two projections of the same store existed in the same process and the poorer
one faced humans: `_describe` in the MCP plugin computed the whole graph, and
the CLI's `_scope_summary` emitted five fields over the same records. They had
already drifted on every field but `status`.

These tests cover the derivation directly. That the two *surfaces* agree is a
separate claim with its own test — `test_workflow_surface_parity.py` — because
one implementation is only half of `pitfalls.md` §6; the other half is a test
that checks the callers against it.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app._workflow_view import derived_state
from functualize.app.core import FunctualizeApp
from functualize.app.utils import (
    StateStore,
    describe_scope,
    list_scopes,
)
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
        return "artifact-v2"

    @workflow(
        steps=[Step("build"), Gate(name="approve", awaits=Approval)],
        edges=[
            Edge(source="build", target="approve"),
            Edge(source="approve", target=END),
        ],
    )
    def release() -> str:
        return "shipped"

    instance.register_dynamic_job("build", build)
    instance.register_dynamic_job("release", release)
    return instance


class TestDerivedState:
    """Spec §3.2. Pure, total, no store read."""

    def test_blocked_with_a_pending_gate_is_waiting(self) -> None:
        assert (
            derived_state({"status": "blocked", "gates": {"g": {"payload": None}}})
            == "waiting"
        )

    def test_blocked_with_no_pending_gate_is_ready(self) -> None:
        """The unnamed state: an answered scope read `blocked` with no pending
        gates and looked stuck. `ready` is exactly what `resume` can advance."""
        assert (
            derived_state({"status": "blocked", "gates": {"g": {"payload": {"ok": 1}}}})
            == "ready"
        )

    def test_completed_with_a_failed_epilogue_is_stalled(self) -> None:
        """Ordering is load-bearing — this must be reached before the plain
        `completed` branch, or the sticky-body case is invisible."""
        scope = {"status": "completed", "epilogue": {"status": "failed"}}
        assert derived_state(scope) == "stalled"

    def test_completed_with_a_good_epilogue_is_completed(self) -> None:
        scope = {"status": "completed", "epilogue": {"status": "success"}}
        assert derived_state(scope) == "completed"

    def test_completed_with_no_epilogue_is_completed(self) -> None:
        assert derived_state({"status": "completed"}) == "completed"

    def test_terminal_statuses_pass_through(self) -> None:
        assert derived_state({"status": "cancelled"}) == "cancelled"
        assert derived_state({"status": "failed"}) == "failed"
        assert derived_state({"status": "running"}) == "running"

    def test_an_unknown_status_is_not_invented(self) -> None:
        assert derived_state({"status": "weird"}) == "weird"
        assert derived_state({}) == "unknown"


class TestDescribeScope:
    def test_it_carries_the_graph_and_the_progress(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-1"
            )
        )
        store = StateStore.for_project(project)

        view = describe_scope(app, store, "rel-1")

        assert view is not None
        assert view["workflow"] == "release"
        assert view["state"] == "waiting"
        # The cached shape spells a node `{"step": name}` or
        # `{"gate": name, "model": ...}` — the kind is the key, not a field.
        assert view["steps"] == [
            {"step": "build"},
            {"gate": "approve", "model": "Approval"},
        ]
        assert view["current_position"] == "approve"
        assert view["results"]["build"]["return_value"] == "artifact-v2"
        assert [g["gate"] for g in view["pending_gates"]] == ["approve"]

    def test_an_unknown_scope_is_none_not_an_empty_projection(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """None lets each surface pick its own exit code; an empty projection
        would read as 'a run with no steps'."""
        store = StateStore.for_project(project)
        assert describe_scope(app, store, "nope") is None

    def test_the_epilogue_is_carried(self, app: FunctualizeApp, project: Path) -> None:
        """A projection that omitted it could not explain its own `state`."""
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-1"
            )
        )
        store = StateStore.for_project(project)
        assert "epilogue" in describe_scope(app, store, "rel-1")


class TestListScopes:
    def test_it_lists_live_scopes_by_default(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-1"
            )
        )
        store = StateStore.for_project(project)
        store.ensure_scope("old", "release")
        store.set_scope_status("old", "completed")

        ids = [r["workflow_id"] for r in list_scopes(app, store)]
        assert ids == ["rel-1"]

    def test_naming_a_state_widens_the_search(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """Asking for `completed` and receiving nothing would be a silently
        empty answer to a well-formed question."""
        store = StateStore.for_project(project)
        store.ensure_scope("old", "release")
        store.set_scope_status("old", "completed")

        rows = list_scopes(app, store, state="completed")
        assert [r["workflow_id"] for r in rows] == ["old"]

    def test_it_filters_by_workflow(self, app: FunctualizeApp, project: Path) -> None:
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-1"
            )
        )
        store = StateStore.for_project(project)
        store.ensure_scope("other", "something-else")

        rows = list_scopes(app, store, workflow_name="release")
        assert [r["workflow_id"] for r in rows] == ["rel-1"]

    def test_it_filters_by_pending_gate(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-1"
            )
        )
        store = StateStore.for_project(project)

        assert list_scopes(app, store, blocked_on="approve")
        assert list_scopes(app, store, blocked_on="nope") == []

    def test_a_row_is_the_full_projection(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """There is deliberately no reduced survey shape.

        An earlier cut had one and it collided immediately: `pending_gates`
        meant *names* in the survey and *gate summaries* in the detail, so no
        two surfaces could return "the same rows" however carefully each was
        written. One key, two shapes, is the drift this module ends.
        """
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-1"
            )
        )
        store = StateStore.for_project(project)

        assert list_scopes(app, store)[0] == describe_scope(app, store, "rel-1")
