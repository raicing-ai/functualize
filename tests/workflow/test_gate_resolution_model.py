"""Gate requests and recorded decisions through the workflow's public doors."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._gate import GateRegistry
from functualize.app import FunctualizeApp
from functualize.app.utils import (
    ScopeStore,
    answer_gate,
    deposit_gate_input,
    gate_draft,
)
from functualize.job import RunStatus
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow


class Approval(BaseModel):
    approved: bool
    reason: str = ""


class _Fails:
    def resolve(self, ctx: Any) -> BaseModel:
        raise RuntimeError("prompt failed")


class _Accepts:
    def resolve(self, ctx: Any) -> BaseModel:
        return Approval(approved=True, reason="resolved")


@pytest.fixture(autouse=True)
def isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield project
    AppState.reset()


def _app(*, strategy: str = "ai_outbound") -> FunctualizeApp:
    app = FunctualizeApp(name="gate-model")

    def prepare() -> str:
        return "ready"

    def finish() -> str:
        return "finished"

    @workflow(
        steps=[
            Step("prepare"),
            Gate(name="approval", awaits=Approval, strategy=strategy),
            Step("finish"),
        ],
        edges=[
            Edge("prepare", "approval"),
            Edge("approval", "finish"),
            Edge("finish", END),
        ],
    )
    def release() -> str:
        return "released"

    app.register_dynamic_job("prepare", prepare)
    app.register_dynamic_job("finish", finish)
    app.register_dynamic_job("release", release)
    return app


def _run(app: FunctualizeApp, scope_id: str = "rel-1") -> Any:
    return app.execute(
        RunRequest(
            job_name="release", surface="app.execute", workflow_scope_id=scope_id
        )
    )


def _store(project: Path) -> ScopeStore:
    return ScopeStore.for_project(project)


def _resolution(
    app: FunctualizeApp, store: ScopeStore, scope_id: str = "rel-1"
) -> dict[str, Any]:
    return gate_draft(app, store, scope_id, "approval")["resolution"]


def test_blocked_gate_has_a_minted_request_id_stable_across_resume(
    isolated_project: Path,
) -> None:
    app = _app()
    assert _run(app).status is RunStatus.BLOCKED
    store = _store(isolated_project)
    opened = _resolution(app, store)
    assert opened["request_id"]
    assert opened["request_id"] != "rel-1::approval"
    assert opened["request_status"] == "open"

    assert (
        deposit_gate_input(app, store, "rel-1", "approval", {"approved": True})[
            "request_id"
        ]
        == opened["request_id"]
    )
    assert _run(app).status is RunStatus.SUCCESS
    consumed = _resolution(app, store)
    assert consumed["request_id"] == opened["request_id"]
    assert consumed["request_status"] == "consumed"


def test_ladder_rungs_are_recorded(isolated_project: Path) -> None:
    app = _app(strategy="ai_inbound")
    app.gates.register_gate_strategy("prompt", _Fails())
    app.gates.register_gate_strategy("resolve", _Accepts())
    assert _run(app).status is RunStatus.SUCCESS
    store = _store(isolated_project)
    candidates = _resolution(app, store)["candidates"]
    assert [candidate["outcome"] for candidate in candidates] == [
        "unavailable",
        "failed",
        "accepted",
    ]
    assert [candidate["source"] for candidate in candidates] == [
        "strategy:ai_inbound",
        "strategy:prompt",
        "strategy:resolve",
    ]
    assert "functualize-ai" in candidates[0]["detail"]
    assert candidates[1]["detail"] == "prompt failed"
    assert [candidate["ordinal"] for candidate in candidates] == [0, 1, 2]
    assert len({candidate["candidate_id"] for candidate in candidates}) == 3

    # An earlier winner still leaves the later rung recorded as not reached.
    app.gates.register_gate_strategy("prompt", _Accepts())
    assert _run(app, "rel-2").status is RunStatus.SUCCESS
    assert [
        candidate["outcome"]
        for candidate in _resolution(app, store, "rel-2")["candidates"]
    ] == ["unavailable", "accepted", "not_reached"]


def test_second_ladder_run_appends_with_continuing_ordinals(
    isolated_project: Path,
) -> None:
    app = _app(strategy="ai_inbound")
    app.gates.register_gate_strategy("prompt", _Fails())
    assert _run(app).status is RunStatus.BLOCKED
    store = _store(isolated_project)
    first = _resolution(app, store)
    assert [candidate["ordinal"] for candidate in first["candidates"]] == [0, 1, 2]

    assert _run(app).status is RunStatus.BLOCKED
    second = _resolution(app, store)
    assert second["request_id"] == first["request_id"]
    assert [candidate["ordinal"] for candidate in second["candidates"]] == list(
        range(6)
    )


def test_blocked_reason_text_is_unchanged(isolated_project: Path) -> None:
    app = _app(strategy="ai_inbound")
    app.gates.register_gate_strategy("prompt", _Fails())
    first = _run(app)
    reason = first.metadata["blocked_reason"]
    assert reason == (
        "unregistered gate strategy 'ai_inbound' "
        "(install functualize-ai to register it); "
        "prompt: prompt failed; "
        "resolve: Cannot resolve model Approval from config chain: "
        "unresolved fields: ['approved']"
    )
    assert _run(app).metadata["blocked_reason"] == reason


def test_reading_a_resolution_never_revalidates(
    isolated_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app()
    assert _run(app).status is RunStatus.BLOCKED
    store = _store(isolated_project)
    answer_gate(app, store, "rel-1", "approval", {"approved": True})

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("read recomputed a recorded verdict")

    monkeypatch.setattr(Approval, "model_validate", fail)
    monkeypatch.setattr(GateRegistry, "evaluate", fail)
    report = gate_draft(app, store, "rel-1", "approval")
    assert report["resolution"]["request_status"] == "accepted"
    assert [
        candidate["outcome"] for candidate in report["resolution"]["candidates"]
    ] == ["accepted"]


def test_invalid_submission_is_recorded_and_gate_stays_open(
    isolated_project: Path,
) -> None:
    app = _app()
    assert _run(app).status is RunStatus.BLOCKED
    store = _store(isolated_project)
    result = deposit_gate_input(app, store, "rel-1", "approval", {"approved": "bad"})
    assert result["error"] == "validation_error"
    resolution = _resolution(app, store)
    assert resolution["request_status"] == "open"
    assert resolution["candidates"][0]["outcome"] == "invalid"
    assert resolution["candidates"][0]["errors"]
    assert store.get_gate("rel-1", "approval")["payload"] is None


def test_second_deposit_is_refused_not_overwritten(isolated_project: Path) -> None:
    app = _app()
    assert _run(app).status is RunStatus.BLOCKED
    store = _store(isolated_project)
    assert (
        deposit_gate_input(app, store, "rel-1", "approval", {"approved": True})[
            "status"
        ]
        == "input_accepted"
    )
    before = _resolution(app, store)
    rejected = deposit_gate_input(app, store, "rel-1", "approval", {"approved": False})
    assert rejected["error"] == "gate_already_answered"
    assert _resolution(app, store) == before
    assert store.get_gate("rel-1", "approval")["payload"]["approved"] is True


def test_reopen_supersedes_and_keeps_history(isolated_project: Path) -> None:
    app = _app()
    assert _run(app).status is RunStatus.BLOCKED
    store = _store(isolated_project)
    assert (
        answer_gate(app, store, "rel-1", "approval", {"approved": True})["status"]
        == "answered"
    )
    old_id = _resolution(app, store)["request_id"]

    reopened = answer_gate(
        app, store, "rel-1", "approval", {"approved": False}, reopen=True
    )
    assert reopened["status"] == "answered"
    current = _resolution(app, store)
    assert current["request_id"] != old_id
    assert current["candidates"][0]["ordinal"] == 0
    record = store.get_gate("rel-1", "approval")
    assert record["superseded"][0]["request_id"] == old_id
    assert record["superseded"][0]["status"] == "cancelled"
    assert record["superseded"][0]["candidates"][0]["outcome"] == "accepted"
    assert record["payload"]["approved"] is False


def test_walk_past_gate_marks_consumed_once(isolated_project: Path) -> None:
    app = _app()
    assert _run(app).status is RunStatus.BLOCKED
    store = _store(isolated_project)
    answer_gate(app, store, "rel-1", "approval", {"approved": True})
    accepted = _resolution(app, store)
    assert accepted["request_status"] == "accepted"
    assert _run(app).status is RunStatus.SUCCESS
    consumed = _resolution(app, store)
    assert consumed["request_status"] == "consumed"
    assert consumed["request_id"] == accepted["request_id"]
    consumed_at = store.get_gate("rel-1", "approval")["consumed_at"]
    assert _run(app).status is RunStatus.SUCCESS
    assert store.get_gate("rel-1", "approval")["consumed_at"] == consumed_at
    assert _resolution(app, store)["candidates"] == accepted["candidates"]


def test_legacy_gate_record_resumes_with_zero_candidates(
    isolated_project: Path,
) -> None:
    app = _app()
    assert _run(app).status is RunStatus.BLOCKED
    store = _store(isolated_project)
    scope = store.get_scope("rel-1")
    original = store.get_gate("rel-1", "approval")
    assert scope is not None and original is not None

    # Write the pre-request gate shape explicitly, as an old scopes.json would.
    scope["gates"] = {
        "approval": {
            "input_schema": original["input_schema"],
            "model": "Approval",
            "tools": [],
            "payload": {"approved": True, "reason": "legacy"},
            "blocked_at": original["blocked_at"],
        }
    }
    (isolated_project / ".functualize" / "scopes.json").write_text(
        json.dumps({"format_version": 1, "scopes": {"rel-1": scope}})
    )
    projected = _resolution(app, store)
    assert projected["request_id"] == "rel-1::approval"
    assert projected["request_status"] == "accepted"
    assert projected["candidates"] == []
    assert _run(app).status is RunStatus.SUCCESS
    assert _resolution(app, store)["candidates"] == []
    assert _resolution(app, store)["request_status"] == "consumed"
