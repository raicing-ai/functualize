"""One answer path, two record seams — the selected store serves the verbs.

Row 3.1 of the gate-interactions-outbox feature. The production call path
these tests drive is the public door every surface uses::

    functualize.app.utils.answer_gate / gate_draft / resolve_gate
    → _workflow_answer (one flow, two seams)
    → document seam: gate_requests candidate + decision on the gate record
    → port seam:      store.transaction(): inputs.append + inputs.decide
                                          + effects.append (durable_outbox only)
    → after the commit: _app.effects.drain → receiver (at-least-once)

The app is real and the walk is real: executing the workflow blocks on the
gate over the *selected* store, exactly as a user's run does, and the answers
then go through the same doors the CLI and MCP are wired to.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from functualize_substrate_sqlite import SQLiteSubstratePlugin
from pydantic import BaseModel, Field

from functualize._app.state import AppState
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._primitives.scope_store import ScopeStore
from functualize._types.errors import GateNotFoundError
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.app.core import FunctualizeApp
from functualize.app.utils import (
    answer_gate,
    gate_draft,
    resolve_gate,
    selected_workflow_store,
)
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Gate, Step, workflow

if TYPE_CHECKING:
    from functualize._types.persistence import EffectView


class Approval(BaseModel):
    approved: bool
    reason: str = Field(description="Why this was approved")
    reviewers: int = 1


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


class Receiver:
    """An `EffectReceiver` that records what the drain delivered."""

    topic = "gate.accepted"

    def __init__(self) -> None:
        self.received: list[EffectView] = []

    def receive(self, effect: EffectView) -> None:
        self.received.append(effect)


class ReceiverPlugin:
    """Registers its receiver the way a consumer package does, at registration."""

    version = "0.1.0"
    description = "Registers an effect receiver."
    name = "receiver-plugin"

    def __init__(self, receiver: Any) -> None:
        self._receiver = receiver

    def __call__(self, app: Any) -> None:
        app.extensions.register_effect_receiver(self._receiver)


@pytest.fixture(autouse=True)
def _reset() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


def _app(tmp_path: Path, url: str, *plugins: object) -> FunctualizeApp:

    defaults: dict[str, Any] = {"runtime_store": {"url": url}}
    config = ConfigSources(
        config_resolution_chain=ResolutionChain([DefaultSource(defaults)])
    )
    sources = PluginSources(entry_point_group="", explicit_plugins=list(plugins))
    jobs = JobSources(functions=[build, deploy, release])
    return FunctualizeApp(
        "answers", job_sources=jobs, config_sources=config, plugin_sources=sources
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root


def _blocked_at_gate(app: FunctualizeApp) -> None:
    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="rel-1")
    )


def test_the_selected_store_serves_the_draft_report_and_the_resolution(
    project: Path, tmp_path: Path
) -> None:
    """Addressing, the draft report and the causal identity, off the port."""
    receiver = Receiver()
    app = _app(
        tmp_path,
        f"sqlite://{tmp_path / 'state.db'}",
        SQLiteSubstratePlugin(),
        ReceiverPlugin(receiver),
    )
    _blocked_at_gate(app)
    store = selected_workflow_store(app)

    assert resolve_gate(store, "rel-1", None) == ("rel-1", "approve")
    assert resolve_gate(store, None, "approve") == ("rel-1", "approve")

    report = gate_draft(app, store, "rel-1", "approve")
    assert report["model"] == "Approval"
    assert report["draft"] == {}
    assert [entry["field"] for entry in report["missing"]] == ["approved", "reason"]
    assert report["resolution"]["request_status"] == "open"
    assert report["resolution"]["candidates"] == []
    causal = report["resolution"]["causal"]
    assert causal["workflow_id"] == "rel-1"
    assert causal["step"] == "approve"
    assert causal["run_id"] is not None


def test_a_partial_answer_is_a_recorded_candidate_the_next_one_continues(
    project: Path, tmp_path: Path
) -> None:
    """A relational store records drafts only as submissions (spec §3.5)."""
    receiver = Receiver()
    app = _app(
        tmp_path,
        f"sqlite://{tmp_path / 'state.db'}",
        SQLiteSubstratePlugin(),
        ReceiverPlugin(receiver),
    )
    _blocked_at_gate(app)
    store = selected_workflow_store(app)

    drafted = answer_gate(app, store, "rel-1", "approve", {"approved": True})

    assert drafted["status"] == "drafted"
    assert drafted["draft"] == {"approved": True}
    request = store.inputs.for_gate("rel-1", "approve")
    assert request is not None and request.status == "open"
    [candidate] = store.inputs.candidates_for(request.request_id)
    assert candidate.evaluation.outcome.value == "invalid"
    assert candidate.payload == {"approved": True}
    assert candidate.channel == "api"
    assert candidate.resolver_class == "program"
    assert candidate.schema_id.endswith("Approval")
    assert candidate.payload_hash.startswith("sha256:")
    assert store.inputs.decision(request.request_id) is None
    # An invalid submission publishes nothing: no intent, no delivery.
    assert receiver.received == []

    answered = answer_gate(app, store, "rel-1", "approve", {"reason": "signed off"})

    assert answered["status"] == "answered"
    candidates = store.inputs.candidates_for(request.request_id)
    assert len(candidates) == 2
    assert candidates[1].supersedes_candidate_id == candidates[0].candidate_id
    # The second submission continued the first one's payload — the draft is
    # the newest non-accepted candidate's payload.
    assert (
        candidates[1].payload
        == Approval(approved=True, reason="signed off").model_dump()
    )
    assert store.inputs.for_gate("rel-1", "approve").status == "accepted"


def test_the_acceptance_carries_its_decision_and_drains_after_commit(
    project: Path, tmp_path: Path
) -> None:
    """Decision and intent in one unit; the dispatcher runs after it commits."""
    receiver = Receiver()
    app = _app(
        tmp_path,
        f"sqlite://{tmp_path / 'state.db'}",
        SQLiteSubstratePlugin(),
        ReceiverPlugin(receiver),
    )
    _blocked_at_gate(app)
    store = selected_workflow_store(app)
    answer_gate(app, store, "rel-1", "approve", {"approved": True})
    answered = answer_gate(app, store, "rel-1", "approve", {"reason": "signed off"})

    request = store.inputs.for_gate("rel-1", "approve")
    assert request is not None
    candidates = store.inputs.candidates_for(request.request_id)
    decision = store.inputs.decision(request.request_id)
    assert decision is not None
    assert decision.policy_id == "gate.validate"
    assert decision.policy_version == candidates[1].schema_version
    assert decision.accepted_id == candidates[1].candidate_id
    assert decision.observed_candidate_ids == tuple(
        candidate.candidate_id for candidate in candidates
    )

    # The drain ran after the commit: the receiver holds the intent, keyed by
    # the request, and the row acknowledges it.
    assert [effect.idempotency_key for effect in receiver.received] == [
        f"gate.accepted:{request.request_id}"
    ]
    effect_id = receiver.received[0].effect_id
    published = store.effects.effect(effect_id)
    assert published is not None and published.status == "published"

    # The report reads what the store recorded, and the legacy scope document
    # holds no record of this scope (AC-6's core).
    resolution = answered["resolution"]
    assert resolution["request_status"] == "accepted"
    assert resolution["accepted_id"] == decision.accepted_id
    assert resolution["decision"]["policy_id"] == "gate.validate"
    assert ScopeStore(app.substrate).get_scope("rel-1") is None


def test_a_relational_store_refuses_an_uncommitted_draft(
    project: Path, tmp_path: Path
) -> None:
    """`--no-commit` has no slot to land in: drafts are submissions."""
    receiver = Receiver()
    app = _app(
        tmp_path,
        f"sqlite://{tmp_path / 'state.db'}",
        SQLiteSubstratePlugin(),
        ReceiverPlugin(receiver),
    )
    _blocked_at_gate(app)
    store = selected_workflow_store(app)

    refused = answer_gate(
        app, store, "rel-1", "approve", {"approved": True}, commit=False
    )

    assert refused["error"] == "draft_requires_commit"
    request = store.inputs.for_gate("rel-1", "approve")
    assert request is not None
    assert store.inputs.candidates_for(request.request_id) == ()


def test_reopen_supersedes_over_the_port_and_refuses_once_consumed(
    project: Path, tmp_path: Path
) -> None:
    """Reopen withdraws the accepted request; a passed walk refuses it."""
    receiver = Receiver()
    app = _app(
        tmp_path,
        f"sqlite://{tmp_path / 'state.db'}",
        SQLiteSubstratePlugin(),
        ReceiverPlugin(receiver),
    )
    _blocked_at_gate(app)
    store = selected_workflow_store(app)
    answer_gate(app, store, "rel-1", "approve", {"approved": True, "reason": "first"})
    first = store.inputs.for_gate("rel-1", "approve")
    assert first is not None

    reopened = answer_gate(
        app,
        store,
        "rel-1",
        "approve",
        {"approved": False, "reason": "corrected"},
        reopen=True,
    )

    assert reopened["status"] == "answered"
    second = store.inputs.for_gate("rel-1", "approve")
    assert second is not None and second.request_id != first.request_id
    assert store.inputs.request(first.request_id).status == "cancelled"
    # The superseded request keeps its own recorded decision.
    assert store.inputs.decision(first.request_id) is not None
    assert store.inputs.decision(second.request_id) is not None
    # Two acceptances, two requests, two intents — each keyed by its request.
    assert sorted(effect.idempotency_key for effect in receiver.received) == sorted(
        [
            f"gate.accepted:{first.request_id}",
            f"gate.accepted:{second.request_id}",
        ]
    )

    app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id="rel-1")
    )

    consumed = answer_gate(
        app,
        store,
        "rel-1",
        "approve",
        {"approved": True, "reason": "again"},
        reopen=True,
    )
    assert consumed["error"] == "gate_already_consumed"


def test_the_document_seam_records_the_decision_beside_the_candidate(
    project: Path, tmp_path: Path
) -> None:
    """The same one path over the scope document: decision now included."""
    app = _app(tmp_path, "documents:")
    _blocked_at_gate(app)
    store = selected_workflow_store(app)

    drafted = answer_gate(app, store, "rel-1", "approve", {"approved": True})
    assert drafted["status"] == "drafted"
    assert store.get_gate("rel-1", "approve")["payload"] is None

    answered = answer_gate(app, store, "rel-1", "approve", {"reason": "signed off"})
    assert answered["status"] == "answered"

    record = store.get_gate("rel-1", "approve")
    decision = record["decision"]
    # The document seam keeps partial input in its draft slot — only the
    # complete submission becomes a candidate, so the decision observes one.
    assert len(record["candidates"]) == 1
    assert decision["policy_id"] == "gate.validate"
    assert decision["accepted_id"] == record["candidates"][0]["candidate_id"]
    assert decision["observed_candidate_ids"] == [
        entry["candidate_id"] for entry in record["candidates"]
    ]
    assert (
        record["payload"] == Approval(approved=True, reason="signed off").model_dump()
    )

    resolution = answered["resolution"]
    assert resolution["accepted_id"] == decision["accepted_id"]
    assert resolution["causal"]["run_id"] is not None
    assert resolution["decision"]["policy_id"] == "gate.validate"
    # Provenance is on the record for the document seam; the view's candidate
    # entries keep the shape document projects have always seen.
    recorded = record["candidates"][0]
    assert recorded["resolver_class"] == "program"
    assert recorded["channel"] == "api"
    assert recorded["schema_id"].endswith("Approval")
    assert recorded["payload_hash"].startswith("sha256:")
    assert recorded["supersedes_candidate_id"] is None
    assert recorded["evidence_refs"] == []


def test_evidence_references_ride_the_submission_on_both_seams(
    project: Path, tmp_path: Path
) -> None:
    """Attached evidence is a reference plus a digest, never bytes."""
    from functualize._engine.recording import InputRecorder

    refs = [
        InputRecorder().evidence("https://example/approval.pdf", "sha256:" + "a" * 64)
    ]
    receiver = Receiver()
    app = _app(
        tmp_path,
        f"sqlite://{tmp_path / 'state.db'}",
        SQLiteSubstratePlugin(),
        ReceiverPlugin(receiver),
    )
    _blocked_at_gate(app)
    store = selected_workflow_store(app)

    answered = answer_gate(
        app,
        store,
        "rel-1",
        "approve",
        {"approved": True, "reason": "signed"},
        evidence=refs,
    )
    assert answered["status"] == "answered"
    request = store.inputs.for_gate("rel-1", "approve")
    assert request is not None
    [candidate] = store.inputs.candidates_for(request.request_id)
    assert candidate.evidence_refs == tuple(refs)


def test_addressing_errors_name_the_scope_and_the_survey_verb(
    project: Path, tmp_path: Path
) -> None:
    """`resolve_gate` over the port refuses like the document seam does."""
    receiver = Receiver()
    app = _app(
        tmp_path,
        f"sqlite://{tmp_path / 'state.db'}",
        SQLiteSubstratePlugin(),
        ReceiverPlugin(receiver),
    )
    _blocked_at_gate(app)
    store = selected_workflow_store(app)

    missing = resolve_gate(store, "nope", None)
    assert missing["error"] == "workflow_not_found"
    with pytest.raises(GateNotFoundError):
        resolve_gate(store, "rel-1", "not-a-gate")
    empty = resolve_gate(store, None, "not-a-gate")
    assert empty["error"] == "gate_not_found"
