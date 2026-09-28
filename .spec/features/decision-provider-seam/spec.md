# decision-provider-seam — specification

Phase 1 of the Jev / System One decision-layer experiment: a provider-neutral
decision seam, a Jev adapter behind it, and one `choice` decision driven
through a workflow `Gate`.

**Status: specified, not confirmed.** Specify-phase confirmation (native step 6
of `/agentic-specify`) and the Plan-phase task review (step 11 of
`/agentic-plan`) are both outstanding. Nothing in `tasks.md` may start until
both are recorded. Answered 2026-09-28: D-1 (own package, renamed
`functualize-decision-jev`), D-2 (the rule is declared on the `Gate`), S-4 (the
decision types are public API). Still open: D-3, S-3, Q-1, Q-2 — `plan.md` →
*Decisions*.

## 1. Problem

A workflow that has to pick one of a few routes from unstructured text has two
ways to do it today: a person answers a `Gate`, or an LLM generates the answer
through the `ai_inbound` strategy. Neither returns *how sure* the answer is, so
the workflow cannot say "take the model's answer when it is clear, ask a person
when it is not".

A dedicated decision model returns a candidate **and** a distribution over the
options. The measured capability matrix
(`contributor/reference/jev-system-one-capability-matrix.md`, merged at
`4cd37f7`) establishes what one such provider really does at the wire. What does
not exist is the seam that carries that answer into the framework without
letting the provider become the authority.

### 1.1 Facts this specification rests on (measured, not re-measured here)

From the capability matrix, rows as named there:

| fact | row |
|---|---|
| request envelope is `{"model", "state", "questions"}`; a `choice` question is `{type, instructions, criteria}` with `criteria` an **object** option → meaning | A1, A4, E6 |
| a `choice` answer is exactly `{type, choice, confidence, probabilities}` | A4 |
| a `noul` answer is `{type, noul}` — **no boolean, no `confidence`, no `probabilities`** | A3, G1, G2 |
| `score` is Σ index × probability over the `legend` | B1 |
| `confidence` is **not** `max(probabilities)` (0.01 – 0.26 apart) | B2 |
| `probabilities` key order is unstable and not the request's | B3 |
| identical requests vary; a near-tied decision flipped argmax 9/20 | C1, C2 |
| one `usage` block per request | A2, D1 |
| refusals come in five status layers and three body shapes, one of them plain text | E, E16, E17 |
| the stdlib default `User-Agent` is refused with `403 error code: 1010`, and omitting the header is not neutral | E12 – E14 |
| the free model `jev-1.13-free` answers; the paid `jev-1.13` returns `402` | E10, F2, F3 |
| the free tier answers a burst with `429` and a `Retry-After` of hours | F4, Q2 |
| the catalog's model count is time-variable — observed 81, 82 and 43 | F1 (and brief) |

Retrieved in this checkout (commands in `research.md`):

- No `DecisionResult`, `DecisionProvider`, `ChoiceDecision` or
  `DecisionGateResolver` symbol exists in `src/`, `plugins/` or `tests/` — one
  hit, the prose line `tests/jev_probe/__init__.py:6` saying no adapter exists.
- No `src/` or `plugins/` file mentions `jev` (0 hits, case-insensitive).
- `Gate(strategy=...)` accepts a **closed set** of four names
  (`src/functualize/_types/workflow.py:276`), and
  `tests/gate/test_provider_tables.py:251` pins `STRATEGY_PROVIDERS`'s keys to
  that set.
- On branch `feat/gate-resolution-model` at `d5747f85` (pull request #68, open),
  the walked gate path calls `registry.evaluate(node.awaits, gate_strategy=…,
  gate_name=…)` with **no `workflow_context`**
  (`src/functualize/_engine/gate_service.py:104-106`), so every strategy run by a
  walk sees an empty context. A strategy there cannot read the text it is
  supposed to decide about.

## 2. Users

- **Workflow author** — declares a gate whose answer a decision provider may
  propose, and the rule under which that proposal is accepted.
- **Operator** — reads why a gate blocked, and answers it when the provider's
  proposal was not accepted.
- **Plugin author** — implements another decision provider against the same
  protocol without touching core.

## 3. User stories

- **US-1.** As a workflow author, I declare that a gate's route may be proposed
  by a decision provider, which step's result is the text to decide about, what
  each option means, and the minimum probability and margin the workflow will
  accept — all in the workflow declaration, not in the provider.
- **US-2.** As an operator, when the provider's proposal is not clear enough, the
  walk stops at the gate as it does today, and the blocked reason tells me what
  the provider proposed, how likely it said it was, and what the workflow
  required.
- **US-3.** As an operator, when the provider is unreachable, rate-limited,
  refuses the credential or is out of funds, the walk stops at the gate and says
  which of those happened — it never crashes the run and never waits for hours.
- **US-4.** As a plugin author, I can implement `DecisionProvider` for a
  different backend and get the same gate behaviour.
- **US-5.** As anyone installing functualize without the Jev plugin, nothing
  changes: no Jev code is imported, no credential is read, and the core package
  gains no dependency.

## 4. Behaviour

### 4.1 The provider-neutral result (provider half)

- **B-1.** A decision is returned as a `DecisionResult` carrying: the proposed
  value; the distribution over options when the provider reports one; the
  provider's own `confidence` scalar when it reports one; the provider's name and
  the model that answered; and provenance — the model requested, latency, and
  token usage when reported.
- **B-2.** `distribution` and `confidence` are each *absent* rather than invented
  when a provider does not report them. Nothing in the seam derives one from the
  other (B2), and nothing fabricates a boolean (G2).
- **B-3.** A distribution is keyed by option. Its iteration order carries no
  meaning, and no consumer reads it positionally (B3).
- **B-4.** A provider that cannot produce a decision raises a single error type,
  whose *kind* is one of: not configured, rate limited, refused, unreachable,
  malformed response. A rate-limited error carries the `Retry-After` the service
  sent, if any. The error text never contains the credential.
- **B-5.** The provider neither retries nor sleeps. A refusal for load is a
  normal, bounded outcome returned to the caller at once (F4).

### 4.2 The Jev adapter (provider half)

- **B-6.** Maps one `choice` request to the wire request of row A1/A4: the
  caller's options become `criteria` as an object, under one question id.
- **B-7.** Always sends an explicit, non-default `User-Agent` (E12 – E14).
- **B-8.** Reads `choice`, `probabilities`, `confidence`, the echoed `model` and
  `usage` from a `200`; rejects an answer whose `type` is not `choice`, or whose
  `choice` is not one of the requested options, as *malformed*.
- **B-9.** Maps `429` to *rate limited*; `400`, `401`, `402`, `403` and `422` to
  *refused*, carrying the status and a clipped body; a transport failure or
  timeout to *unreachable*; a non-JSON or shape-violating `200` to *malformed*.
- **B-10.** Reads the credential from `OPENCODE_API_KEY` only. With it unset the
  adapter still constructs; each decision fails as *not configured*.
- **B-11.** Defaults to the free model `jev-1.13-free`; the model is
  configuration, not code. The adapter never reads the catalog and never
  depends on a model count.
- **B-12.** Phase 1 maps `choice` only. `noul` and `score` are not mapped
  (§6), and the result type does not need them to be (B-2 is what keeps it
  able to carry `noul` later).

### 4.3 One `choice` decision through a Gate (Gate half — depends on #68)

- **B-13.** A workflow declares a decision on the gate: the `awaits` field it
  fills, the instructions, each option's meaning, the step whose recorded result
  is the text to decide about, the minimum probability to accept, and the
  minimum margin over the runner-up.
- **B-14.** The declaration is checked when the workflow is declared: the field
  exists on `awaits`, its allowed values are exactly the declared options, and
  the thresholds are in range. A mismatch is a `ValueError` at import time, like
  every other `Gate` check.
- **B-15.** A gate with a decision is walked with the ladder
  `decision → prompt → resolve`, the same shape `ai_inbound` has today.
- **B-16.** The `decision` rung is **accepted** only when the proposed option's
  probability is at least the declared minimum **and** exceeds every other
  option's probability by at least the declared margin. The provider's
  `confidence` is recorded and never consulted.
- **B-17.** Otherwise the rung **fails** with a detail naming the provider,
  model, proposed option, its probability and margin, and the workflow's
  thresholds; the ladder continues exactly as for any failed rung, and a walk
  with no accepted rung **blocks**, carrying that detail in `blocked_reason`.
- **B-18.** A provider error (B-4) fails the rung with its kind in the detail;
  it never escapes the walk.
- **B-19.** An accepted decision is recorded as that request's accepted
  candidate, like any rung (ADR-029). On resume the recorded answer is replayed;
  **the provider is not called again**.
- **B-20.** After a block, a person answers the gate through the existing answer
  surfaces and the walk continues down the branch they chose.
- **B-21.** The Jev plugin registers the `decision` strategy at boot. Without the
  plugin, a decision gate's first rung is `unavailable` with an install hint, and
  the walk falls through to `prompt`/`resolve` as today.

## 5. Acceptance criteria

Each is an observable behaviour; `tasks.md` binds each to its gate.

- **AC-1** (B-1, B-2). A `DecisionResult` built from a `choice`-shaped answer
  exposes value, distribution, confidence, provider, model and provenance; one
  built with neither distribution nor confidence is valid and reports both
  absent.
- **AC-2** (B-3). Two answers with the same probabilities in different key
  orders produce equal `DecisionResult`s.
- **AC-3** (B-6, B-7). The adapter's request body for options
  `{billing, returns, shipping}` equals row A4's shape, and the request carries a
  `User-Agent` that is neither empty nor `Python-urllib/*`.
- **AC-4** (B-8). A `200` carrying a `noul` answer, a `choice` not among the
  options, or a missing `probabilities` raises *malformed*.
- **AC-5** (B-9). Each status in row E — `400`, `401`, `402`, `403` (plain text
  body), `422`, `429` — maps to the kind B-9 names; `429` carries the
  `Retry-After` value; no case sleeps.
- **AC-6** (B-4, B-10). With `OPENCODE_API_KEY` unset a decision fails as *not
  configured*; with it set to a sentinel, no error text or `repr` contains the
  sentinel.
- **AC-7** (B-11). No `src/` or `plugins/` file names a catalog URL or a model
  count; the default model string appears once, as a default.
- **AC-8** (B-14). Declaring a decision whose options differ from the field's
  allowed values, whose field is absent, or whose thresholds are out of range
  raises `ValueError` at declaration.
- **AC-9** (B-16). Through a walked workflow: a proposal at 0.80 with margin 0.40
  against a declared 0.70 / 0.10 continues down that option's branch.
- **AC-10** (B-16, B-17). The same walk with 0.54 / 0.08 blocks at the gate;
  `blocked_reason` names the option, 0.54, 0.08, 0.70 and 0.10.
- **AC-11** (B-16). A proposal with probability below threshold and `confidence`
  1.0 blocks; one above threshold with `confidence` 0.0 continues.
- **AC-12** (B-18, B-5). A provider raising *rate limited* blocks the walk with
  the kind in `blocked_reason`, in under one second of wall clock.
- **AC-13** (B-19). Resuming a walk whose decision was accepted does not call the
  provider (call count stays 1).
- **AC-14** (B-20). After AC-10's block, answering the gate through the public
  answer path resumes the walk down the answered branch.
- **AC-15** (B-21, US-5). With the Jev plugin not loaded, a decision gate's
  first recorded rung is `unavailable` and the walk falls through; `import
  functualize` imports no `functualize_decision_jev` module.
- **AC-16** (standing guard). No new authority primitive: the diff adds no new
  workflow node type, no new walk outcome, no new `EvaluationOutcome` member and
  no new request status.

## 6. Out of scope

- `noul` and `score` mapping; batching several questions in one request (D2).
- Recording the full distribution and provenance as structured evidence on the
  gate record beyond the rung's detail text — Phase 2 (FUN-6) owns "the run
  records … provider/model, candidate distribution, threshold/policy revision".
- Any second workflow, any catalog walk, any model-gateway abstraction, any
  provider selection among several installed decision providers.
- Calibration, benchmarking or threshold tuning — Phase 3.
- A stable-API promise for the new names. They are public (member decision,
  2026-09-28) and **provisional**, per the design review's decision D2 ("What
  1.0 promises": everything outside the stable list is provisional).
- Refusing an effecting step downstream of a decision gate — pending Q-1; see
  `plan.md` → *Decisions*. Phase 1's reference workflow has no effecting step.
- Deadlines on a decision gate that blocks for a person. The design review's
  decision D1 (a deadline on the gate, checked when the run is touched) applies
  to every gate alike and lands with FUN-21, not here.

## 7. Standing constraints (from the track, restated as testable lines)

- Jev returns a candidate and an uncertainty; the gate and the workflow's
  declared thresholds decide (B-16, AC-11).
- No rename of `Gate` around Jev: the new strategy is named `decision`, and no
  core module names Jev except the install hint in `_gate/_strategy.py`'s
  provider table — a diagnostic string, as it already is for `functualize-ai`.
- No mandatory Jev dependency: the adapter is its own workspace package,
  `functualize-decision-jev` (AC-15), and it reaches core through the public
  API only.
- No "hermetic" claim. The design review (G-Q19) found bit-for-bit hermeticity
  impossible for hosted models; the property this work can support is
  functional reproducibility, which needs the model identity and inputs
  recorded — B-1's provenance is the first slice of that.
- No "zero hallucinations" claim anywhere in code, docs or messages.
- No confidence-only authorization: the acceptance rule does not read
  `confidence` (AC-11).
