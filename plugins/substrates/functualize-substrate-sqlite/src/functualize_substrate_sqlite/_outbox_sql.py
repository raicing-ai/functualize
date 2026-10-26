"""`SqlEffectQueue`: the outbox's claim-and-acknowledge side, over ``outbox``.

Three short writes, each its own unit and none of them around a receiver
call (data model §4: *dispatch effect* claims a row, *acknowledge effect*
settles it, and the provider call runs with no transaction open):

- **claim** is one ``UPDATE … WHERE id IN (SELECT … LIMIT n)`` stamping a
  fresh ``claim_token``, so two dispatchers — two processes on one file —
  never take the same row in the same instant; the rows are then read back by
  that token. Due means ``pending`` and available, or ``claimed`` under a
  lease that has expired: the dispatcher holding it died between the receiver
  and the acknowledgement, and delivering it again is what at-least-once
  means.
- **published** and **failed** are conditioned on the token they were handed,
  so an acknowledgement from a dispatcher whose claim expired and was retaken
  changes nothing.

Timestamps compare as text, which is chronological because `iso` writes every
one in UTC at one width.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from functualize._primitives.transitions import require_transition
from functualize._types.lifecycle import OUTBOX
from functualize.plugin import EffectView
from functualize_substrate_sqlite._transaction import iso, parse_iso

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from functualize_substrate_sqlite._driver import SqlDriver

__all__ = ["SqlEffectQueue"]

_COLUMNS = (
    "id, topic, aggregate_type, aggregate_id, payload, idempotency_key, status, "
    "attempts, available_at, claimed_at, published_at, last_error, claim_token"
)


def _view(row: tuple[Any, ...]) -> EffectView:
    return EffectView(
        effect_id=row[0],
        topic=row[1],
        aggregate_type=row[2],
        aggregate_id=row[3],
        payload=json.loads(row[4]) if row[4] is not None else None,
        idempotency_key=row[5],
        status=row[6],
        attempts=int(row[7]),
        available_at=parse_iso(row[8]),
        claimed_at=parse_iso(row[9]) if row[9] else None,
        published_at=parse_iso(row[10]) if row[10] else None,
        last_error=row[11],
        claim_token=row[12],
    )


class SqlEffectQueue:
    """`EffectQueue` over the ``outbox`` table of one namespace."""

    def __init__(self, driver: SqlDriver, namespace: str) -> None:
        self._driver = driver
        self._namespace = namespace

    def claim(
        self,
        topics: Sequence[str],
        *,
        now: datetime,
        lease_seconds: float,
        limit: int,
    ) -> tuple[EffectView, ...]:
        if not topics or limit <= 0:
            return ()
        token = uuid4().hex
        stamp = iso(now)
        expired = iso(now - timedelta(seconds=lease_seconds))
        marks = ", ".join("?" for _ in topics)
        self._driver.batch(
            [
                (
                    "UPDATE outbox SET status = 'claimed', claimed_at = ?, "
                    "claim_token = ?, attempts = attempts + 1 WHERE id IN ("
                    "SELECT id FROM outbox WHERE namespace_id = ? "
                    f"AND topic IN ({marks}) AND ((status = 'pending' AND "
                    "available_at <= ?) OR (status = 'claimed' AND "
                    "claimed_at <= ?)) ORDER BY available_at, rowid LIMIT ?)",
                    (stamp, token, self._namespace, *topics, stamp, expired, limit),
                )
            ]
        )
        rows = self._driver.query(
            f"SELECT {_COLUMNS} FROM outbox WHERE namespace_id = ? "
            "AND claim_token = ? ORDER BY available_at, rowid",
            (self._namespace, token),
        )
        return tuple(_view(row) for row in rows)

    def published(self, effect: EffectView, *, now: datetime) -> None:
        require_transition(OUTBOX, effect.status, "published")
        self._driver.batch(
            [
                (
                    "UPDATE outbox SET status = 'published', published_at = ?, "
                    "last_error = NULL WHERE namespace_id = ? AND id = ? "
                    "AND status = 'claimed' AND claim_token = ?",
                    (iso(now), self._namespace, effect.effect_id, effect.claim_token),
                )
            ]
        )

    def failed(self, effect: EffectView, *, error: str, retry_at: datetime) -> None:
        require_transition(OUTBOX, effect.status, "pending")
        self._driver.batch(
            [
                (
                    "UPDATE outbox SET status = 'pending', available_at = ?, "
                    "last_error = ?, claim_token = NULL, claimed_at = NULL "
                    "WHERE namespace_id = ? AND id = ? AND status = 'claimed' "
                    "AND claim_token = ?",
                    (
                        iso(retry_at),
                        error,
                        self._namespace,
                        effect.effect_id,
                        effect.claim_token,
                    ),
                )
            ]
        )

    def effect(self, effect_id: str) -> EffectView | None:
        rows = self._driver.query(
            f"SELECT {_COLUMNS} FROM outbox WHERE namespace_id = ? AND id = ?",
            (self._namespace, effect_id),
        )
        return _view(rows[0]) if rows else None
