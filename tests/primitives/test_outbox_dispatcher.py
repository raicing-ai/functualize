"""Dispatch committed SQLite effects with real claims and acknowledgements."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory

from functualize._primitives.outbox import DrainReport, OutboxDispatcher, retry_delay
from functualize.plugin import RuntimeStoreConfig

if TYPE_CHECKING:
    from collections.abc import Iterator

    from functualize_substrate_sqlite import SqliteRuntimeStore

    from functualize._types.persistence import EffectView

TOPIC = "gate.accepted"
T0 = datetime(2030, 1, 1, tzinfo=UTC)


def _store(root: Path) -> SqliteRuntimeStore:
    return cast(
        "SqliteRuntimeStore",
        SqliteRuntimeStoreFactory()
        .prepare(
            RuntimeStoreConfig(
                url=f"sqlite://{root / 'state.db'}",
                scheme="sqlite",
                project_root=root,
            )
        )
        .store,
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SqliteRuntimeStore]:
    selected = _store(tmp_path)
    try:
        yield selected
    finally:
        selected.close()


def _commit_intent(store: SqliteRuntimeStore, key: str) -> None:
    with store.transaction() as tx:
        tx.effects.append("gate", TOPIC, {"key": key}, key)


def test_dispatcher_delivers_outside_a_transaction_and_publishes_once(
    store: SqliteRuntimeStore, tmp_path: Path
) -> None:
    """A peer can write during delivery; its dispatcher cannot steal the claim."""
    _commit_intent(store, "answer-1")
    peer = _store(tmp_path)

    class CompetingReceiver:
        topic = TOPIC

        def __init__(self) -> None:
            self.calls = 0

        def receive(self, effect: EffectView) -> None:
            self.calls += 1

    competitor = CompetingReceiver()
    competing_dispatcher = OutboxDispatcher(
        peer.effects, {TOPIC: competitor}, clock=lambda: T0
    )

    class Receiver:
        topic = TOPIC

        def __init__(self) -> None:
            self.effect_id: str | None = None
            self.competitor_report: DrainReport | None = None
            self.claimed_status: str | None = None
            self.calls = 0

        def receive(self, effect: EffectView) -> None:
            self.calls += 1
            self.effect_id = effect.effect_id
            claimed = peer.effects.effect(effect.effect_id)
            self.claimed_status = claimed.status if claimed else None
            # A second SQLite connection can commit while receive is running.
            # This would fail with a locked database if delivery held the unit.
            with peer.transaction() as tx:
                tx.effects.append(
                    "audit", "audit.received", {"source": effect.effect_id}, "audit-1"
                )
            self.competitor_report = competing_dispatcher.drain()

    receiver = Receiver()
    dispatcher = OutboxDispatcher(store.effects, {TOPIC: receiver}, clock=lambda: T0)
    try:
        assert dispatcher.drain() == DrainReport(delivered=1)
        assert receiver.calls == 1
        assert receiver.claimed_status == "claimed"
        assert receiver.competitor_report == DrainReport()
        assert competitor.calls == 0
        assert receiver.effect_id is not None
        published = store.effects.effect(receiver.effect_id)
        assert published is not None
        assert (published.status, published.attempts, published.payload) == (
            "published",
            1,
            {"key": "answer-1"},
        )
        assert published.published_at == T0
        assert peer.driver.query(
            "SELECT status FROM outbox WHERE topic = 'audit.received'"
        ) == [("pending",)]
        assert dispatcher.drain() == DrainReport()
        assert receiver.calls == 1
    finally:
        peer.close()


def test_receiver_failure_is_read_back_and_retried_when_due(
    store: SqliteRuntimeStore,
) -> None:
    _commit_intent(store, "answer-2")
    now = [T0]

    class FailsOnce:
        topic = TOPIC

        def __init__(self) -> None:
            self.calls = 0
            self.effect_id: str | None = None

        def receive(self, effect: EffectView) -> None:
            self.calls += 1
            self.effect_id = effect.effect_id
            if self.calls == 1:
                raise ConnectionError("receiver offline")

    receiver = FailsOnce()
    dispatcher = OutboxDispatcher(
        store.effects, {TOPIC: receiver}, clock=lambda: now[0]
    )

    assert dispatcher.drain() == DrainReport(failed=1)
    assert receiver.effect_id is not None
    pending = store.effects.effect(receiver.effect_id)
    assert pending is not None
    assert (pending.status, pending.attempts, pending.last_error) == (
        "pending",
        1,
        "ConnectionError: receiver offline",
    )
    assert pending.available_at == T0 + retry_delay(1)
    now[0] = pending.available_at - timedelta(microseconds=1)
    assert dispatcher.drain() == DrainReport()
    now[0] = pending.available_at
    assert dispatcher.drain() == DrainReport(delivered=1)
    published = store.effects.effect(receiver.effect_id)
    assert published is not None
    assert (published.status, published.attempts) == ("published", 2)
    assert receiver.calls == 2


class _StoppedAfterApply(BaseException):
    """Simulates the process disappearing before the queue acknowledgment."""


def test_lost_ack_redelivers_but_receiver_deduplicates_by_key(
    store: SqliteRuntimeStore,
) -> None:
    _commit_intent(store, "answer-3")
    now = [T0]

    class DeduplicatingReceiver:
        topic = TOPIC

        def __init__(self) -> None:
            self.calls = 0
            self.applied: set[str] = set()
            self.effect_id: str | None = None

        def receive(self, effect: EffectView) -> None:
            self.calls += 1
            self.effect_id = effect.effect_id
            if effect.idempotency_key not in self.applied:
                assert effect.idempotency_key is not None
                self.applied.add(effect.idempotency_key)
            if self.calls == 1:
                raise _StoppedAfterApply()

    receiver = DeduplicatingReceiver()
    dispatcher = OutboxDispatcher(
        store.effects,
        {TOPIC: receiver},
        clock=lambda: now[0],
        lease_seconds=60,
    )

    with pytest.raises(_StoppedAfterApply):
        dispatcher.drain()
    assert receiver.effect_id is not None
    held = store.effects.effect(receiver.effect_id)
    assert held is not None
    assert (held.status, held.attempts, held.published_at) == ("claimed", 1, None)
    now[0] = T0 + timedelta(seconds=59)
    assert dispatcher.drain() == DrainReport()
    now[0] = T0 + timedelta(seconds=61)
    assert dispatcher.drain() == DrainReport(delivered=1)
    published = store.effects.effect(receiver.effect_id)
    assert published is not None
    assert (published.status, published.attempts) == ("published", 2)
    assert receiver.calls == 2
    assert receiver.applied == {"answer-3"}


def test_retry_delay_stays_bounded_for_many_attempts() -> None:
    assert retry_delay(1) == timedelta(seconds=5)
    assert retry_delay(2) == timedelta(seconds=10)
    assert retry_delay(1_000_000) == timedelta(minutes=15)
