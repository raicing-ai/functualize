# ADR-029: Gate Resolution Is Recorded, Not Recomputed

**Status**: accepted
**Date**: 2026-09-27
**Deciders**: maintainer (D-1 through D-5)

## Context

A workflow gate used to be a payload field in the scope document. The question
had no identity, a strategy ladder retained only its winning answer, and a
second deposit could replace that answer. Replaying a walk or reading a draft
therefore had no recorded evaluation to consult.

The persistence ports already divide transition meaning from durability in
[ADR-025](025-engine-owns-transition-meaning.md). Gate resolution needs the
same ownership rule: the engine decides which request is open, which candidate
won, and when the walk has used it; a store commits those decisions without
running strategies or validating an old answer again.

## Decision

1. **The engine mints identity.** `InputRecorder` mints the request ID when a
   gate opens and the candidate ID for each ladder rung or submitted answer.
   The ID remains stable across a blocked walk, acceptance, and consumption.
   Minting before the write lets buffered commands in one transaction refer to
   the same request.
2. **Candidates append with their verdict.** Every rung and submission records
   its ordinal, source, payload, and evaluation at submission time. Evaluation
   outcomes include `accepted`, `invalid`, `failed`, `unavailable`, and
   `not_reached`. Reads project the recorded verdict and do not rerun a
   strategy or revalidate the candidate. An accepted answer cannot be
   overwritten by a later deposit.
3. **Consumption has one writer.** Only the walk moving past the gate emits the
   consume command. A resumed walk may replay the same answer, so consuming an
   already consumed request is idempotent.
4. **Reopen supersedes.** While the walk is still parked at a gate, correcting
   an answer archives the accepted request as cancelled and opens a new request
   with a new ID. The old candidates remain in its history. The transition
   model must admit `accepted → cancelled`; it must not rewrite the accepted
   request to `open`.

The engine and recorder choose these transitions; the runtime input port and
its backend commit them. This is ADR-025's engine/storage boundary applied to
gate decisions. The current document backend stores requests and candidates
inside `scopes.json` as `TRANSITIONAL(FUN-21)`. Independently durable request,
candidate, evaluation, and interaction evidence storage remains pending.

## Consequences

### Positive

- A surface can name the question by request ID and show the recorded ladder,
  including failed and unavailable rungs, without changing its verdict on read.
- An invalid submission remains visible while its request stays open; a second
  accepted deposit is refused rather than silently replacing the first.
- Reopening preserves both the earlier answer and the correction as separate
  requests.

### Negative

- The document backend's nested gate record is a transitional storage location.
  The durable interaction slice must move answer surfaces to the selected
  runtime store and make evidence readable independently of the scope document.
- The legacy direct `ScopeStore.deposit_gate_payload` helper remains for old
  test callers and does not provide the new candidate guard.

### Neutral

- The visible `blocked_reason` text is unchanged. Ladder failures are recorded
  in addition to the existing operator-facing message.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Let storage mint request and candidate IDs at commit | IDs are assigned beside persisted rows | A buffered candidate command cannot name its request before the batch commits | The recorder must establish identity before issuing related commands |
| Keep only the winning payload or recompute evaluations on read | Smaller records | Loses failed attempts and can change a past verdict when strategies or validators change | An evaluation is a fact about the submission, not a live query |
| Reopen the same request in place | Fewer records | Rewrites accepted history and makes a correction look like the original answer | Superseding preserves both decisions and their identities |
| Let an answer surface mark a request consumed | Can combine deposit and resume in the surface | Claims the walk used input before it actually moved past the gate | The walk is the single consumption writer |
