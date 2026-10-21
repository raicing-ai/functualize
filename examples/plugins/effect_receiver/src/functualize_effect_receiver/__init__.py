"""An outbox effect receiver, applied exactly once per idempotency key.

Implements the `EffectReceiver` protocol from `functualize.plugin` and
registers it through `app.extensions.register_effect_receiver`, the door a
plugin uses, from its registration call — which runs **before** boot selects
the store, because registering a receiver is the declaration that this
project's store must have a durable outbox (boot refuses the document store
with a receiver registered, naming `runtime_store.url` as the setting to
change).

Delivery is **at least once** (ADR-034): a process that dies between the
receiver and the acknowledgement leaves the claim to expire, and the intent
is delivered again — by the next boot, the next answer, the next resume. So
the one obligation on a receiver is to apply each `idempotency_key` once.
This example keeps the applied-key set in memory, which deduplicates within
a process and exists to be read; a production receiver persists the set
beside whatever it applies the effect to, so a restart redelivers into a
no-op rather than a duplicate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize.plugin import EffectView

__all__ = ["AuditReceiver", "EffectReceiverPlugin"]

#: The one topic a gate's acceptance publishes under.
GATE_ACCEPTED = "gate.accepted"


class AuditReceiver:
    """Receives each accepted gate, applying every key exactly once.

    The deduplication is the point: ``receive`` may be handed the same intent
    more than once, and the second hand-off is a no-op, not a duplicate
    application. Everything else a receiver does is its own — this one keeps
    an audit line per applied effect.
    """

    topic = GATE_ACCEPTED

    def __init__(self) -> None:
        self._applied: set[str] = set()
        self.audit: list[str] = []

    def receive(self, effect: EffectView) -> None:
        """Apply the effect once; a redelivery of the same key is a no-op."""
        if effect.idempotency_key in self._applied:
            return
        self._applied.add(effect.idempotency_key)
        payload = effect.payload if isinstance(effect.payload, dict) else {}
        self.audit.append(
            f"{effect.idempotency_key} gate={payload.get('gate')} "
            f"request={payload.get('request_id')}"
        )


class EffectReceiverPlugin:
    """Registers the audit receiver, the way a consumer package would."""

    name = "effect-receiver"
    version = "0.1.0"
    description = "Registers an at-least-once gate-effect receiver"

    def __init__(self, receiver: Any | None = None) -> None:
        self._receiver = receiver if receiver is not None else AuditReceiver()

    @property
    def receiver(self) -> Any:
        """The receiver this plugin registers — the handle a test reads."""
        return self._receiver

    def __call__(self, app: Any) -> None:
        app.extensions.register_effect_receiver(self._receiver)
