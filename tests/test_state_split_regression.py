"""The defect this feature exists to remove, as a regression test.

Before the split, this sequence returned ``scopes: []`` and
``gate payload survived? False`` — no error, no warning, no backup. The
transcript is in the shape intent's evidence directory; this is it, executable.

Two ordinary actions destroyed every in-flight run:

1. a ``format_version`` bump, which is what a release does, followed by any
   unrelated write;
2. ``func builtin state clear``, whose help text named only "fingerprints,
   history".

Neither can now.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._primitives.fresh_format import FRESH_FILENAME
from functualize._primitives.fresh_store import FreshStore
from functualize._primitives.scope_format import SCOPES_FILENAME
from functualize.app.core import FunctualizeApp
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow


def _blocked_run(root):
    """A blocked release pipeline holding a human's recorded approval."""
    store = FreshStore.for_project(root)
    store.scopes.ensure_scope("rel-1", "release")
    store.scopes.set_scope_status("rel-1", "blocked")
    store.scopes.set_position("rel-1", "approve")
    store.scopes.record_step(
        "rel-1", "build::", {"status": "success", "return_value": "v2"}
    )
    store.scopes.record_branch("rel-1", "check", "deploy")
    store.scopes.put_gate(
        "rel-1",
        "approve",
        {"model": "", "input_schema": {}, "payload": {"approved_by": "sam"}},
    )
    store.put_fingerprint("build::h::checksum", {"n": 1})
    return store


class TestVersionBumpNoLongerErasesRuns:
    """§1.1 of the spec, verbatim. AC-3."""

    @pytest.mark.json_substrate
    def test_a_derived_version_bump_leaves_the_run_intact(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        store = _blocked_run(tmp_path)
        state_path = tmp_path / ".functualize" / FRESH_FILENAME

        assert store.scopes.scope_ids() == ["rel-1"]

        # Bump the derived store's format version, exactly as a release would.
        raw = json.loads(state_path.read_text())
        raw["format_version"] = 999
        state_path.write_text(json.dumps(raw))

        # One write that has nothing to do with workflows. This is what used to
        # persist the empty envelope over the top of every scope.
        store.put_fingerprint("unrelated::h::checksum", {"n": 2})

        assert store.scopes.scope_ids() == ["rel-1"]
        gate = store.scopes.get_gate("rel-1", "approve")
        assert gate is not None
        assert gate["payload"] == {"approved_by": "sam"}

    @pytest.mark.json_substrate
    def test_the_derived_state_is_still_discarded_as_designed(self, tmp_path) -> None:
        """The old rule is correct *for derived data* and must survive."""
        (tmp_path / ".functualize").mkdir()
        store = _blocked_run(tmp_path)
        state_path = tmp_path / ".functualize" / FRESH_FILENAME

        raw = json.loads(state_path.read_text())
        raw["format_version"] = 999
        state_path.write_text(json.dumps(raw))
        store.put_fingerprint("unrelated::h::checksum", {"n": 2})

        assert store.get_fingerprint("build::h::checksum") is None

    @pytest.mark.json_substrate
    def test_the_whole_walk_state_survives_not_just_the_payload(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        store = _blocked_run(tmp_path)
        state_path = tmp_path / ".functualize" / FRESH_FILENAME

        raw = json.loads(state_path.read_text())
        raw["format_version"] = 999
        state_path.write_text(json.dumps(raw))
        store.put_fingerprint("unrelated::h::checksum", {"n": 2})

        scope = store.scopes.get_scope("rel-1")
        assert scope is not None
        assert scope["status"] == "blocked"
        assert scope["position"] == "approve"
        assert scope["workflow"] == "release"
        assert store.scopes.get_step("rel-1", "build::") == {
            "status": "success",
            "return_value": "v2",
        }
        assert store.scopes.get_branch("rel-1", "check") == "deploy"


class TestClearNoLongerErasesRuns:
    """§1.2. AC-7."""

    def test_clearing_fingerprints_keeps_the_run(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        store = _blocked_run(tmp_path)

        store.clear()

        assert store.get_fingerprint("build::h::checksum") is None
        assert store.scopes.scope_ids() == ["rel-1"]
        gate = store.scopes.get_gate("rel-1", "approve")
        assert gate is not None
        assert gate["payload"] == {"approved_by": "sam"}


class TestTheTwoFilesAreReallySeparate:
    @pytest.mark.json_substrate
    def test_scopes_are_not_written_into_the_state_file(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        _blocked_run(tmp_path)
        raw = json.loads((tmp_path / ".functualize" / FRESH_FILENAME).read_text())
        assert "scopes" not in raw

    @pytest.mark.json_substrate
    def test_fingerprints_are_not_written_into_the_scope_file(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        _blocked_run(tmp_path)
        raw = json.loads((tmp_path / ".functualize" / SCOPES_FILENAME).read_text())
        assert set(raw) == {"format_version", "scopes"}

    @pytest.mark.json_substrate
    def test_the_two_versions_are_independent(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        _blocked_run(tmp_path)
        state = json.loads((tmp_path / ".functualize" / FRESH_FILENAME).read_text())
        scopes = json.loads((tmp_path / ".functualize" / SCOPES_FILENAME).read_text())
        assert "format_version" in state
        assert "format_version" in scopes


class Approval(BaseModel):
    approved: bool


def _gated_workflow_app(calls: list[str] | None = None) -> FunctualizeApp:
    """A real workflow that blocks at a gate, resolved from cwd."""
    seen = calls if calls is not None else []
    app = FunctualizeApp(name="testapp")

    def build() -> str:
        seen.append("build")
        return "artifact-v2"

    @workflow(
        steps=[
            Step("build"),
            Gate(name="approve", awaits=Approval),
        ],
        edges=[
            Edge(source="build", target="approve"),
            Edge(source="approve", target=END),
        ],
    )
    def release() -> str:
        return "shipped"

    app.register_dynamic_job("build", build)
    app.register_dynamic_job("release", release)
    return app


def _resume_release(app: FunctualizeApp, scope_id: str = "rel-1"):
    """Resume `release` in an existing scope.

    The scope is a **control input**, not a job argument, so it is named on the
    request. The old `app.execute("release", scope_id=...)` keyword was the
    accidental channel spec 1.6a closed (T15): a payload key spelled
    `scope_id` chose the scope the run joined. `request_for` would put it back
    in `kwargs`, where it would arrive as an argument the job does not take.
    """
    return app.execute(
        RunRequest(
            job_name="release", surface="app.execute", workflow_scope_id=scope_id
        )
    )


class TestBlockedRunResumesAcrossTheSplit:
    """AC-12, AC-13. The end-to-end version: a real walk, blocked, resumed."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        AppState.reset()
        yield
        AppState.reset()

    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        root = tmp_path / "project"
        (root / ".functualize").mkdir(parents=True)
        monkeypatch.chdir(root)
        return root

    @pytest.fixture
    def app(self, project):
        return _gated_workflow_app()

    def test_a_gate_blocks_and_records_its_scope(self, app, project) -> None:
        result = _resume_release(app)
        assert result.metadata.get("workflow_status") == "blocked"

        store = FreshStore.for_project(project)
        scope = store.scopes.get_scope("rel-1")
        assert scope is not None
        assert scope["status"] == "blocked"

    @pytest.mark.json_substrate
    def test_the_blocked_scope_lives_in_the_scope_file(self, app, project) -> None:
        _resume_release(app)
        raw = json.loads((project / ".functualize" / SCOPES_FILENAME).read_text())
        assert "rel-1" in raw["scopes"]

    def test_completed_steps_replay_rather_than_rerun(self, project) -> None:
        """AC-12. Counted, not inferred from the record: the walk rewrites a
        replayed step's `completed_at` without re-executing it, so comparing
        records would assert the wrong thing. What matters is that the body
        runs once."""
        calls: list[str] = []
        app = _gated_workflow_app(calls)

        _resume_release(app)
        assert calls == ["build"]

        _resume_release(app)
        assert calls == ["build"], "the completed step re-executed on resume"

        store = FreshStore.for_project(project)
        recorded = store.scopes.get_step("rel-1", "build::")
        assert recorded is not None
        assert recorded["status"] == "success"
        assert recorded["return_value"] == "artifact-v2"

    def test_clearing_derived_state_between_runs_does_not_restart_the_walk(
        self, app, project
    ) -> None:
        """The operator story: clear stale fingerprints, keep the run."""
        _resume_release(app)
        store = FreshStore.for_project(project)

        store.clear()

        scope = store.scopes.get_scope("rel-1")
        assert scope is not None
        assert scope["status"] == "blocked"
        assert store.scopes.get_step("rel-1", "build::") is not None
