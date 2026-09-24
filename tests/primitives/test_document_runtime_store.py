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
from functualize._types.errors import CrossAggregateRefusedError
from functualize._types.persistence import (
    CancelWorkflow,
    Claimed,
    ClaimWorkflow,
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
