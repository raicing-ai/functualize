"""The outbox dispatcher — committed intents, delivered at least once.

A transition records the intent to reach the outside world in its own
transaction (``EffectWriter``); this module is the other half, and it runs
with **no transaction open**. One drain is a loop of three short steps,
straight off the data model's transaction catalogue (§4):

1. **claim** due intents for the topics a receiver exists for
   (``EffectQueue.claim`` — one write, a fresh claim token);
2. **deliver** each to its receiver — the only call that can take long, and
   the reason nothing here holds a transaction;
3. **acknowledge**: ``published`` when the receiver returned, ``failed`` with
   the error and a retry time when it raised.

**Delivery is AT-LEAST-ONCE with consumer dedup.** A process that dies after
the receiver acted and before the acknowledgement landed leaves the claim in
place; once its lease expires the intent is claimed and delivered again. A
receiver raising is retried later. So a receiver sees an intent one or more
times and deduplicates on ``EffectView.idempotency_key`` — this module makes
no single-delivery promise, and nothing built on it may claim one.

**Deployment: in-process and synchronous.** ``_app`` drains once when boot
finishes and once after each answer surface commits; there is no thread and no
separate worker, so shutdown has nothing to join and a kill costs only an
unacknowledged claim, which the lease returns. A receiver that blocks blocks
the drain that called it, deliberately — a slow receiver is the receiver's to
make asynchronous, not this module's to hide.

This module sits in ``_primitives`` and imports ``_types`` only; ``_app``
composes it (``_app/effects.py``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from functualize._types.persistence import (
        EffectQueue,
        EffectReceiver,
        EffectView,
    )

__all__ = [
    "BATCH_SIZE",
    "CLAIM_LEASE_SECONDS",
    "DrainReport",
    "OutboxDispatcher",
    "retry_delay",
]

logger = logging.getLogger(__name__)

#: How long a claim protects an intent from a second dispatcher. Past it, a
#: dispatcher that has not acknowledged is presumed dead and the intent is
#: delivered again.
CLAIM_LEASE_SECONDS = 60.0
#: Intents claimed per round of one drain.
BATCH_SIZE = 50
#: Rounds per drain: a bound, so a receiver that keeps producing work for its
#: own topic cannot keep one drain running for ever.
MAX_ROUNDS = 20
#: The first retry waits this long; each further one doubles, up to the cap.
_RETRY_BASE_SECONDS = 5.0
_RETRY_CAP_SECONDS = 15 * 60.0
#: An error recorded on a row is a diagnosis, not a log; bounded.
_ERROR_MAX = 2000


def retry_delay(attempts: int) -> timedelta:
    """How long after its ``attempts``-th failed delivery an intent is due again.

    5 s, 10 s, 20 s … doubling, capped at 15 minutes.
    """
    exponent = max(attempts, 1) - 1
    seconds = min(_RETRY_BASE_SECONDS * (2**exponent), _RETRY_CAP_SECONDS)
    return timedelta(seconds=seconds)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class DrainReport:
    """What one drain did: how many were delivered, how many rescheduled."""

    delivered: int = 0
    failed: int = 0


class OutboxDispatcher:
    """Claims due intents, hands each to its topic's receiver, acknowledges.

    One receiver per topic. Intents for a topic nobody receives are never
    claimed: they wait, committed, for the first process that registers a
    receiver for them.
    """

    def __init__(
        self,
        queue: EffectQueue,
        receivers: Mapping[str, EffectReceiver],
        *,
        clock: Callable[[], datetime] = _utcnow,
        lease_seconds: float = CLAIM_LEASE_SECONDS,
        batch_size: int = BATCH_SIZE,
        max_rounds: int = MAX_ROUNDS,
    ) -> None:
        self._queue = queue
        self._receivers = dict(receivers)
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._batch_size = batch_size
        self._max_rounds = max_rounds

    @property
    def topics(self) -> tuple[str, ...]:
        """The topics this dispatcher claims, sorted."""
        return tuple(sorted(self._receivers))

    def drain(self) -> DrainReport:
        """Deliver every due intent for this dispatcher's topics, then stop.

        A receiver that raises is rescheduled and the drain carries on with
        the next intent; an error from the queue itself propagates, because
        an outbox that cannot be read is a store problem the caller decides
        about. ``BaseException`` (an interrupt) propagates with the claim
        held, which is exactly the crash the lease exists for.
        """
        delivered = failed = 0
        topics = self.topics
        if not topics:
            return DrainReport()
        for _round in range(self._max_rounds):
            claimed = self._queue.claim(
                topics,
                now=self._clock(),
                lease_seconds=self._lease_seconds,
                limit=self._batch_size,
            )
            if not claimed:
                break
            for effect in claimed:
                if self._deliver(effect):
                    delivered += 1
                else:
                    failed += 1
        return DrainReport(delivered=delivered, failed=failed)

    def _deliver(self, effect: EffectView) -> bool:
        receiver = self._receivers[effect.topic]
        try:
            receiver.receive(effect)
        except Exception as exc:  # noqa: BLE001 — a receiver's failure is data
            error = f"{type(exc).__name__}: {exc}"[:_ERROR_MAX]
            retry_at = self._clock() + retry_delay(effect.attempts)
            logger.warning(
                "outbox: receiver for %r raised on %s (attempt %d); retrying at %s: %s",
                effect.topic,
                effect.effect_id,
                effect.attempts,
                retry_at.isoformat(),
                error,
            )
            self._queue.failed(effect, error=error, retry_at=retry_at)
            return False
        self._queue.published(effect, now=self._clock())
        return True
