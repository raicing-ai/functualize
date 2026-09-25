"""The cross-aggregate refusal — a spanning unit never applies in parts.

FUN-17/T8, acceptance criterion 2. `DOCUMENT_PROFILE` declares
`cross_aggregate_atomicity=False` because the document stores take one lock
per document and two cannot roll back together, so a unit spanning two
workflow scopes must be refused whole — naming the aggregates, with the
second one unwritten.

The expensive mistake this file exists to catch is not "no exception was
raised" but "one aggregate survived": applying half a transition is defect B3
under a new name, and a test that only checks the raise cannot tell a refusal
from a partial apply that happened to fail at the end. Every refusal case
here therefore reads **both** aggregates back through a freshly constructed
store — not the refused transaction's own view — and finds the crossed
aggregate unwritten.

`claim` is the one write that can be on disk when a crossing is refused, and
it is why the second half of this file exists. A claim commits on the spot
(`contracts.md` §1.3), so a unit that claimed one scope and then reached for
another is already half-applied — and refusing that at commit, as the first
version of the refusal did, both refused a legitimate same-scope batch and
reported "nothing applied" while a lease was held. Those cases assert what
the message now says: the second aggregate untouched, and the scope that did
reach disk named in `CrossAggregateRefusedError.landed` so the caller releases
it instead of retrying it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import (
    CrossAggregateRefusedError,
    InputRequestNotOpenError,
)
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
)
from functualize._types.persistence import (
    CancelWorkflow,
    Claimed,
    ClaimWorkflow,
    ConsumeInput,
    ResumeWorkflow,
    SuspendAtGate,
)

#: One fixed clock for every command, so a failure cannot depend on when the
#: test ran. Commands carry `now` precisely so this is possible.
NOW = datetime(2026, 9, 24, 0, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> DocumentRuntimeStore:
    return DocumentRuntimeStore(JsonFileSubstrate(tmp_path))


def _fresh(tmp_path: Path) -> DocumentRuntimeStore:
    """A store that shares the documents but none of the first one's memory.

    Reading the refusal's aftermath through this is what makes the check a
    read-back rather than an echo: the transaction object's own state is not
    evidence of what reached a file.
    """
    return DocumentRuntimeStore(JsonFileSubstrate(tmp_path))


def _claim(store: DocumentRuntimeStore, scope_id: str) -> Claimed:
    """Claim one scope in its own single-command unit."""
    with store.transaction() as tx:
        return tx.workflows.claim(
            ClaimWorkflow(
                scope_id=scope_id, owner="tester", now=NOW, lease_seconds=300.0
            )
        )


class TestTheSpanningRefusal:
    def test_both_aggregates_are_refused_and_neither_written(
        self, store: DocumentRuntimeStore, tmp_path: Path
    ) -> None:
        claimed_a = _claim(store, "scope-a")
        claimed_b = _claim(store, "scope-b")

        with (
            pytest.raises(CrossAggregateRefusedError) as raised,
            store.transaction() as tx,
        ):
            tx.workflows.cancel(
                CancelWorkflow(
                    scope_id="scope-a", generation=claimed_a.generation, now=NOW
                )
            )
            tx.workflows.cancel(
                CancelWorkflow(
                    scope_id="scope-b", generation=claimed_b.generation, now=NOW
                )
            )

        assert raised.value.aggregates == ("scope-a", "scope-b")
        assert "scope-a" in str(raised.value) and "scope-b" in str(raised.value)

        fresh = _fresh(tmp_path)
        view_a = fresh.workflows.workflow("scope-a")
        view_b = fresh.workflows.workflow("scope-b")
        assert view_a is not None and view_a.status == "running"
        assert view_b is not None and view_b.status == "running"
        assert fresh.workflows.events_after("scope-a", 0) == ()
        assert fresh.workflows.events_after("scope-b", 0) == ()

    def test_one_aggregate_still_applies(
        self, store: DocumentRuntimeStore, tmp_path: Path
    ) -> None:
        """The refusal must not make an ordinary single-aggregate unit shy.

        Also the first exercise of `apply`'s clean path: a unit of one cancel
        commits, and the read-back sees the status and the event.
        """
        claimed = _claim(store, "scope-a")

        with store.transaction() as tx:
            tx.workflows.cancel(
                CancelWorkflow(
                    scope_id="scope-a", generation=claimed.generation, now=NOW
                )
            )

        fresh = _fresh(tmp_path)
        view = fresh.workflows.workflow("scope-a")
        assert view is not None and view.status == "cancelled"
        events = fresh.workflows.events_after("scope-a", 0)
        assert [event.type for event in events] == ["workflow.cancelled"]

    def test_claims_across_two_scopes_are_not_a_batch(
        self, store: DocumentRuntimeStore, tmp_path: Path
    ) -> None:
        """Two claims in one `with` block are two single-command commits.

        `claim` commits on the spot — that is what lets it answer with a
        value — so a block whose only writes are claims carries no batch for
        the refusal to judge, and both scopes must end up claimed.
        """
        with store.transaction() as tx:
            first = tx.workflows.claim(
                ClaimWorkflow(
                    scope_id="scope-a", owner="tester", now=NOW, lease_seconds=300.0
                )
            )
            second = tx.workflows.claim(
                ClaimWorkflow(
                    scope_id="scope-b", owner="tester", now=NOW, lease_seconds=300.0
                )
            )

        assert first.generation == 1 and second.generation == 1
        fresh = _fresh(tmp_path)
        for scope_id in ("scope-a", "scope-b"):
            view = fresh.workflows.workflow(scope_id)
            assert view is not None and view.generation == 1

    def test_claim_first_then_a_batch_on_the_other_scope_is_refused(
        self, store: DocumentRuntimeStore, tmp_path: Path
    ) -> None:
        """A claim under a batch for another scope is refused, and says so.

        `claim` commits on the spot, so a unit that claims `scope-a` and then
        buffers a command for `scope-b` has *written* `scope-a` by the time the
        second aggregate is reached. The refusal must therefore admit it: a
        caller told "nothing applied" would retry `scope-a` and take a second
        lease, and the lease it already holds is the thing it has to release.

        The batch half is refused with the claim: `scope-a` is claimed and not
        cancelled, `scope-b` was never touched, and a later ordinary unit for
        `scope-b` still commits — the refusal is a fact about this
        transaction, not a poisoned store.
        """
        claimed_b = _claim(store, "scope-b")

        with (
            pytest.raises(CrossAggregateRefusedError) as raised,
            store.transaction() as tx,
        ):
            first = tx.workflows.claim(
                ClaimWorkflow(
                    scope_id="scope-a", owner="tester", now=NOW, lease_seconds=300.0
                )
            )
            tx.workflows.cancel(
                CancelWorkflow(scope_id="scope-a", generation=first.generation, now=NOW)
            )
            tx.workflows.cancel(
                CancelWorkflow(
                    scope_id="scope-b", generation=claimed_b.generation, now=NOW
                )
            )

        assert first.generation == 1
        assert raised.value.aggregates == ("scope-a", "scope-b")
        assert raised.value.landed == ("scope-a",)
        assert "nothing applied" not in str(raised.value)

        fresh = _fresh(tmp_path)
        claimed = fresh.workflows.workflow("scope-a")
        assert claimed is not None and claimed.status == "running"
        assert fresh.workflows.events_after("scope-a", 0) == ()
        untouched = fresh.workflows.workflow("scope-b")
        assert untouched is not None and untouched.status == "running"

        with store.transaction() as tx:
            tx.workflows.cancel(
                CancelWorkflow(
                    scope_id="scope-b", generation=claimed_b.generation, now=NOW
                )
            )

        assert _fresh(tmp_path).workflows.workflow("scope-b").status == "cancelled"

    def test_a_batch_first_then_a_claim_on_the_other_scope_is_refused(
        self, store: DocumentRuntimeStore, tmp_path: Path
    ) -> None:
        """The claim is refused *before* it writes — the partial apply.

        This is the order the old refusal got wrong in the other direction: a
        buffered batch for `scope-a` and then `claim(scope-b)` used to leave
        `scope-b` holding a lease, refuse at commit, and report that nothing
        had been applied. Nothing here can un-write a claim, so the refusal has
        to land at the claim itself, before `claim_scope`, and the `.landed`
        it reports is empty because the claim never happened.
        """
        claimed_a = _claim(store, "scope-a")

        with (
            pytest.raises(CrossAggregateRefusedError) as raised,
            store.transaction() as tx,
        ):
            tx.workflows.cancel(
                CancelWorkflow(
                    scope_id="scope-a", generation=claimed_a.generation, now=NOW
                )
            )
            # Raised by `claim` itself — the call that would otherwise have
            # returned `Claimed` — not by the block's exit.
            tx.workflows.claim(
                ClaimWorkflow(
                    scope_id="scope-b", owner="tester", now=NOW, lease_seconds=300.0
                )
            )

        assert raised.value.aggregates == ("scope-a", "scope-b")
        assert raised.value.landed == ()

        fresh = _fresh(tmp_path)
        assert fresh.workflows.workflow("scope-b") is None
        untouched = fresh.workflows.workflow("scope-a")
        assert untouched is not None and untouched.status == "running"
        assert fresh.workflows.events_after("scope-a", 0) == ()

    def test_a_swallowed_refusal_still_refuses_the_whole_unit(
        self, store: DocumentRuntimeStore, tmp_path: Path
    ) -> None:
        """Catching the refusal inside the block must not land the batch.

        `apply` runs on any clean exit, so a caller that catches the crossing
        where it is raised — and returns normally — would otherwise apply the
        half that never reached a document: a refused unit applied in part,
        which is the defect the refusal exists to prevent. The transaction
        stays refused, and the same error comes out at exit.
        """
        claimed_a = _claim(store, "scope-a")

        with (
            pytest.raises(CrossAggregateRefusedError) as raised,
            store.transaction() as tx,
        ):
            tx.workflows.cancel(
                CancelWorkflow(
                    scope_id="scope-a", generation=claimed_a.generation, now=NOW
                )
            )
            with pytest.raises(CrossAggregateRefusedError):
                tx.workflows.claim(
                    ClaimWorkflow(
                        scope_id="scope-b",
                        owner="tester",
                        now=NOW,
                        lease_seconds=300.0,
                    )
                )

        assert raised.value.aggregates == ("scope-a", "scope-b")
        assert raised.value.landed == ()

        fresh = _fresh(tmp_path)
        untouched = fresh.workflows.workflow("scope-a")
        assert untouched is not None and untouched.status == "running"
        assert fresh.workflows.events_after("scope-a", 0) == ()
        assert fresh.workflows.workflow("scope-b") is None


class TestTheEffectRefusal:
    def test_an_effect_is_refused_rather_than_dropped(
        self, store: DocumentRuntimeStore
    ) -> None:
        """No outbox document exists here — `durable_outbox=False`, genuinely.

        The refusal is keyed on a capability this store really lacks (the
        capability matrix's filesystem column has no outbox row to borrow),
        so recording the intent cannot silently become a no-op: an unrecorded
        intent is a side effect nobody can replay.
        """
        with (
            pytest.raises(NotImplementedError, match="durable_outbox=False"),
            store.transaction() as tx,
        ):
            tx.effects.append(
                "functualize", "build.completed", {"v": 1}, idempotency_key="k-1"
            )


class TestTheInputsAggregate:
    """The document backend speaking the amended input port.

    A suspend opens the request with its own id, a candidate append answers
    it, and the walk's consume retires it — each through `transaction()`,
    each refused or applied as one unit. The resume reclaiming the scope no
    longer stamps `consumed_at`: consumption has one writer, and it is the
    `ConsumeInput` command the walk issues when it feeds the answer forward.
    """

    REQUEST_ID = "req_3f9c"

    def _suspend(self, store: DocumentRuntimeStore, generation: int = 1) -> None:
        store.scope_store.ensure_scope("wf-1")
        store.scope_store.claim_scope("wf-1", owner="w1", now=NOW)
        with store.transaction() as tx:
            tx.workflows.suspend(
                SuspendAtGate(
                    scope_id="wf-1",
                    generation=generation,
                    gate_name="approve",
                    request_id=self.REQUEST_ID,
                    position="approve",
                    now=NOW,
                    schema={"type": "object"},
                    prompt="Approve?",
                    model="Approval",
                    tools=({"tool": "check_stock", "bound": ["sku"]},),
                )
            )

    def _accepted(self, ordinal: int = 0) -> GateCandidate:
        return GateCandidate(
            candidate_id=f"cand_{ordinal}",
            request_id=self.REQUEST_ID,
            ordinal=ordinal,
            source="api",
            submitted_at=NOW,
            evaluation=CandidateEvaluation(EvaluationOutcome.ACCEPTED),
            payload={"approved": True},
        )

    def test_suspend_opens_a_request_the_reader_finds_by_id(
        self, store: DocumentRuntimeStore
    ) -> None:
        self._suspend(store)
        request = store.inputs.request(self.REQUEST_ID)
        assert request is not None
        assert request.status == "open"
        assert request.gate_name == "approve"
        assert store.inputs.candidates_for(self.REQUEST_ID) == ()
        record = store.scope_store.get_gate("wf-1", "approve") or {}
        assert record["model"] == "Approval"
        assert record["tools"] == [{"tool": "check_stock", "bound": ["sku"]}]

    def test_a_candidate_answers_and_the_second_is_refused_whole(
        self, store: DocumentRuntimeStore
    ) -> None:
        self._suspend(store)
        with store.transaction() as tx:
            tx.inputs.append(self._accepted())
        assert store.inputs.request(self.REQUEST_ID) is not None
        assert store.inputs.request(self.REQUEST_ID).status == "accepted"  # type: ignore[union-attr]
        recorded = store.inputs.candidates_for(self.REQUEST_ID)
        assert [c.candidate_id for c in recorded] == ["cand_0"]
        with pytest.raises(InputRequestNotOpenError), store.transaction() as tx:
            tx.inputs.append(self._accepted(ordinal=1))

    def test_consume_retires_once_and_the_resume_does_not(
        self, store: DocumentRuntimeStore
    ) -> None:
        self._suspend(store)
        with store.transaction() as tx:
            tx.inputs.append(self._accepted())
        with store.transaction() as tx:
            tx.workflows.resume(
                ResumeWorkflow(
                    scope_id="wf-1",
                    owner="w2",
                    gate_name="approve",
                    now=NOW,
                    lease_seconds=300,
                    force=True,  # the suspending walk never released in-test
                )
            )
        # The reclaim alone: consumption is the walk's single write.
        record = store.scope_store.get_gate("wf-1", "approve") or {}
        assert record.get("consumed_at") is None
        assert record["status"] == "accepted"
        with store.transaction() as tx:
            tx.inputs.consume(
                ConsumeInput(
                    scope_id="wf-1",
                    generation=store.scope_store.generation_for("wf-1") or 2,
                    request_id=self.REQUEST_ID,
                    now=NOW,
                )
            )
        retired = store.scope_store.get_gate("wf-1", "approve") or {}
        assert retired["status"] == "consumed"
        assert retired["consumed_at"] == NOW.isoformat()
        with store.transaction() as tx:  # a replayed resume is a no-op
            tx.inputs.consume(
                ConsumeInput(
                    scope_id="wf-1",
                    generation=store.scope_store.generation_for("wf-1") or 2,
                    request_id=self.REQUEST_ID,
                    now=NOW,
                )
            )
        assert store.scope_store.get_gate("wf-1", "approve") == retired

    def test_a_legacy_record_projects_through_the_port(
        self, store: DocumentRuntimeStore
    ) -> None:
        store.scope_store.ensure_scope("wf-1")
        store.scope_store.put_gate(
            "wf-1",
            "approve",
            {
                "model": "Approval",
                "input_schema": {"type": "object"},
                "payload": {"approved": True},
                "blocked_at": NOW.isoformat(),
            },
        )
        request = store.inputs.request("wf-1::approve")
        assert request is not None
        assert request.status == "accepted"
        assert store.inputs.candidates_for("wf-1::approve") == ()
        assert store.inputs.open_for("wf-1") is not None
