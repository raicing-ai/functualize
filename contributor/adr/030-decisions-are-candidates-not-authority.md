# ADR-030: Decisions Are Candidates, Not Authority

**Status**: accepted
**Date**: 2026-09-30
**Deciders**: maintainer (D-1, D-2, D-3, S-3, S-4, Q-1, Q-2)

## Context

A workflow gate can be answered by a person, by the config chain, or by an AI
that fills the whole model (`ai_inbound`). A narrower and more common need is a
**closed choice**: route this ticket to one of three teams. A classifier service
can answer that with a probability per option, but a probability is not an
answer — something has to decide whether it is good enough, and that something
is where authority lives.

The measured wire contract of the first such service (the Jev System One API,
`contributor/reference/jev-system-one-capability-matrix.md`) shaped the rest:
the service returns a distribution and a separate `confidence` scalar that is
**not** `max(distribution)` (row B2); it refuses for load with a `429` and a
`Retry-After` measured in hours (row F4); and it answers text in a ticket as
data only if the request keeps that text out of its instructions.

The risk this decision exists to prevent is a gate that quietly becomes an
automated approver: a provider package that owns the threshold, a `confidence`
that a provider can raise to get itself accepted, or a failure that retries
until it succeeds.

## Decision

**A decision provider proposes; the gate's declared rule decides.**

1. **The seam is provider-neutral and lives in core.** `DecisionProvider` is a
   `Protocol` with one method, `choose(ChoiceRequest) -> DecisionResult[str]`.
   A result is a *candidate*: a value, a distribution, the provider's own
   `confidence`, and provenance. It has no `accepted` field and no boolean of
   any kind. A provider either returns a candidate among the offered options or
   raises `DecisionUnavailableError`; it makes at most one round trip and never
   sleeps or retries. Provider packages translate a wire and register the
   strategy — nothing else (`functualize-decision-jev` is the first).
2. **The rule is on the gate, declared by the workflow.**
   `Gate(decide=ChoiceDecision(field, instructions, options, state, accept_at,
   min_margin, model))`. The provider-neutral `DecisionGateResolver` (the
   `decision` strategy) accepts a proposal only when its probability reaches
   `accept_at` **and** it leads the runner-up by at least `min_margin`. The
   declaration is checked at import: the field must be a `Literal` of strings
   or a `StrEnum` whose values equal the options.
3. **`confidence` is never an input.** It is recorded on the result and never
   read by the acceptance rule; the resolver module does not name it. A
   provider cannot raise its own acceptance by claiming certainty.
4. **Provider failure is a failed rung.** A below-threshold proposal, a rate
   limit, a refusal or a malformed answer is recorded as a `failed` candidate
   with a readable detail, and the gate's ladder
   (`decision` → `prompt` → `resolve`) falls through to a person. No new node
   kind, walk outcome, request status or evaluation outcome is added: the gate
   stays the only thing that accepts an answer, on ADR-029's recorded ladder.
5. **Which options need a person is the workflow's choice, made with
   conditional edges (Q-1).** There is no `auto_accept` field. The gate's
   answer feeds a `ConditionalEdge`, and the author routes any branch that must
   be approved through a second `Gate` before its effecting step. An option
   routed straight to an effecting step runs on the provider's answer alone —
   the framework states this plainly rather than enforcing it.
6. **The rule is fenced by the graph digest (Q-2).** The declared decision is
   projected into the workflow shape, so the graph digest covers it and a walk
   parked under one rule refuses to resume under another, exactly as it does for
   a moved edge. Recording the rule structurally on the request is later work.

## Consequences

### Positive

- A second provider is a wire adapter and a registration; the policy, the
  failure handling and the audit trail are shared.
- An operator reading a blocked gate sees the proposal against the rule, e.g.
  `jev/jev-1.13-free proposed 'returns' at 0.54 (margin 0.08); workflow requires
  >= 0.70, margin >= 0.10`.
- A provider outage or rate limit degrades to a person, immediately, never to a
  retry loop or a guess.
- Text in the decided-about state reaches the provider as data only, and an
  answer outside the declared options is refused, so the state cannot open a
  branch the workflow did not declare.

### Negative

- "No confidence-only authorisation of consequential side effects" holds only
  where the author draws the approval gate (Q-1); a workflow that routes an
  option straight to an effecting step automates it.
- The acceptance comparison is an exact float comparison on probabilities
  reported to two decimals, so a lead printed as `0.10` can fail
  `min_margin=0.10`.
- Every walked gate now receives the walk's step results in
  `GateContext.workflow_context` — required for the `decision` strategy, and
  visible to every other strategy too.

### Neutral

- The provider vocabulary, `DecisionGateResolver` and `ChoiceDecision` are
  public and **provisional**, outside the names 1.0 promises to keep.
- Registration happens at `APP_READY`, because plugins load before the config
  resolution chain is built.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| **A-1.** A provider-specific gate strategy in the plugin, applying a threshold itself | Smallest change; no core seam | The provider package owns acceptance — the authority this decision forbids; a second provider duplicates the policy (duplicate code, then divergent change) | Puts authority in the adapter |
| **A-2.** Policy registered at boot, keyed by the awaits model class (`DecisionGateResolver(provider, policies={Route: …})`) | No `Gate` change | The threshold moves from the workflow declaration to app wiring, so the workflow no longer owns it; a model class used by two gates makes the policy ambiguous | Workflow loses ownership of its rule |
| **A-3.** Policy as a `ClassVar` on the awaits model | Workflow-owned; no `Gate` change | The resolver finds it by attribute name — an implicit convention the constitution forbids for ports — and it is invisible to `Gate`'s declaration checks | Implicit convention; unchecked |
| **A-4 (chosen).** Provider-neutral seam in core, policy on the `Gate`, adapter in its own plugin | Policy declared and checked where the workflow is written; any provider plugs in | One field on `Gate`, one on `GateContext`, one keyword on `GateRegistry.evaluate`, one more branch in the walker's strategy list | — |

## Addendum — fallback and evidence (2026-10)

**Deciders**: maintainer (D-1, D-2, D-3, D-4, S-1, S-4), 2026-10-01.

Point 4 sends every failed decision to a person. A router whose every miss
blocks is not a router, so a workflow may now name the option a miss takes —
and a router that decides is only auditable if each run records what it was
shown, what it proposed and why it was or was not taken. Four questions,
each answered as recommended:

- **D-1 — the default route is declared on the decision.**
  `ChoiceDecision(fallback=...)` names one of the options. A gate with a
  fallback is walked `decision` → `resolve`, and the **existing `resolve`
  rung** takes it: the registry seeds the decided field with the fallback and
  forces the decision rung to run first, so the provider is still asked
  exactly once. No node kind, walk outcome, request status, evaluation outcome
  or strategy name is added — the gate remains the only thing that accepts an
  answer. A default on the decided field is refused at import, because a
  fully defaulted answer completes the gate before any strategy runs. The
  fallback joins the decision's projection, so it is fenced by the graph
  digest like the rest of the rule (point 6).
- **D-2 — evidence lives on the rung's candidate.** `CandidateEvaluation`
  gains an optional `evidence` mapping, written only by the gate through a
  per-rung, write-once `RungEvidence` sink on `GateContext` (S-1: a mutable
  collector on a frozen context, accepted). An answer surface cannot write it.
  The decision rung records one flat `decision-evidence/1` mapping: the state's
  step and SHA-256, the rule's digest and thresholds, provider and model, the
  proposal, the distribution, the provider's `confidence` (recorded; the rule
  module still never names it — point 3), the probability and margin read,
  the verdict, any failure, the latency and the token counts. It is built in
  its own module, `_gate/decision_evidence.py`, so the rule module can keep
  that word out.
  The `decision-evidence/1` verdict set is `accepted`, `below_threshold`,
  `no_distribution`, `uncovered_proposal`, and `provider_failed`. The fifth
  value records a provider answer whose distribution omits its own proposal:
  the proposal and distribution remain recorded, while `probability`,
  `margin`, and `failure` are `null`. This is distinct from an absent
  distribution or a provider error and keeps that failed rung auditable.
- **D-3 — cost is token usage only.** Monetary cost needs a price table and is
  later work.
- **D-4 — one public, provisional reader.** `decision_record(store, scope_id,
  gate)` in `functualize.app.utils` projects the recorded candidates into one
  record — route, `decided_by` (`decision`, `fallback`, `person`), the reason
  the decision missed, the evidence — re-evaluating nothing. It tells a
  fallback from a decision by the candidate's `source` (S-4: mapping
  `strategy:resolve` to "fallback" reads `source`, accepted).

A gate without a fallback is unchanged: same ladder, same blocking, same
reason — it now also records evidence on its decision rung.

### Alternatives considered for the addendum

| Alternative | Cons | Why rejected |
|-------------|------|-------------|
| **A.** Evidence on the **answer model** (an `evidence` field the resolver fills); the resolver applies the fallback | An answer surface can submit any `evidence`, so it is forgeable; answer and provenance mixed in one model — divergent change on every awaits model; an absent provider has no evidence | Forgeable |
| **B.** Evidence in a **new evidence store/table**; the default route via a new `decision_fallback` strategy | Duplicates the durable candidate tables the runtime-persistence work owns — shotgun surgery when they land; a new strategy name breaks the pin that the strategy providers equal the valid strategies, and edges toward a new primitive | Duplicate storage; new primitive |
| **C.** Evidence in a provider **Decorator** that logs `DecisionResult`s | The provider cannot see the scope, so its records are uncorrelated with runs; a side channel outside the run record | Uncorrelated side channel |
| **D (chosen).** Evidence on the rung's `CandidateEvaluation`, through the per-rung sink; the fallback declared on `ChoiceDecision`, taken by the existing `resolve` rung | A mutable sink on a frozen context (S-1); evidence is an untyped JSON mapping | — |
