"""The instruments, checked before anything is measured with them (FUN-25 2.1).

`tests/substrate_probe/fakes.py` is the only file tasks 2.1 and 2.2 declare; this
module is a declared deviation, for the reason wave 0's two test modules are: the
directory's convention is instrument plus `test_<instrument>.py`, and both tasks'
done-when are *behavioural* — a transaction that cannot be held open, a batch
that commits with no network, an S3 that cannot commit two keys together, a
DynamoDB that cancels a whole transaction — none of which a counting gate can
see. Each test here was shown to fail against a sabotaged instrument before its
box was ticked.
"""

from __future__ import annotations

import sqlite3

import pytest

from tests.substrate_probe.fakes import (
    BatchOnlySqliteDriver,
    FakeItemStore,
    FakeObjectStore,
    NoInteractiveTransactionError,
    PreconditionFailedError,
    Put,
    TransactionCanceledError,
    _offline_round_trip,
)
from tests.substrate_probe.harness import FAKE_EVIDENCE, FIELDS

#: The three, for the parametrised checks at the foot of this module.
INSTRUMENTS = (BatchOnlySqliteDriver, FakeObjectStore, FakeItemStore)


class TestATransactionCannotBeHeldOpenAcrossAPythonDecision:
    """2.1: D1 has no `BEGIN`/`COMMIT`, and the driver refuses rather than mimes one."""

    def test_the_transaction_is_refused_and_its_body_never_runs(self) -> None:
        driver = BatchOnlySqliteDriver()
        decided: list[str] = []

        with pytest.raises(NoInteractiveTransactionError), driver.transaction():
            decided.append(driver.read("nothing") or "read, decided, then wrote")

        assert decided == []


class TestOneBatchIsTheOnlyAtomicUnit:
    """2.1: one batch commits — with no network — and a refused one leaves nothing."""

    def test_one_batch_commits_with_no_network(self) -> None:
        driver = BatchOnlySqliteDriver()

        reached = _offline_round_trip(
            lambda: driver.batch(
                (
                    (
                        "INSERT OR REPLACE INTO documents(key, body) VALUES (?, ?)",
                        ("a", "1"),
                    ),
                    (
                        "INSERT OR REPLACE INTO documents(key, body) VALUES (?, ?)",
                        ("b", "2"),
                    ),
                )
            )
        )

        assert reached == ()
        assert (driver.read("a"), driver.read("b")) == ("1", "2")

    def test_a_refused_statement_rolls_the_whole_batch_back(self) -> None:
        driver = BatchOnlySqliteDriver()

        with pytest.raises(sqlite3.IntegrityError):
            driver.batch(
                (
                    ("INSERT INTO documents(key, body) VALUES (?, ?)", ("a", "state")),
                    ("INSERT INTO documents(key, body) VALUES (?, ?)", ("a", "outbox")),
                )
            )

        assert driver.read("a") is None


class TestTheObjectStoreCannotCommitTwoKeysTogether:
    """2.2: an S3 — conditional writes per key, and no atomicity across keys."""

    def test_a_write_is_refused_when_its_condition_does_not_hold(self) -> None:
        store = FakeObjectStore()
        fresh = store.put_if_absent("scopes", "1")

        with pytest.raises(PreconditionFailedError):
            store.put_if_absent("scopes", "2")
        with pytest.raises(PreconditionFailedError):
            store.put_if_match("scopes", "3", "an-etag-that-moved")
        assert store.get("scopes") == "1"

        store.put_if_match("scopes", "3", fresh)
        assert store.get("scopes") == "3"

    def test_advancing_the_state_can_leave_its_outbox_row_behind(self) -> None:
        """The half-write the instrument exists to expose: two calls, no unit."""
        store = FakeObjectStore()
        store.put("outbox", "from an earlier run")
        store.put("state", "2")

        with pytest.raises(PreconditionFailedError):
            store.put_if_absent("outbox", "for this run")

        assert (store.get("state"), store.get("outbox")) == ("2", "from an earlier run")


class TestTheItemStoreCancelsTheWholeTransaction:
    """2.2: a DynamoDB — one violated condition writes no item at all."""

    def test_a_violated_condition_writes_no_sibling_and_modifies_nothing(self) -> None:
        store = FakeItemStore()
        store.put("existing", "1")

        with pytest.raises(TransactionCanceledError):
            store.transact_write(
                (Put("sibling", "2"), Put("existing", "9", only_if_absent=True))
            )

        assert store.get("sibling") is None
        assert store.get("existing") == "1"

    def test_a_transaction_whose_conditions_hold_lands_every_item(self) -> None:
        store = FakeItemStore()

        store.transact_write(
            (Put("state", "1"), Put("outbox", "written", only_if_absent=True))
        )

        assert (store.get("state"), store.get("outbox")) == ("1", "written")


class TestNoInstrumentAnswerClaimsARealService:
    """2.2's done-when: ten answers each, every one of them `measured (fake)`."""

    @pytest.mark.parametrize("instrument", INSTRUMENTS)
    def test_every_field_of_the_harness_is_answered(self, instrument: type) -> None:
        answers = instrument().reading().answers

        assert {answer.field for answer in answers} == set(FIELDS)
        assert [answer for answer in answers if not answer.is_measured] == []

    @pytest.mark.parametrize("instrument", INSTRUMENTS)
    def test_every_answer_is_stamped_measured_fake(self, instrument: type) -> None:
        assert {answer.evidence for answer in instrument().reading().answers} == {
            FAKE_EVIDENCE
        }


class TestTheInstrumentsAreNotPorts:
    """`plan.md` §4: instruments, not backends — no shared base, no ABC, no port."""

    def test_no_shared_base_and_no_abstract_methods(self) -> None:
        for instrument in INSTRUMENTS:
            assert instrument.__bases__ == (object,)
            assert not hasattr(instrument, "__abstractmethods__")
