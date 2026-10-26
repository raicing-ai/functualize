"""`SqlEffectQueue`: claim, acknowledge, reschedule, retake (task 1.4).

Gates: a claim takes only due intents of the asked topics and stamps a token;
an acknowledgement with a stale token changes nothing; a failure returns the
intent to ``pending`` with its error and retry time; a claim whose lease
expired is taken again — at-least-once — and the store is an ``OutboxStore``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory

from functualize.plugin import (
    Claimed,
    ClaimWorkflow,
    CompleteStep,
    EffectQueue,
    OutboxStore,
    RuntimeStoreConfig,
)

if TYPE_CHECKING:
    from functualize_substrate_sqlite import SqliteRuntimeStore

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> SqliteRuntimeStore:
    config = RuntimeStoreConfig(
        url=f"sqlite://{tmp_path / 'state.db'}", scheme="sqlite", project_root=tmp_path
    )
    return cast("SqliteRuntimeStore", SqliteRuntimeStoreFactory().prepare(config).store)


def _intent(store: SqliteRuntimeStore, topic: str, key: str, step: str = "s") -> None:
    with store.transaction() as tx:
        claimed = tx.workflows.claim(ClaimWorkflow(f"scope-{key}", "w", T0, 60.0))
    assert isinstance(claimed, Claimed)
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep(f"scope-{key}", claimed.generation, step, T0, position="p")
        )
        tx.effects.append("test", topic, {"key": key}, key)


def test_the_store_is_an_outbox_store(store: SqliteRuntimeStore) -> None:
    assert isinstance(store, OutboxStore)
    assert isinstance(store.effects, EffectQueue)


def test_a_claim_takes_only_due_intents_of_its_topics(
    store: SqliteRuntimeStore,
) -> None:
    _intent(store, "gate.accepted", "a")
    _intent(store, "other.topic", "b")

    claimed = store.effects.claim(
        ["gate.accepted"], now=datetime.now(UTC), lease_seconds=60, limit=10
    )

    assert [effect.idempotency_key for effect in claimed] == ["a"]
    [effect] = claimed
    assert (effect.status, effect.attempts, effect.payload) == (
        "claimed",
        1,
        {"key": "a"},
    )
    assert effect.claim_token
    again = store.effects.claim(
        ["gate.accepted"], now=datetime.now(UTC), lease_seconds=60, limit=10
    )
    assert again == ()


def test_published_settles_it_for_good(store: SqliteRuntimeStore) -> None:
    _intent(store, "t", "a")
    now = datetime.now(UTC)
    [effect] = store.effects.claim(["t"], now=now, lease_seconds=60, limit=1)

    store.effects.published(effect, now=now)

    settled = store.effects.effect(effect.effect_id)
    assert settled is not None and settled.status == "published"
    assert settled.published_at is not None
    later = now + timedelta(days=1)
    assert store.effects.claim(["t"], now=later, lease_seconds=60, limit=1) == ()


def test_a_failure_returns_it_pending_until_its_retry_time(
    store: SqliteRuntimeStore,
) -> None:
    _intent(store, "t", "a")
    now = datetime.now(UTC)
    [effect] = store.effects.claim(["t"], now=now, lease_seconds=60, limit=1)

    store.effects.failed(
        effect, error="ConnectionError: down", retry_at=now + timedelta(seconds=5)
    )

    pending = store.effects.effect(effect.effect_id)
    assert pending is not None
    assert (pending.status, pending.last_error) == ("pending", "ConnectionError: down")
    assert store.effects.claim(["t"], now=now, lease_seconds=60, limit=1) == ()
    [retried] = store.effects.claim(
        ["t"], now=now + timedelta(seconds=6), lease_seconds=60, limit=1
    )
    assert retried.attempts == 2


def test_an_expired_claim_is_taken_again_and_the_stale_ack_lands_nothing(
    store: SqliteRuntimeStore,
) -> None:
    _intent(store, "t", "a")
    now = datetime.now(UTC)
    [first] = store.effects.claim(["t"], now=now, lease_seconds=60, limit=1)

    # The first dispatcher died after the receiver and before acknowledging.
    assert (
        store.effects.claim(
            ["t"], now=now + timedelta(seconds=30), lease_seconds=60, limit=1
        )
        == ()
    )
    [second] = store.effects.claim(
        ["t"], now=now + timedelta(seconds=61), lease_seconds=60, limit=1
    )
    assert second.effect_id == first.effect_id
    assert second.attempts == 2 and second.claim_token != first.claim_token

    store.effects.published(first, now=now)
    view = store.effects.effect(first.effect_id)
    assert view is not None and view.status == "claimed"

    store.effects.published(second, now=now)
    view = store.effects.effect(first.effect_id)
    assert view is not None and view.status == "published"


def test_a_limit_bounds_one_claim(store: SqliteRuntimeStore) -> None:
    for key in "abc":
        _intent(store, "t", key)

    claimed = store.effects.claim(
        ["t"], now=datetime.now(UTC), lease_seconds=60, limit=2
    )

    assert len(claimed) == 2
