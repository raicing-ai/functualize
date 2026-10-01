"""`answer` — partial, whole, and corrected.

A gate was all-or-nothing. Two actors could not fill different fields of one
gate, and a deposited answer could not be corrected at all: once `payload` is
non-None, `pending_gates` stops listing the gate and every addressing path
answers `gate_not_found`. Fixing a typo meant hand-editing `scopes.json`.

The invariant under all of it: only an accepted candidate writes a payload.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from functualize._app.state import AppState
from functualize._primitives import gate_requests
from functualize._types.errors import InputRequestNotOpenError
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
)
from functualize.app.core import FunctualizeApp
from functualize.app.utils import (
    ScopeStore,
    answer_gate,
    deposit_gate_input,
    gate_draft,
    resolve_gate,
)
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow


class Approval(BaseModel):
    approved: bool
    reason: str = Field(description="Why this was approved")
    reviewers: int = 1


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

    instance.register_dynamic_job("build", build)
    instance.register_dynamic_job("deploy", deploy)
    instance.register_dynamic_job("release", release)
    return instance


@pytest.fixture
def store(app: FunctualizeApp, project: Path) -> ScopeStore:
    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="rel-1")
    )
    return ScopeStore.for_project(project)


class TestPartialAnswers:
    """AC-11."""

    def test_an_incomplete_draft_is_stored_and_the_gate_stays_unanswered(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        result = answer_gate(app, store, "rel-1", "approve", {"approved": True})

        assert result["status"] == "drafted"
        assert result["draft"] == {"approved": True}
        assert store.get_gate("rel-1", "approve")["payload"] is None

    def test_it_says_what_is_missing_not_merely_that_something_is(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        result = answer_gate(app, store, "rel-1", "approve", {"approved": True})

        assert [m["field"] for m in result["missing"]] == ["reason"]
        assert result["missing"][0]["description"] == "Why this was approved"
        assert "reason" in result["message"]

    def test_two_actors_fill_different_fields(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """The story the draft exists for."""
        answer_gate(app, store, "rel-1", "approve", {"approved": True})
        result = answer_gate(app, store, "rel-1", "approve", {"reason": "signed off"})

        assert result["status"] == "answered"
        assert store.get_gate("rel-1", "approve")["payload"]["approved"] is True
        assert store.get_gate("rel-1", "approve")["payload"]["reason"] == "signed off"

    def test_replace_discards_the_accumulated_draft(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})
        result = answer_gate(
            app, store, "rel-1", "approve", {"reason": "x"}, mode="replace"
        )
        assert result["draft"] == {"reason": "x"}

    def test_unset_removes_a_field(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})
        result = answer_gate(app, store, "rel-1", "approve", unset=["approved"])
        assert result["draft"] == {}

    def test_clear_discards_everything(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})
        result = answer_gate(app, store, "rel-1", "approve", clear=True)
        assert result["draft"] == {}


class TestAutoCommit:
    """AC-12, AC-13."""

    def test_a_complete_draft_answers_the_gate_in_one_call(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """The existing one-shot flow must be unchanged."""
        result = answer_gate(
            app, store, "rel-1", "approve", {"approved": True, "reason": "ok"}
        )

        assert result["status"] == "answered"
        assert store.get_gate("rel-1", "approve")["payload"] is not None

    def test_complete_answer_records_a_candidate(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """The public answer path must reach the candidate append wire."""
        result = answer_gate(
            app,
            store,
            "rel-1",
            "approve",
            {"approved": True, "reason": "ok"},
            source="api-test",
        )

        record = store.get_gate("rel-1", "approve")
        assert result["resolution"]["request_id"] == record["request_id"]
        assert result["resolution"]["request_status"] == "accepted"
        assert result["resolution"]["candidates"] == [
            {
                "candidate_id": record["candidates"][0]["candidate_id"],
                "ordinal": 0,
                "source": "api-test",
                "submitted_at": record["candidates"][0]["submitted_at"],
                "outcome": "accepted",
                "detail": "",
                "errors": [],
            }
        ]
        assert "payload" not in result["resolution"]["candidates"][0]
        assert record["candidates"][0]["payload"] == record["payload"]

    def test_a_candidate_with_evidence_projects_an_eighth_key(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """A strategy rung's evidence rides the resolution view when present."""
        record = store.get_gate("rel-1", "approve") or {}
        gate_requests.append_candidate(
            store,
            "rel-1",
            "approve",
            GateCandidate(
                candidate_id="cand_ev",
                request_id=record["request_id"],
                ordinal=0,
                source="strategy:decision",
                submitted_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
                evaluation=CandidateEvaluation(
                    EvaluationOutcome.FAILED,
                    detail="below threshold",
                    evidence={"schema": "decision-evidence/1", "x": 1},
                ),
            ),
        )

        report = gate_draft(app, store, "rel-1", "approve")

        projected = report["resolution"]["candidates"][0]
        assert projected["evidence"] == {"schema": "decision-evidence/1", "x": 1}

    def test_the_payload_is_the_validated_dump(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """AC-10's invariant, on the draft path too — a defaulted field must be
        present, or the strategy path and this one diverge again."""
        answer_gate(app, store, "rel-1", "approve", {"approved": True, "reason": "ok"})

        assert (
            store.get_gate("rel-1", "approve")["payload"]
            == Approval(approved=True, reason="ok").model_dump()
        )
        assert store.get_gate("rel-1", "approve")["payload"]["reviewers"] == 1

    def test_committing_clears_the_draft(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})
        answer_gate(app, store, "rel-1", "approve", {"reason": "ok"})
        assert store.get_gate_draft("rel-1", "approve") is None

    def test_no_commit_leaves_a_complete_draft_uncommitted(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """For the case where a second actor must review before the gate opens."""
        result = answer_gate(
            app,
            store,
            "rel-1",
            "approve",
            {"approved": True, "reason": "ok"},
            commit=False,
        )

        assert result["status"] == "drafted"
        assert result["complete"] is True
        assert store.get_gate("rel-1", "approve")["payload"] is None

    def test_an_invalid_draft_never_commits(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        result = answer_gate(
            app, store, "rel-1", "approve", {"approved": "nope", "reason": "x"}
        )

        assert result["status"] == "drafted"
        assert [i["field"] for i in result["invalid"]] == ["approved"]
        assert store.get_gate("rel-1", "approve")["payload"] is None

    def test_a_concurrent_answer_is_a_named_refusal(
        self,
        app: FunctualizeApp,
        store: ScopeStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The port can refuse after the draft passed its initial status check."""

        def refused(*args: object, **kwargs: object) -> None:
            raise InputRequestNotOpenError("req_other", "accepted")

        monkeypatch.setattr(gate_requests, "append_candidate", refused)
        result = answer_gate(
            app, store, "rel-1", "approve", {"approved": True, "reason": "ok"}
        )
        assert result["error"] == "gate_already_answered"
        assert store.get_gate("rel-1", "approve")["payload"] is None


class TestReopen:
    """AC-14."""

    def test_a_gate_still_parked_at_can_be_reopened(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        answer_gate(
            app, store, "rel-1", "approve", {"approved": True, "reason": "typo"}
        )
        original = store.get_gate("rel-1", "approve")
        original_request_id = original["request_id"]

        result = answer_gate(
            app, store, "rel-1", "approve", {"reason": "corrected"}, reopen=True
        )

        assert result["status"] == "answered"
        record = store.get_gate("rel-1", "approve")
        assert record["payload"]["reason"] == "corrected"
        assert record["request_id"] != original_request_id
        assert record["candidates"][0]["ordinal"] == 0
        assert record["superseded"][0]["request_id"] == original_request_id
        assert record["superseded"][0]["status"] == "cancelled"
        assert record["superseded"][0]["cancel_reason"] == "reopened"
        assert record["superseded"][0]["payload"]["reason"] == "typo"

    def test_a_gate_the_walk_has_passed_refuses(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """The walker records the gate as replayed and advances past it, so the
        answer already produced the results recorded after it."""
        answer_gate(app, store, "rel-1", "approve", {"approved": True, "reason": "ok"})
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-1"
            )
        )  # walk past the gate

        result = answer_gate(
            app, store, "rel-1", "approve", {"reason": "x"}, reopen=True
        )

        assert result["error"] == "gate_already_consumed"

    def test_the_refusal_names_the_position(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """So the refusal is checkable rather than merely asserted."""
        answer_gate(app, store, "rel-1", "approve", {"approved": True, "reason": "ok"})
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-1"
            )
        )

        result = answer_gate(app, store, "rel-1", "approve", reopen=True)
        assert "position" in result

    def test_reopening_an_unanswered_gate_errors(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        result = answer_gate(app, store, "rel-1", "approve", reopen=True)
        assert result["error"] == "gate_not_answered"

    def test_answering_an_answered_gate_without_reopen_refuses(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """Not a silent overwrite: an answered gate is out of the pending set on
        every surface, so a caller editing it is working from a stale view."""
        answer_gate(app, store, "rel-1", "approve", {"approved": True, "reason": "ok"})

        result = answer_gate(app, store, "rel-1", "approve", {"reason": "x"})
        assert result["error"] == "gate_already_answered"


class TestTheDraftReport:
    """AC-15."""

    def test_it_reports_every_field(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})

        report = gate_draft(app, store, "rel-1", "approve")

        assert report["draft"] == {"approved": True}
        assert report["satisfied"] == ["approved"]
        assert [m["field"] for m in report["missing"]] == ["reason"]
        assert report["invalid"] == []
        assert report["complete"] is False
        assert report["answered"] is False
        assert report["resolution"]["request_status"] == "open"
        assert report["resolution"]["candidates"] == []

    def test_resolution_reads_recorded_verdict_without_revalidating(
        self,
        app: FunctualizeApp,
        store: ScopeStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True, "reason": "ok"})

        def refuse_validation(*args: object, **kwargs: object) -> None:
            raise AssertionError("resolution read revalidated the answer")

        monkeypatch.setattr(Approval, "model_validate", refuse_validation)
        report = gate_draft(app, store, "rel-1", "approve")
        assert report["resolution"]["candidates"][0]["outcome"] == "accepted"

    def test_missing_and_invalid_come_from_the_commit_paths_own_errors(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """So --show cannot describe a draft the commit would treat differently."""
        answer_gate(app, store, "rel-1", "approve", {"reviewers": "not-a-number"})

        report = gate_draft(app, store, "rel-1", "approve")
        assert {m["field"] for m in report["missing"]} == {"approved", "reason"}
        assert [i["field"] for i in report["invalid"]] == ["reviewers"]


class TestDepositedCandidates:
    def test_invalid_input_is_recorded_without_answering(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        result = deposit_gate_input(
            app, store, "rel-1", "approve", {"approved": "invalid"}, source="api-test"
        )

        assert result["error"] == "validation_error"
        assert result["gate"] == "approve"
        record = store.get_gate("rel-1", "approve")
        assert record["status"] == "open"
        assert record["payload"] is None
        assert record["candidates"][0]["outcome"] == "invalid"
        assert record["candidates"][0]["source"] == "api-test"
        assert record["candidates"][0]["errors"]

    def test_valid_input_appends_after_invalid_and_returns_request_id(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        deposit_gate_input(app, store, "rel-1", "approve", {"approved": "invalid"})
        result = deposit_gate_input(
            app, store, "rel-1", "approve", {"approved": True, "reason": "ok"}
        )

        record = store.get_gate("rel-1", "approve")
        assert result["status"] == "input_accepted"
        assert result["request_id"] == record["request_id"]
        assert [c["ordinal"] for c in record["candidates"]] == [0, 1]
        assert [c["outcome"] for c in record["candidates"]] == [
            "invalid",
            "accepted",
        ]

    def test_a_second_deposit_is_refused_without_overwriting(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        deposit_gate_input(
            app, store, "rel-1", "approve", {"approved": True, "reason": "first"}
        )
        result = deposit_gate_input(
            app, store, "rel-1", "approve", {"approved": True, "reason": "second"}
        )

        assert result["error"] == "gate_already_answered"
        record = store.get_gate("rel-1", "approve")
        assert record["payload"]["reason"] == "first"
        assert len(record["candidates"]) == 1


class TestJointAddressing:
    """The hole where `resume_gate` took a gate, `resume_workflow` took a scope,
    and each referred the caller to the other."""

    def test_both_identifiers_are_accepted(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        assert resolve_gate(store, "rel-1", "approve") == ("rel-1", "approve")

    def test_the_gate_may_be_omitted_when_unambiguous(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        assert resolve_gate(store, "rel-1", None) == ("rel-1", "approve")

    def test_the_scope_may_be_omitted_when_unambiguous(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        assert resolve_gate(store, None, "approve") == ("rel-1", "approve")

    def test_neither_is_needed_when_there_is_exactly_one(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        assert resolve_gate(store, None, None) == ("rel-1", "approve")

    def test_several_candidates_are_listed_never_guessed(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        """Never "newest wins" — `blocked_at` resets on every re-block, so it
        is not computable anyway."""
        app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-2"
            )
        )

        result = resolve_gate(store, None, "approve")

        assert result["error"] == "ambiguous_gate"
        assert {c["workflow_id"] for c in result["candidates"]} == {"rel-1", "rel-2"}

    def test_no_candidates_names_the_survey_verb(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        result = resolve_gate(store, None, "nope")
        assert result["error"] == "gate_not_found"
        assert "workflow list" in result["message"]

    def test_an_unknown_scope_is_not_found(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        assert resolve_gate(store, "nope", None)["error"] == "workflow_not_found"
