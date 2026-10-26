# Effect Receiver — an outbox consumer that deduplicates by key

An [`EffectReceiver`](https://github.com/raicing-ai/functualize/blob/master/docs/api/workflow.md#effect-receivers)
plugin: it receives every effect a gate's acceptance publishes on the
`gate.accepted` topic and applies each one exactly once, keyed by the
intent's `idempotency_key`.

## Why deduplicate

Delivery is **at least once** (ADR-034). The accepted answer, its decision
and the effect intent commit in one transaction, and a dispatcher hands the
intent to this receiver — but a process that dies between the receiver and
the acknowledgement leaves the claim to expire, and the intent is delivered
**again**: by the next boot, the next answer, the next resume. Exactly-once
application is therefore the receiver's to keep, and the key is how:
`gate.accepted:<request_id>` is stable, so the second delivery of the same
intent is a no-op here.

This example keeps the applied-key set in memory, which deduplicates within
a process and exists to be read. A production receiver persists the set
beside whatever it applies the effect to, so a restart redelivers into a
no-op rather than a duplicate.

## What registering declares

Registering a receiver is the declaration that this project's store must
have a durable outbox. With `runtime_store.url = "sqlite:"` that holds; on
the default document store boot refuses, naming `runtime_store.url` as the
setting to change — because silently dropping every committed intent is the
failure the outbox exists to prevent. Registration happens in the plugin's
registration call, before boot selects the store; one receiver per topic.

## The plugin

```python
class AuditReceiver:
    topic = "gate.accepted"

    def __init__(self) -> None:
        self._applied: set[str] = set()
        self.audit: list[str] = []

    def receive(self, effect) -> None:
        if effect.idempotency_key in self._applied:
            return  # at-least-once delivery: a redelivery is a no-op
        self._applied.add(effect.idempotency_key)
        ...  # apply the effect — once per key


class EffectReceiverPlugin:
    def __call__(self, app) -> None:
        app.extensions.register_effect_receiver(AuditReceiver())
```

## Run the tests

```bash
uv run pytest examples/plugins/effect_receiver -v
```

The end-to-end test answers a real gate over SQLite through the public
`answer_gate` door and watches the delivery arrive after the commit.
