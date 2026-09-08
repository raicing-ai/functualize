"""`cancel` means something now.

`cancel_workflow`'s description has always said *"Cancelled scopes are not
resumable."* Nothing enforced it: the string `cancelled` appeared **zero**
times across `executor.py`, `workflow_walker.py` and `workflow_runner.py`, so
invoking the workflow job against a cancelled scope walked it to completion and
overwrote the status with `completed`.

The promise was documentation. These tests are the rule.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._types.errors import ScopeCancelledError
from functualize.app.core import FunctualizeApp
from functualize.app.utils import StateStore
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
    calls: list[str] = []

    def build() -> str:
        calls.append("build")
        return "artifact"

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
    instance._test_calls = calls  # type: ignore[attr-defined]
    return instance


class TestACancelledScopeRefusesToAdvance:
    """AC-4."""

    def test_invoking_the_job_against_a_cancelled_scope_raises(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        app.execute("release", scope_id="rel-1")
        store = StateStore.for_project(project)
        store.set_scope_status("rel-1", "cancelled")

        with pytest.raises(ScopeCancelledError):
            app.execute("release", scope_id="rel-1")

    def test_the_status_is_not_overwritten(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """The exact regression: the walk used to run to completion and write
        `completed` over `cancelled`."""
        app.execute("release", scope_id="rel-1")
        store = StateStore.for_project(project)
        store.set_scope_status("rel-1", "cancelled")

        with pytest.raises(ScopeCancelledError):
            app.execute("release", scope_id="rel-1")

        scope = store.get_scope("rel-1")
        assert scope is not None
        assert scope["status"] == "cancelled"

    def test_no_step_runs(self, app: FunctualizeApp, project: Path) -> None:
        store = StateStore.for_project(project)
        store.ensure_scope("rel-2", "release")
        store.set_scope_status("rel-2", "cancelled")

        with pytest.raises(ScopeCancelledError):
            app.execute("release", scope_id="rel-2")

        assert app._test_calls == []  # type: ignore[attr-defined]

    def test_the_refusal_names_the_workflow_to_start_fresh(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """Terminal means terminal, so the message must carry the recovery —
        a caller that cannot reuse the id needs the job name."""
        store = StateStore.for_project(project)
        store.ensure_scope("rel-3", "release")
        store.set_scope_status("rel-3", "cancelled")

        with pytest.raises(ScopeCancelledError) as excinfo:
            app.execute("release", scope_id="rel-3")

        assert "release" in str(excinfo.value)
        assert "rel-3" in str(excinfo.value)


class TestALiveScopeIsUnaffected:
    def test_a_blocked_scope_still_advances(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """The guard must not catch the case it is not for."""
        app.execute("release", scope_id="rel-4")
        store = StateStore.for_project(project)
        assert store.get_scope("rel-4")["status"] == "blocked"

        result = app.execute("release", scope_id="rel-4")
        assert result.metadata.get("workflow_status") == "blocked"

    def test_a_fresh_scope_is_unaffected(self, app: FunctualizeApp) -> None:
        result = app.execute("release")
        assert result.metadata.get("workflow_status") == "blocked"
