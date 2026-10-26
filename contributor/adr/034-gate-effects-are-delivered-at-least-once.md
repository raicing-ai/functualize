# ADR-034: Gate Effects Are Delivered At Least Once

**Status**: accepted
**Date**: 2026-10-21
**Deciders**: maintainer, through the approved shape intent *Gate Interactions,
Evidence, and the Transactional Outbox* (SD page 20086800 v2, owner approval
2026-10-19) and the spec's settled provisional items (§5).

## Context

A gate answer is a state change with a side effect waiting behind it: the
moment a candidate is accepted, something outside the workflow — an
integration, an audit trail, a webhook — is supposed to hear about it. The
two halves can be separated by a crash in either direction, and both
separations are the same bug:

- **Commit without effect.** The answer is recorded and the process dies
  before anything is told. The effect is lost, silently, and nothing in the
  store says it was ever owed.
- **Effect without commit.** Something is told, the process dies before the
  answer is recorded, and the resume answers again — the effect fires twice
  for one decision.

An engine cannot make an external effect transactional. What it *can* do is
make the intent to deliver durable in the same instant as the decision, and
be honest about what happens after: delivery may be attempted more than once,
so exactly-once — if a consumer needs it — is the consumer's own deduplication.

The infrastructure already half-existed. `FUN-19`'s SQLite store declared
`durable_outbox=True` and carried an `outbox` table with an `EffectWriter` —
and nothing claimed, delivered or acknowledged a row. The document store
declares `durable_outbox=False` and refuses to record an intent at all.

## Decision

**An effect is committed to a durable outbox in the same transaction as the
state change that caused it, and delivered at least once; exactly-once is the
consumer's job, via the idempotency key.**

- **One commit carries both halves.** A gate acceptance appends the accepted
  candidate, its `GateDecision` and its effect intent — topic
  `gate.accepted`, idempotency key `gate.accepted:<request_id>` — in **one**
  transaction unit. A crash leaves all three or none; there is no committed
  answer with no owed effect, and no owed effect for an answer that never
  happened.
- **A store that cannot make this promise says so.** `durable_outbox` is a
  profile fact: SQLite declares `True` and hands out the queue; the document
  store declares `False`, is never asked to record an intent, and runs no
  dispatcher. Registering an `EffectReceiver` declares that this
  configuration needs the capability — boot step 6.5 refuses a selected store
  whose profile lacks it, naming the receivers' topics, and refuses a store
  whose profile and type disagree, so the declaration has one meaning.
- **Delivery is in-process and synchronous.** One drain at the end of boot —
  which is what delivers an intent committed by a process that died before
  delivering it — one after each answer-surface commit, one after `resume`.
  No thread, no worker: shutdown has nothing to join, and a kill costs only
  an unacknowledged claim.
- **At least once, with a lease.** The dispatcher claims due intents under a
  claim lease, hands each to its topic's receiver outside any transaction,
  and acknowledges (`published`) or reschedules (`pending`, `last_error`,
  `available_at`). A claim that is never acknowledged — the process died
  between the receiver and the acknowledgement — becomes claimable again
  once the lease expires, and the intent is delivered again.
- **The receiver deduplicates on `idempotency_key`.** A receiver may see the
  same intent more than once; it must apply each key once. The framework
  never promises a single delivery, and nothing built on the outbox may claim
  one.

## Consequences

### Positive

- A committed answer can no longer lose its effect: the next process that
  starts with a receiver for its topic delivers it (proven against a real
  `os._exit` between commit and dispatch in `tests/workflow/test_gate_outbox_recovery.py`).
- The guarantee is one sentence a consumer can build on: at-least-once
  delivery, exactly-once application if the consumer deduplicates by key.
- The document store keeps its honest `durable_outbox=False`: no silent
  tier, no half-outbox, and a receiver registered against it refuses boot
  with the setting to change.

### Negative

- A receiver that is not idempotent by key can apply an effect twice. The
  obligation is documented on the protocol, the dispatcher and the example
  (`examples/plugins/effect_receiver/`), but it is the receiver's to keep.
- Delivery waits for a drain. Between commit and the next drain the intent
  sits committed and undelivered; the window is bounded by the drains, not by
  a poller.

### Neutral

- `Notify` is unchanged: record-first, at-most-once, delivered by the
  notifier provider — deliberately not this outbox (spec §6). Its
  documentation no longer calls that rule "the outbox".
- A future outbox topic beyond `gate.accepted` (a step-effect topic, a
  notify-via-outbox) reuses the dispatcher and this decision's contract
  unchanged.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|--------------|
| Call the receiver inside the transaction | One commit; no gap | Holds the store's unit across unbounded user code; a slow receiver blocks every write and a crash rolls back an effect that already happened | The data model forbids a transaction around a provider call; the outbox exists precisely to move delivery outside it |
| A background dispatcher thread started at boot | Shorter commit-to-delivery window | Needs join-on-shutdown and a policy for daemon death; a second thing running work beside the engine | Rejected by the shape's settled deployment mode: synchronous drains, no thread |
| At-most-once (record and try once, drop on failure) | Simplest; no dedup obligation on anyone | Loses effects — the first half of the bug this feature exists to close; a dropped webhook with no trace is worse than a duplicate the receiver can ignore | Losing a committed decision's effect silently is the failure mode; a visible duplicate with a key is not |
| Exactly-once via two-phase commit with the receiver | No duplicates, no losses | No such protocol exists over an arbitrary receiver; the receiver would have to be transactional with the store, which is the consumer's system, not ours | Exactly-once delivery across systems is not achievable; exactly-once *application* is, and it is one `set` lookup by key |
