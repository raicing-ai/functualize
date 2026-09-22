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
    NoInteractiveTransactionError,
    _offline_round_trip,
)


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
