"""`answer` — partial, whole, and corrected.

A gate was all-or-nothing. Two actors could not fill different fields of one
gate, and a deposited answer could not be corrected at all: once `payload` is
non-None, `pending_gates` stops listing the gate and every addressing path
answers `gate_not_found`. Fixing a typo meant hand-editing `scopes.json`.

The invariant under all of it: `payload` is non-null **iff** it is the output of
a complete, successful `model(**draft.values).model_dump()`.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.app.utils import (
    StateStore,
    answer_gate,
    gate_draft,
    resolve_gate,
)
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
def store(app: FunctualizeApp, project: Path) -> StateStore:
    app.execute("release", scope_id="rel-1")
    return StateStore.for_project(project)


class TestPartialAnswers:
    """AC-11."""

    def test_an_incomplete_draft_is_stored_and_the_gate_stays_unanswered(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        result = answer_gate(app, store, "rel-1", "approve", {"approved": True})

        assert result["status"] == "drafted"
        assert result["draft"] == {"approved": True}
        assert store.get_gate("rel-1", "approve")["payload"] is None

    def test_it_says_what_is_missing_not_merely_that_something_is(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        result = answer_gate(app, store, "rel-1", "approve", {"approved": True})

        assert [m["field"] for m in result["missing"]] == ["reason"]
        assert result["missing"][0]["description"] == "Why this was approved"
        assert "reason" in result["message"]

    def test_two_actors_fill_different_fields(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """The story the draft exists for."""
        answer_gate(app, store, "rel-1", "approve", {"approved": True})
        result = answer_gate(app, store, "rel-1", "approve", {"reason": "signed off"})

        assert result["status"] == "answered"
        assert store.get_gate("rel-1", "approve")["payload"]["approved"] is True
        assert store.get_gate("rel-1", "approve")["payload"]["reason"] == "signed off"

    def test_replace_discards_the_accumulated_draft(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})
        result = answer_gate(
            app, store, "rel-1", "approve", {"reason": "x"}, mode="replace"
        )
        assert result["draft"] == {"reason": "x"}

    def test_unset_removes_a_field(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})
        result = answer_gate(app, store, "rel-1", "approve", unset=["approved"])
        assert result["draft"] == {}

    def test_clear_discards_everything(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})
        result = answer_gate(app, store, "rel-1", "approve", clear=True)
        assert result["draft"] == {}


class TestAutoCommit:
    """AC-12, AC-13."""

    def test_a_complete_draft_answers_the_gate_in_one_call(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """The existing one-shot flow must be unchanged."""
        result = answer_gate(
            app, store, "rel-1", "approve", {"approved": True, "reason": "ok"}
        )

        assert result["status"] == "answered"
        assert store.get_gate("rel-1", "approve")["payload"] is not None

    def test_the_payload_is_the_validated_dump(
        self, app: FunctualizeApp, store: StateStore
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
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})
        answer_gate(app, store, "rel-1", "approve", {"reason": "ok"})
        assert store.get_gate_draft("rel-1", "approve") is None

    def test_no_commit_leaves_a_complete_draft_uncommitted(
        self, app: FunctualizeApp, store: StateStore
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
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        result = answer_gate(
            app, store, "rel-1", "approve", {"approved": "nope", "reason": "x"}
        )

        assert result["status"] == "drafted"
        assert [i["field"] for i in result["invalid"]] == ["approved"]
        assert store.get_gate("rel-1", "approve")["payload"] is None


class TestReopen:
    """AC-14."""

    def test_a_gate_still_parked_at_can_be_reopened(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        answer_gate(
            app, store, "rel-1", "approve", {"approved": True, "reason": "typo"}
        )

        result = answer_gate(
            app, store, "rel-1", "approve", {"reason": "corrected"}, reopen=True
        )

        assert result["status"] == "answered"
        assert store.get_gate("rel-1", "approve")["payload"]["reason"] == "corrected"

    def test_a_gate_the_walk_has_passed_refuses(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """The walker records the gate as replayed and advances past it, so the
        answer already produced the results recorded after it."""
        answer_gate(app, store, "rel-1", "approve", {"approved": True, "reason": "ok"})
        app.execute("release", scope_id="rel-1")  # walk past the gate

        result = answer_gate(
            app, store, "rel-1", "approve", {"reason": "x"}, reopen=True
        )

        assert result["error"] == "gate_already_consumed"

    def test_the_refusal_names_the_position(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """So the refusal is checkable rather than merely asserted."""
        answer_gate(app, store, "rel-1", "approve", {"approved": True, "reason": "ok"})
        app.execute("release", scope_id="rel-1")

        result = answer_gate(app, store, "rel-1", "approve", reopen=True)
        assert "position" in result

    def test_reopening_an_unanswered_gate_errors(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        result = answer_gate(app, store, "rel-1", "approve", reopen=True)
        assert result["error"] == "gate_not_answered"

    def test_answering_an_answered_gate_without_reopen_refuses(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """Not a silent overwrite: an answered gate is out of the pending set on
        every surface, so a caller editing it is working from a stale view."""
        answer_gate(app, store, "rel-1", "approve", {"approved": True, "reason": "ok"})

        result = answer_gate(app, store, "rel-1", "approve", {"reason": "x"})
        assert result["error"] == "gate_already_answered"


class TestTheDraftReport:
    """AC-15."""

    def test_it_reports_every_field(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        answer_gate(app, store, "rel-1", "approve", {"approved": True})

        report = gate_draft(app, store, "rel-1", "approve")

        assert report["draft"] == {"approved": True}
        assert report["satisfied"] == ["approved"]
        assert [m["field"] for m in report["missing"]] == ["reason"]
        assert report["invalid"] == []
        assert report["complete"] is False
        assert report["answered"] is False

    def test_missing_and_invalid_come_from_the_commit_paths_own_errors(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """So --show cannot describe a draft the commit would treat differently."""
        answer_gate(app, store, "rel-1", "approve", {"reviewers": "not-a-number"})

        report = gate_draft(app, store, "rel-1", "approve")
        assert {m["field"] for m in report["missing"]} == {"approved", "reason"}
        assert [i["field"] for i in report["invalid"]] == ["reviewers"]


class TestJointAddressing:
    """The hole where `resume_gate` took a gate, `resume_workflow` took a scope,
    and each referred the caller to the other."""

    def test_both_identifiers_are_accepted(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        assert resolve_gate(store, "rel-1", "approve") == ("rel-1", "approve")

    def test_the_gate_may_be_omitted_when_unambiguous(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        assert resolve_gate(store, "rel-1", None) == ("rel-1", "approve")

    def test_the_scope_may_be_omitted_when_unambiguous(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        assert resolve_gate(store, None, "approve") == ("rel-1", "approve")

    def test_neither_is_needed_when_there_is_exactly_one(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        assert resolve_gate(store, None, None) == ("rel-1", "approve")

    def test_several_candidates_are_listed_never_guessed(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        """Never "newest wins" — `blocked_at` resets on every re-block, so it
        is not computable anyway."""
        app.execute("release", scope_id="rel-2")

        result = resolve_gate(store, None, "approve")

        assert result["error"] == "ambiguous_gate"
        assert {c["workflow_id"] for c in result["candidates"]} == {"rel-1", "rel-2"}

    def test_no_candidates_names_the_survey_verb(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        result = resolve_gate(store, None, "nope")
        assert result["error"] == "gate_not_found"
        assert "workflow list" in result["message"]

    def test_an_unknown_scope_is_not_found(
        self, app: FunctualizeApp, store: StateStore
    ) -> None:
        assert resolve_gate(store, "nope", None)["error"] == "workflow_not_found"
