# hermetic-router — specification

Phase 2 of the decision-layer experiment: **one small reference workflow** whose
route is proposed by a decision provider and decided by a `Gate`, with every
routing decision recorded as first-class, auditable evidence.

**Status: confirmed by the member, 2026-10-01** (native Specify step 6), with
every decision and flagged smell answered as recommended: D-1 A (declared
fallback, taken by `resolve`), D-2 A (evidence on the rung's evaluation), D-3 A
(tokens only), D-4 A (`decision_record`), S-1 and S-4 accepted. `plan.md` →
*Decisions* records each. A change to this file sends `plan.md` and
`tasks.md` back for revision before any `src/**` write.

## 1. Problem

Phase 1 (merged at `ef1939d`) gave a `Gate` a declared decision:
`Gate(decide=ChoiceDecision(field, instructions, options, state, accept_at,
min_margin))`. A provider proposes; the gate's declared thresholds decide; a
proposal that does not clear them **blocks the walk for a person**.

A router needs two things Phase 1 left open, and its scope (`spec.md` §6 of
Phase 1) handed both to this phase:

1. **A declared default route.** "Low confidence → human review" is a route
   the workflow continues down, with the reason recorded — not a walk parked
   at the router. And the workflow must run unchanged when no decision
   provider is installed.
2. **The decision as evidence.** Today the distribution, the provider and
   model, latency and token usage survive only inside a failed rung's
   `detail` *text*, and on an **accepted** rung they are not recorded at all
   (`detail` is `""`). Nobody can audit why a run took a route, nor compare two
   runs over the same input.

### 1.1 Facts this specification rests on (measured on this branch, `ef1939d`)

| # | fact | how it was measured |
|---|---|---|
| F-1 | **A default on the decided field silently bypasses the decision.** `Route.route = "human_review"` with `Gate(decide=...)` is accepted at declaration; `GateRegistry.evaluate` short-circuits on "every field resolved" and records one rung `('resolve', 'accepted')`; the provider is called **0** times. The obvious way to declare a default route is therefore wrong today, and the record credits the config chain. | scratch probe calling `Gate(...)` and `GateRegistry.evaluate(Route, gate_strategy=["decision","prompt","resolve"], decision=d)` with a counting resolver → `provider calls: 0 rungs: [('resolve', 'accepted')]`; code path `src/functualize/_gate/_registry.py` step 2 (`if not unresolved_fields and not force_gate`) |
| F-2 | An accepted rung records `CandidateEvaluation(ACCEPTED)` with empty `detail`; a failed rung records `detail=str(exc)`. No structured field exists for evidence. | `src/functualize/_gate/_registry.py` (`evaluate`, rung construction); `src/functualize/_types/gate_resolution.py` (`CandidateEvaluation` has `outcome`, `detail`, `errors`) |
| F-3 | Candidates persist only in the document store, nested under each gate in `scopes.json` (`TRANSITIONAL(FUN-21)`); no SQL store persists candidates. | `rg -l -i candidate plugins/substrates --type py` → no files; writer `src/functualize/_primitives/gate_requests.py::append_candidate`, reader `::candidates_for` |
| F-4 | Recorded candidates are already readable through a public function: `functualize.app.utils.gate_draft(app, store, scope_id, gate)["resolution"]["candidates"]`. | `src/functualize/app/_workflow_answer.py::gate_draft` → `_workflow_resume._resolution_view` |
| F-5 | `tests/workflow/test_gate_drafts.py` pins a candidate's projected dict **exactly** (seven keys). Adding a key unconditionally breaks it; adding one only when present does not. | `tests/workflow/test_gate_drafts.py:176-186` |
| F-6 | `GateRegistry.evaluate` has exactly two callers: `GateRegistry.resolve_gate` and `GateService.service`. | `rg -n "\.evaluate\(" src plugins --type py` |
| F-7 | ADR-030 point 3: the resolver module never names `confidence`. Measured: `rg -c confidence src/functualize/_gate/` → 0. | ADR-030; rg |
| F-8 | The decision rule is projected into the graph digest by `_decision_shape` in `src/functualize/_types/workflow.py` (2 references); a gate without `decide` projects to exactly `{"gate", "model"}`. | `rg -n _decision_shape src tests` |
| F-9 | The `decision` gate's ladder is `decision → prompt → resolve` (`_gate_strategy_list`, `src/functualize/_engine/gate_service.py`). With the provider plugin absent, the `decision` rung records `unavailable` with the hint `install functualize-decision-jev to register it`. | code; Phase 1 AC-15 |
| F-10 | Wire facts kept from Phase 1 (capability matrix, `contributor/reference/jev-system-one-capability-matrix.md`): the yes/no tag is `noul`, not `null`; a `noul` answer carries no boolean, no `confidence`, no `probabilities`; `score` = Σ index × probability; `probabilities` key order is unstable; identical requests vary (a near-tied decision flipped argmax 9/20). | matrix rows A3, B1, B3, C1–C2, G1–G2 |

## 2. Users

- **Workflow author** — declares the router: the routes, what each means, the
  thresholds, and the route taken when the proposal is not good enough.
- **Operator / auditor** — reads, per run, which route was taken, by whom
  (provider, fallback, person) and why.
- **Evaluator (Phase 3)** — replays a corpus and compares runs; needs each
  run's decision as data, and two runs over the same input to be comparable.

## 3. User stories

- **US-1.** As a workflow author, I declare a default route on the decision
  itself, so a weak proposal, a provider failure, or a missing provider sends
  the run down that route instead of guessing or parking.
- **US-2.** As an operator, I read one record per routed run that says the
  route, whether the fallback was used, the reason, and the evidence behind
  it.
- **US-3.** As an evaluator, I run the same input twice and can see — from the
  two records alone — that the input and the rule were identical and the
  provider's distribution was not.
- **US-4.** As anyone without the provider installed, the reference workflow
  still runs, and takes the declared default.

## 4. Behaviour

### 4.1 The declared default route

- **B-1.** A decision may declare a **fallback**: one of its own options,
  taken when the proposal does not clear the declared thresholds, when the
  provider fails, or when no provider is registered.
- **B-2.** The declaration is checked when the workflow is declared
  (`ValueError`, like every other `Gate` check): the fallback must be one of
  the options; the decided field must have **no default** (closing F-1, with a
  message pointing at the fallback); and when a fallback is declared, every
  *other* field of the awaited model must have a default, so the fallback alone
  completes the answer.
- **B-3.** A gate whose decision declares a fallback always asks the provider
  first. It never blocks at the router: the outcome is either the accepted
  proposal or the fallback. Its ladder is `decision → resolve`, where `resolve`
  takes the declared fallback.
- **B-4.** A gate whose decision declares **no** fallback behaves exactly as in
  Phase 1: `decision → prompt → resolve`, and a weak proposal blocks for a
  person.
- **B-5.** The fallback is part of the decision rule, so it joins the graph
  digest; a decision without a fallback projects exactly as it does on
  `master` (its digest does not move).

### 4.2 The decision as evidence

- **B-6.** Every time the `decision` rung asks the provider, the rung records
  **evidence** beside its outcome — accepted, below threshold, or provider
  failure alike. Evidence is written by the gate, never supplied by whoever
  answers it: a candidate submitted through an answer surface carries none.
- **B-7.** Evidence carries: the evidence format revision; the **state
  identity** (the state step's name, the SHA-256 and the length of the exact
  text sent — not the text); the **rule identity** (a digest of the declared
  decision, and the `accept_at`, `min_margin` and fallback it holds); the
  provider name, the model that answered and the model requested; the proposed
  option; the **distribution as returned** and the provider's `confidence`
  (recorded, never consulted); the proposal's probability and margin as the
  gate computed them; the verdict; the provider failure kind, HTTP status and
  `Retry-After` when it failed; the latency of the provider call as the gate
  measured it; and input/output token usage when reported.
- **B-8.** The **cost** recorded is the provider's reported token usage. No
  monetary figure is computed in this phase (D-3).
- **B-9.** A **decision record** is readable per run and gate through the
  public API: the selected route, who decided it (`decision`, `fallback`,
  `person`, or nothing yet), whether the fallback was used, the reason when it
  was (the failed decision rung's detail, or the missing-provider hint), and
  the decision rung's evidence. It is a projection of what the ladder
  recorded; nothing is re-evaluated to build it.
- **B-10.** On resume, a recorded answer is replayed: the provider is **not**
  called again, and no second evidence is written.
- **B-11.** Two runs over identical input are two records. Neither overwrites
  the other; the state and rule identities match; the distributions may
  differ, and the records show it.

### 4.3 The reference workflow

- **B-12.** One reference workflow, under `examples/`: unstructured text in; a
  router gate deciding `route` among exactly
  `deterministic | cheap_model | frontier_agent | human_review`; declared
  thresholds and `fallback="human_review"`; one stub step per automated route;
  and a human `Gate` on the `human_review` route.
- **B-13.** The route steps are stubs that report which route ran. The
  workflow calls no model, holds no model client and selects no provider —
  routing is all it shows.
- **B-14.** No step reachable from the router is consequential
  (`effecting=True`) without first passing a human `Gate`. The reference
  workflow declares none; a test asserts this over the graph.
- **B-15.** The workflow runs unchanged with no decision provider registered:
  it takes `human_review`, and the record says why.

## 5. Acceptance criteria

Each is decidable by a command; `tasks.md` binds each to its gate. Thresholds
used below: `accept_at=0.70`, `min_margin=0.10`, `fallback="human_review"`.

- **AC-1** (B-2). Declaring a fallback outside the options, a decided field
  with a default, or a fallback beside another required field each raises
  `ValueError` at declaration; the message for the default names `fallback=`.
- **AC-2** (B-3, B-9). A proposal `cheap_model` at 0.82 (runner-up 0.10) runs
  the `cheap_model` stub and no other route; the record reads route
  `cheap_model`, decided by `decision`, fallback not used.
- **AC-3** (B-1, B-3, B-9). A proposal `deterministic` at 0.55 (margin 0.20)
  does **not** run the `deterministic` stub; the route is `human_review`, the
  fallback was used, the reason contains `proposed 'deterministic' at 0.55`,
  and the walk stops at the human review gate.
- **AC-4** (B-1, B-7). A provider raising *rate limited* (`Retry-After: 19014`)
  routes to `human_review` within one second of wall clock without sleeping;
  the evidence carries failure kind `rate_limited`, status 429 and
  `retry_after` 19014.
- **AC-5** (B-15, US-4). With no `decision` strategy registered, the route is
  `human_review`, decided by `fallback`, and the reason contains `install
  functualize-decision-jev`.
- **AC-6** (B-7). For AC-2's run the evidence equals, key for key, the shape in
  `contracts.md` C-3: `state.sha256` is the SHA-256 of the intake text,
  `rule.digest` equals `decision_digest` of the declared decision, the
  distribution equals the returned mapping (compared as a mapping), and
  `input_tokens`/`output_tokens` equal the reported usage.
- **AC-7** (B-7, standing guard). A proposal below threshold with `confidence`
  1.0 falls back; one above threshold with `confidence` 0.0 is accepted.
  `rg -c confidence src/functualize/_gate/decision_strategy.py` stays 0.
- **AC-8** (B-11). Two runs in two scopes over identical text with different
  returned distributions produce two records with equal `state.sha256` and
  `rule.digest` and unequal `distribution`.
- **AC-9** (B-10). Resuming a scope whose route was accepted calls the
  provider no further time, and the decision record is unchanged.
- **AC-10** (B-6). A person answering the human review gate leaves a candidate
  with no evidence, and a payload carrying an `evidence` key does not add any.
- **AC-11** (B-4, B-5). A decision without a fallback keeps Phase 1's ladder
  (`decision`, `prompt`, `resolve`) and its graph-shape projection has no
  `fallback` key; `tests/integration/test_decision_gate_e2e.py` and
  `tests/workflow/test_gate_drafts.py` pass unchanged.
- **AC-12** (B-5). Two declarations differing only in `fallback` have
  different graph digests.
- **AC-13** (standing guard). No new authority primitive: the gate strategy
  names, the five `EvaluationOutcome` members, the walk outcomes and the node
  kinds are unchanged.
- **AC-14** (B-14). The reference workflow has no `effecting=True` step
  reachable from the router without passing a human `Gate`.
- **AC-15** (B-12, B-13). Exactly one new example directory; it imports no
  model client (`functualize_ai`, `openai`, `anthropic`, `httpx`, `urllib`)
  and no provider package.
- **AC-16** (F-10, kept). The Phase 1 wire tests
  (`tests/plugins/test_jev_wire.py`, `tests/plugins/test_jev_decision_provider.py`)
  pass unchanged; this phase changes no wire mapping.

## 6. Out of scope

- A model gateway, provider selection among several providers, a routing
  framework, a second workflow, or any real model call from a route step.
- `noul` and `score` mapping; batching questions.
- Monetary cost (D-3), calibration, threshold tuning, corpus replay — Phase 3.
- Storing evidence in SQL tables: the `input_candidates` table is FUN-18/FUN-21
  work; this phase records evidence in the document store's candidate entry,
  which is already `TRANSITIONAL(FUN-21)`, and documents the JSON column it
  will need.
- Rounding before the margin comparison (Phase 1 open item; unchanged).
- A live run against the service in CI; the live provider test still skips
  without `OPENCODE_API_KEY`.

## 7. Standing constraints, restated as testable lines

- **No new authority primitive** — AC-13. The fallback is taken by the existing
  `resolve` rung; no strategy name, outcome, status, node kind or walk outcome
  is added.
- **Jev is a candidate generator** — evidence is the gate's record of a
  candidate; the provider never writes it, and `confidence` is never an input
  (AC-7).
- **No Gate renames, no mandatory Jev dependency** — AC-5, AC-15; core still
  imports no `functualize_decision_jev` (`rg -c functualize_decision_jev src` → 0).
- **Never authorize a consequential side effect from confidence alone** —
  AC-7, AC-14.
- **No "hermetic" or "zero hallucinations" claim** — the property supported is
  auditability of variance (AC-8), not reproducibility of the provider.
