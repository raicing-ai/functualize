"""The input recorder's provenance, evidence, decision and intent values.

Gates for task 1.1 of `gate-interactions-outbox`: every candidate the
recorder builds carries who answered, through what, against which schema and
over which payload; evidence is a reference plus a digest and nothing else; a
decision names exactly the candidates it weighed; an acceptance's intent is
keyed by its request.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from functualize._engine.recording import InputRecorder
from functualize._engine.recording.input_recorder import (
    LADDER_POLICY,
    content_digest,
    schema_identity,
)
from functualize._types.gate_resolution import (
    GATE_ACCEPTED_TOPIC,
    CandidateEvaluation,
    EvaluationOutcome,
    EvidenceRef,
    GateCandidate,
    LadderOutcome,
)

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
ACCEPTED = CandidateEvaluation(EvaluationOutcome.ACCEPTED)
INVALID = CandidateEvaluation(EvaluationOutcome.INVALID, errors=(("ok", "bad"),))
DIGEST = content_digest(b"screenshot bytes")


class Approval(BaseModel):
    approved: bool


class TestSubmittedProvenance:
    @pytest.mark.parametrize(
        ("source", "resolver"),
        [("cli", "human"), ("tui", "human"), ("mcp", "agent"), ("api", "program")],
    )
    def test_the_surface_decides_the_resolver_class_and_is_the_channel(
        self, source: str, resolver: str
    ) -> None:
        candidate = InputRecorder().submitted(
            "req_1", source, ACCEPTED, {"approved": True}, ordinal=0, now=T0
        )
        assert (candidate.resolver_class, candidate.channel) == (resolver, source)

    def test_the_payload_hash_is_over_the_canonical_payload(self) -> None:
        recorder = InputRecorder()
        one = recorder.submitted(
            "r", "cli", ACCEPTED, {"a": 1, "b": 2}, ordinal=0, now=T0
        )
        two = recorder.submitted(
            "r", "cli", ACCEPTED, {"b": 2, "a": 1}, ordinal=1, now=T0
        )
        other = recorder.submitted("r", "cli", ACCEPTED, {"a": 2}, ordinal=2, now=T0)
        assert one.payload_hash == two.payload_hash != other.payload_hash
        assert one.payload_hash.startswith("sha256:")

    def test_schema_identity_is_the_import_path_and_the_schema_digest(self) -> None:
        schema_id, version = schema_identity(Approval)
        assert schema_id == f"{__name__}.Approval"
        assert version.startswith("sha256:") and len(version) == len("sha256:") + 64

        class Edited(BaseModel):
            approved: bool
            reason: str = ""

        assert schema_identity(Edited)[1] != version

    def test_a_correction_names_what_it_supersedes(self) -> None:
        candidate = InputRecorder().submitted(
            "req_1", "cli", INVALID, {}, ordinal=1, now=T0, supersedes="cand_0"
        )
        assert candidate.supersedes_candidate_id == "cand_0"


class TestEvidence:
    def test_a_reference_and_a_digest_are_kept(self) -> None:
        ref = EvidenceRef("artifact://ev_5", DIGEST, "image/png", 16)
        candidate = InputRecorder().submitted(
            "req_1", "cli", ACCEPTED, {}, ordinal=0, now=T0, evidence=[ref]
        )
        assert candidate.evidence_refs == (ref,)

    @pytest.mark.parametrize(
        ("ref", "digest", "message"),
        [
            ("", DIGEST, "reference"),
            ("data:image/png;base64,iVBORw0KGgo=", DIGEST, "never as bytes"),
            ("artifact://ev", "", "digest"),
            ("artifact://ev", "md5:abc", "digest"),
            ("artifact://ev", "sha256:" + "A" * 64, "digest"),
        ],
    )
    def test_anything_but_a_reference_plus_a_digest_is_refused(
        self, ref: str, digest: str, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            InputRecorder().submitted(
                "req_1",
                "cli",
                ACCEPTED,
                {},
                ordinal=0,
                now=T0,
                evidence=[EvidenceRef(ref, digest)],
            )


class TestLadderCandidates:
    def test_each_rung_names_its_strategy_and_resolver(self) -> None:
        outcome = LadderOutcome(
            rungs=(
                ("decision", CandidateEvaluation(EvaluationOutcome.FAILED), None),
                ("prompt", ACCEPTED, {"approved": True}),
                ("resolve", CandidateEvaluation(EvaluationOutcome.NOT_REACHED), None),
            )
        )
        rungs = InputRecorder().ladder_candidates(
            "req_1",
            outcome,
            first_ordinal=2,
            now=T0,
            schema_id="m.Approval",
            schema_version="sha256:x",
        )
        assert [(c.channel, c.resolver_class) for c in rungs] == [
            ("decision", "agent"),
            ("prompt", "human"),
            ("resolve", "policy"),
        ]
        assert [c.ordinal for c in rungs] == [2, 3, 4]
        assert {c.schema_id for c in rungs} == {"m.Approval"}
        assert [bool(c.payload_hash) for c in rungs] == [False, True, False]


class TestDecision:
    def _candidates(self) -> list[GateCandidate]:
        recorder = InputRecorder()
        return [
            recorder.submitted("req_1", "cli", INVALID, {}, ordinal=0, now=T0),
            recorder.submitted(
                "req_1", "cli", ACCEPTED, {"approved": True}, ordinal=1, now=T0
            ),
            recorder.submitted("req_1", "api", INVALID, {}, ordinal=2, now=T0),
        ]

    def test_the_observed_ids_stop_at_the_accepted_one(self) -> None:
        candidates = self._candidates()
        decision = InputRecorder().decided(
            "req_1",
            list(reversed(candidates)),
            candidates[1].candidate_id,
            policy_id="gate.validate",
            policy_version="sha256:v",
            now=T0,
        )
        assert decision.observed_candidate_ids == (
            candidates[0].candidate_id,
            candidates[1].candidate_id,
        )
        assert (decision.policy_id, decision.policy_version) == (
            "gate.validate",
            "sha256:v",
        )

    def test_an_accepted_id_that_is_not_a_candidate_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not among"):
            InputRecorder().decided(
                "req_1",
                self._candidates(),
                "cand_missing",
                policy_id="p",
                policy_version="1",
                now=T0,
            )

    def test_the_ladder_policy_is_versioned_by_its_rungs(self) -> None:
        one = InputRecorder.ladder_policy(["decision", "prompt", "resolve"])
        two = InputRecorder.ladder_policy(["prompt", "resolve"])
        assert one[0] == two[0] == LADDER_POLICY
        assert one[1] != two[1]


class TestAcceptedEffect:
    def test_the_intent_is_keyed_by_its_request(self) -> None:
        recorder = InputRecorder()
        accepted = recorder.submitted("req_7", "cli", ACCEPTED, {}, ordinal=0, now=T0)
        decision = recorder.decided(
            "req_7",
            [accepted],
            accepted.candidate_id,
            policy_id="gate.validate",
            policy_version="v",
            now=T0,
        )
        intent = recorder.accepted_effect(
            decision, scope_id="wf_42", gate_name="approval"
        )
        assert intent.topic == GATE_ACCEPTED_TOPIC
        assert intent.idempotency_key == "gate.accepted:req_7"
        assert intent.payload == {
            "request_id": "req_7",
            "scope_id": "wf_42",
            "gate": "approval",
            "accepted_id": accepted.candidate_id,
            "policy_id": "gate.validate",
            "policy_version": "v",
        }

    def test_superseding_mints_a_new_request_id(self) -> None:
        command = InputRecorder().superseding(
            scope_id="wf_42", gate_name="approval", request_id="req_7", now=T0
        )
        assert command.request_id == "req_7"
        assert command.new_request_id.startswith("req_")
        assert command.new_request_id != "req_7"
