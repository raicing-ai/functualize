"""A gate answers to the name it was declared with (T4: the resolver).

`Gate(name="approve_refund", …)` canonicalizes to the node name
`approve-refund`, and the walk reports the canonical form. Until this change,
addressing the gate by the declared spelling missed: the raw string never
matched the canonical key, and the failure surfaced as an `AttributeError`
wrapped in a returned error value a caller could ignore.

The resolver here is the one every public gate entry calls first; this file
grows with each entry the later tasks of the feature wire to it.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._primitives import gate_requests
from functualize.app._workflow_resume import _canonical_gate, _resolve_gate_model
from functualize.app.core import FunctualizeApp
from functualize.app.utils import (
    GateNotFoundError,
    ScopeStore,
    answer_gate,
    deposit_gate_input,
    gate_draft,
    list_scopes,
    resolve_gate,
    resume_scope,
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
        return "artifact"

    def deploy() -> str:
        return "deployed"

    @workflow(
        steps=[
            Step("build"),
            Gate(name="approve_refund", awaits=Approval),
            Step("deploy"),
        ],
        edges=[
            Edge(source="build", target="approve_refund"),
            Edge(source="approve_refund", target="deploy"),
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


_KNOWN = ["approve-refund"]


class TestCanonicalGate:
    """The pure resolver: declared spelling, canonical spelling, or raise."""

    def test_exact_match_wins(self) -> None:
        assert _canonical_gate(_KNOWN, "approve-refund", scope_id="rel-1") == (
            "approve-refund"
        )

    def test_the_python_spelling_reaches_the_canonical_gate(self) -> None:
        assert _canonical_gate(_KNOWN, "approve_refund", scope_id="rel-1") == (
            "approve-refund"
        )

    def test_the_camel_spelling_reaches_the_canonical_gate(self) -> None:
        assert _canonical_gate(_KNOWN, "approveRefund", scope_id="rel-1") == (
            "approve-refund"
        )

    def test_the_title_spelling_reaches_the_canonical_gate(self) -> None:
        assert _canonical_gate(_KNOWN, "Approve_Refund", scope_id="rel-1") == (
            "approve-refund"
        )

    def test_an_unknown_reference_raises_with_the_known_gates(self) -> None:
        with pytest.raises(GateNotFoundError) as raised:
            _canonical_gate(_KNOWN, "nope", scope_id="rel-1")

        assert raised.value.known == ("approve-refund",)
        assert raised.value.scope_id == "rel-1"

    def test_no_known_gates_at_all_raises_with_an_empty_roster(self) -> None:
        with pytest.raises(GateNotFoundError) as raised:
            _canonical_gate([], "nope", scope_id="rel-1")

        assert raised.value.known == ()

    def test_a_dotted_miss_raises_rather_than_matching_the_last_segment(self) -> None:
        with pytest.raises(GateNotFoundError):
            _canonical_gate(_KNOWN, "x.approve_refund", scope_id="rel-1")


class TestDeposit:
    """The first wired entry: deposit resolves before it records."""

    def test_the_declared_spelling_is_accepted_and_canonicalized(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        result = deposit_gate_input(
            app, store, "rel-1", "approve_refund", {"approved": True}
        )

        assert result["status"] == "input_accepted"
        assert result["gate"] == "approve-refund"
        record = store.get_gate("rel-1", "approve-refund")
        assert record is not None and record["payload"] == {"approved": True}

    def test_an_unknown_reference_raises_and_records_nothing(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        record = store.get_gate("rel-1", "approve-refund")
        assert record is not None
        before = [c.candidate_id for c in gate_requests.candidates_for(record)]

        with pytest.raises(GateNotFoundError) as raised:
            deposit_gate_input(app, store, "rel-1", "nope", {"approved": True})

        assert raised.value.scope_id == "rel-1"
        after = store.get_gate("rel-1", "approve-refund")
        assert after is not None
        assert [c.candidate_id for c in gate_requests.candidates_for(after)] == before
        assert after["payload"] is None


class TestModelLookup:
    """Declaration drift is not a caller typo, and unreadable is not missing."""

    def test_a_gate_the_declaration_dropped_is_drift_not_a_traceback(
        self, app: FunctualizeApp
    ) -> None:
        scope = {
            "workflow": "release",
            "gates": {"ghost-gate": {"payload": None}},
        }

        _model, error = _resolve_gate_model(app, scope, "ghost-gate")

        assert error is not None
        assert error["error"] == "gate_unresolvable"
        assert "no longer declares" in error["message"]
        assert "AttributeError" not in error["message"]

    def test_a_workflow_that_will_not_load_is_unresolvable(
        self, app: FunctualizeApp
    ) -> None:
        scope = {
            "workflow": "not-a-registered-job",
            "gates": {"approve-refund": {"payload": None}},
        }

        _model, error = _resolve_gate_model(app, scope, "approve-refund")

        assert error is not None
        assert error["error"] == "gate_unresolvable"


_SPELLINGS = ["approve-refund", "approve_refund", "approveRefund", "Approve_Refund"]


class TestResolveGate:
    """The addressing half: every spelling resolves, and a miss is loud."""

    @pytest.mark.parametrize("spelling", _SPELLINGS)
    def test_both_named_resolves_every_spelling(
        self, store: ScopeStore, spelling: str
    ) -> None:
        assert resolve_gate(store, "rel-1", spelling) == ("rel-1", "approve-refund")

    @pytest.mark.parametrize("spelling", _SPELLINGS)
    def test_gate_only_scan_resolves_every_spelling(
        self, store: ScopeStore, spelling: str
    ) -> None:
        assert resolve_gate(store, None, spelling) == ("rel-1", "approve-refund")

    def test_both_named_unknown_raises(self, store: ScopeStore) -> None:
        with pytest.raises(GateNotFoundError):
            resolve_gate(store, "rel-1", "nope")

    def test_gate_only_unknown_keeps_the_survey_envelope(
        self, store: ScopeStore
    ) -> None:
        """A search across scopes never raises: the gate may exist, answered,
        somewhere this search cannot see."""
        result = resolve_gate(store, None, "nope")

        assert isinstance(result, dict)
        assert result["error"] == "gate_not_found"
        assert "workflow list" in result["message"]


class TestAnswerGate:
    def test_the_declared_spelling_answers_and_the_walk_resumes(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        result = answer_gate(app, store, "rel-1", "approve_refund", {"approved": True})

        assert result["status"] == "answered"
        assert result["gate"] == "approve-refund"

        resumed = resume_scope(app, store, "rel-1")
        assert resumed["status"] == "success"
        scope = store.get_scope("rel-1")
        assert scope is not None
        assert any(
            key.split("::", 1)[0] == "deploy" for key in scope.get("steps") or {}
        )

    def test_an_unknown_reference_raises_and_leaves_the_draft_alone(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        assert store.get_gate_draft("rel-1", "approve-refund") is None

        with pytest.raises(GateNotFoundError):
            answer_gate(app, store, "rel-1", "nope", {"approved": True})

        assert store.get_gate_draft("rel-1", "approve-refund") is None


class TestGateDraft:
    def test_the_declared_spelling_drafts(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        result = gate_draft(app, store, "rel-1", "approve_refund")

        assert "error" not in result
        assert result["gate"] == "approve-refund"

    def test_an_unknown_reference_raises(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        with pytest.raises(GateNotFoundError):
            gate_draft(app, store, "rel-1", "nope")

    def test_an_unknown_scope_is_workflow_not_found(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        result = gate_draft(app, store, "nope", "approve_refund")

        assert result["error"] == "workflow_not_found"


def test_resume_scope_answers_by_declared_name(
    app: FunctualizeApp, store: ScopeStore
) -> None:
    resumed = resume_scope(
        app, store, "rel-1", input={"approved": True}, gate="approve_refund"
    )

    assert resumed["status"] == "success"


def test_resume_scope_with_an_unknown_gate_raises(
    app: FunctualizeApp, store: ScopeStore
) -> None:
    with pytest.raises(GateNotFoundError):
        resume_scope(app, store, "rel-1", input={"approved": True}, gate="nope")


class TestListScopes:
    """The survey filter resolves the same way and never raises."""

    def test_blocked_on_resolves_the_declared_spelling(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        rows = list_scopes(app, store, blocked_on="approve_refund")
        assert [row["workflow_id"] for row in rows] == ["rel-1"]

    def test_blocked_on_resolves_the_canonical_spelling(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        rows = list_scopes(app, store, blocked_on="approve-refund")
        assert [row["workflow_id"] for row in rows] == ["rel-1"]

    def test_blocked_on_unknown_returns_no_rows(
        self, app: FunctualizeApp, store: ScopeStore
    ) -> None:
        assert list_scopes(app, store, blocked_on="nope") == []
