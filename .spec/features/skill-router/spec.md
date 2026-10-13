# skill-router — specification

Phase 4 of the decision-layer experiment: **before an agent's context is
assembled, a bounded decision provider picks one functualize skill (or
`none`) out of the four shipped skills, a gate decides whether to take it, and
only the chosen definition is loaded.** The phase measures routing quality and
context economics on a frozen corpus, and downstream task success on a small
fixed task subset. It compares three arms: load everything, native routing, and
the pre-context router. It ends in a computed verdict that the maintainer then
rules on.

**Status: drafted 2026-10-13, awaiting the maintainer's confirmation.**
Shape intent: [SD/16515075](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/16515075)
v3, `Authority: Approved`, last reviewed 2026-10-13, read live on 2026-10-13
from the issue's `Shape intent` property (authored against v2; v3 records the
decisions below and changes no scope).
D0–D3 were decided by the owner. D4–D6 were accepted as recommended in the
MCH-180 thread on 2026-10-13T06:42:18Z. That same comment **waived the owner's
corpus-label review** ("I dont need to review the corpus"), so B-3 has no human
approval step between drafting and freezing the corpus. It has a reviewer check
instead.

**User-visible surface: none** (shape D0). This change adds a contributor
instrument under `tests/skill_router_eval/`, one downstream suite and one
harness option under `evals/`, and one `contributor/reference/` page. It
changes no `skills/**`, `src/functualize/**`, `plugins/**`, `examples/` or
`docs/` file (AC-15 checks this mechanically). Measured numbers are never
committed (B-27).

## 1. Problem

The opportunity's second proof (SD/5079042) is a **Skill Router**: given a
request plus a compact catalog of skills, select `none` or a skill with
confidence, load only that definition, and compare context size, routing
correctness, latency, cost and downstream task success against "load
everything" and generative routing. The scope guard is **a bounded catalog**.

Phase 3 measured the same seam on a four-route question. Jev's routed accuracy
was 0.665, against 0.650 for a regex table and 0.895 for the frontier model;
the verdict was *continue research* (SD/13959170). Phase 4 asks whether a
five-option question over deliberately disjoint descriptions is easier for
Jev (shape H2). It also asks whether choosing before the agent starts saves
context without costing downstream success (shape H1).

### 1.1 Facts this specification rests on (measured on `sdd/skill-router`, base `36eaeabf`, 2026-10-11/13)

| # | fact | how it was measured |
|---|---|---|
| F-1 | `skills/` ships **4** skills: `functualize`, `functualize-app`, `functualize-cli`, `functualize-skill`. All of them together are 13 files and 110 855 bytes; the four `SKILL.md` files are 46 596 bytes. | `find skills -name SKILL.md \| wc -l`; `find skills/<name> -type f` (research.md F1) |
| F-2 | Description lengths: `functualize` 651, `functualize-app` 598, `functualize-cli` 743, `functualize-skill` 502 characters (folded YAML, whitespace-collapsed). | frontmatter parse, 2026-10-13 |
| F-3 | `evals/suites/triggering.yaml` holds **21** labelled single-skill cases: `functualize` 7, `functualize-cli` 6, `functualize-app` 3, `functualize-skill` 2, `none` 3. | `grep -E '^\s+expect:'` (research.md F2) |
| F-4 | The seam proposes one option: `DecisionProvider.choose(ChoiceRequest) -> DecisionResult[str]`, with 2–32 options. | `src/functualize/_types/decision.py:54,111-118,143`; ADR-030 §1 |
| F-5 | `ChoiceDecision(fallback=None)` is legal. A proposal below the thresholds then **blocks the gate for a person**: the run returns `RunStatus.BLOCKED`, the decision rung's evidence is recorded with a verdict such as `below_threshold`, and nothing is accepted. | `src/functualize/_types/decision.py:158-186`; `tests/integration/test_decision_fallback_e2e.py:179-199` |
| F-6 | `decision_record(store, scope, gate)` reads `decided_by` ∈ `decision`/`fallback`/`person`/`None` plus the decision evidence. It is public as `functualize.app.utils.decision_record`. `RunStatus` is public from `functualize.types`. | `src/functualize/app/_decision_record.py:37-80`; `src/functualize/app/utils.py:123,223`; `src/functualize/types/__init__.py:28,73` |
| F-7 | These Phase 3 parts take any `ChoiceRequest` and contain no route literal: `comparators.identity_sha256`, `hermetic()`, `hermetic_identity()`, `FrontierRouter` (schema and prompt built from `request.options`), `corpus.corpus_sha256`, `corpus.ordered_cells`, and `metrics.accepts`, `agreement`, `variance`, `latency`, `cost`. Route-coupled parts: `corpus.ROUTES`/`check_v1_shape`, `comparators.RULES`/`DeterministicBaseline`, `metrics` confusion/escalation/errors/boundary/verdict and `_brier` (sums over `ROUTES`), `replay` (loads the Phase 2 router by path), and `report`. | `rg -n 'ROUTES\|human_review' tests/hermetic_eval/{metrics,comparators}.py`; function bodies read |
| F-8 | Native routing is already a provider: `evals/providers/claude_router.py::call_api(prompt, options, context)` mounts all skills, runs `claude -p` (pinned `claude-sonnet-5`, tools `Skill Read Glob Grep`, ≤3 turns) and returns `selected` (first `functualize*` skill loaded, else `None`) and `cost`. | file read |
| F-9 | The downstream harness mounts **all skills or none** (`build_workspace(fixture, with_skills, …)` copies `SKILLS_DIR` whole). `AgentRun` records `num_turns`, `cost_usd` and `skills_loaded`, but **no token usage**: `_absorb` reads no `usage` block. | `evals/providers/_harness.py:567-631,788-845` |
| F-10 | `claude` 2.1.281 on this host offers `--append-system-prompt <prompt>`. Whether its stream-json `assistant` events carry a per-message `usage` block (input, cache-creation and cache-read tokens) is **not yet measured**. T5 step 0 measures it. | `claude --help`, `claude --version` |
| F-11 | The five downstream candidates chosen for D3 are graded only by deterministic asserts (no `llm-rubric`), and their task prompts are 138–291 characters long (§4.6). | `awk` over the three suites; `yaml.safe_load` lengths |
| F-12 | `functualize-cli` has **no** downstream suite: `evals/suites/` holds `functualize`, `functualize-app`, `functualize-skill` and `triggering` only. | `ls evals/suites` |
| F-13 | `tests/evals/test_suite_contracts.py` parametrises over `evals/suites/*.yaml`, so a new suite is checked for the var-expansion and worker-timeout rules automatically. | file read (`SUITES = sorted(EVALS.glob("suites/*.yaml"))`) |
| F-14 | Whether Jev accepts a request whose five option meanings total about 2.5 kB is **not yet measured**. The longest state the capability matrix records is +288 characters. | `contributor/reference/jev-system-one-capability-matrix.md:217` |

## 2. Users

- **Maintainer**: rules on the verdict and on publication, and needs one table
  per question (routing, context, downstream) that a command can re-derive.
- **Evaluator** (the implementer): runs the corpus and the downstream subset
  within the time box and rate-limited budgets.
- **Reviewer**: checks that no number was hand-edited, the corpus and catalog
  were frozen before the first measurement, and the labels follow the rubric.

## 3. User stories

- **US-1.** As the evaluator, I freeze a corpus and the catalog it was written
  against before any comparator sees either. A later edit to a scenario or to
  any shipped skill forces a new corpus version.
- **US-2.** As the evaluator, I replay the corpus through one selection gate for
  a hermetic, a frontier and a deterministic comparator, and through the native
  router for accuracy alone.
- **US-3.** As the maintainer, I read how much context each arm puts in front of
  the agent before its first turn, with native routing as the headline baseline.
- **US-4.** As the maintainer, I read whether the router arm completes the
  downstream tasks as often as the native arm, with an interval and not just a
  point estimate.
- **US-5.** As a reviewer, I regenerate every report file from the ledgers and
  get the same bytes.

## 4. Behaviour

### 4.1 The catalog: bounded, derived, frozen

- **B-1.** The catalog is the four shipped skills plus `none`, in this order:
  `functualize`, `functualize-app`, `functualize-cli`, `functualize-skill`,
  `none`. It is **read** from `skills/*/SKILL.md` and never written. Each entry
  carries `name`, `description` (the frontmatter description,
  whitespace-collapsed) and `sha256`, a digest over the skill directory's files:
  sorted relative paths with their bytes. `none` has the fixed meaning *"No
  functualize skill applies; answer without loading one."* The catalog digest is
  the SHA-256 of the canonical catalog JSON.
- **B-2.** **Bounded by construction.** The instrument refuses (exit 2) a
  catalog with other than exactly the four names above. A fifth skill directory,
  a missing one, or a renamed one stops the run. A different catalog is a new
  corpus version, not a wider router.

### 4.2 The corpus: versioned, frozen before the first measurement

- **B-3.** Corpus `v1` is `tests/skill_router_eval/corpus/v1/scenarios.jsonl`:
  **40 scenarios, 8 per option, and within each option 5 `clear` and 3
  `borderline`.** Keys are `id` (`k01`…`k40`), `state` (1–600 characters),
  `expected` (an option), `stratum`, `rationale` (one sentence citing a
  `LABELING.md` clause) and `origin` (`triggering:<n>` for the 21 seeded cases,
  where `<n>` is the 1-based case index in `triggering.yaml`, else `new`). The
  21 `triggering.yaml` cases keep their own `expect` as the label. The remaining
  19 are new, drafted against the rubric `corpus/v1/LABELING.md`. Its five
  clauses are the five option meanings of B-1, plus tie-breaks: tool
  installation, PATH, config directories and shell completion ⇒
  `functualize-cli`; writing or debugging jobs ⇒ `functualize`; building a whole
  program ⇒ `functualize-app`; authoring an agent skill ⇒ `functualize-skill`;
  a request functualize does not bear on ⇒ `none`. No model labels the corpus,
  and no comparator output is consulted while drafting. **No scenario's `state`
  equals a downstream task prompt (§4.6).** The owner waived label review
  (2026-10-13); a reviewer checks every rationale against the rubric instead
  (T7).
- **B-4.** **Freeze.** `corpus/v1/corpus.lock.json` pins the scenarios'
  SHA-256, the counts of B-3, seed `20261013`, repeats `5`, a 72-hour time box,
  the catalog JSON and its digest, each comparator's identity digest, the
  verdict constants (B-24) and `frozen_at`. It is committed before the first
  live cell.
- **B-5.** **No tuning after the first measurement.** The replay refuses to
  start or resume (exit 2, nothing written) when the lock is missing, or when
  the scenario digest, **the catalog digest re-derived from `skills/`**, or a
  comparator's identity digest differs from the lock. A `SKILL.md` edit after
  the freeze therefore voids the corpus (shape Risk 2).

### 4.3 The selection: one request, one gate, no fallback

- **B-6.** The selection is a workflow defined in the instrument (not in
  `examples/`, shape D0): `intake → Gate("select", decide=SELECT) →` one stub
  step per option `→ END`. `SELECT = ChoiceDecision(field="skill",
  instructions=<C-3>, options=<the five catalog meanings>, state=FromStep("intake"),
  accept_at=0.70, min_margin=0.10, fallback=None)`. The decision seam is
  unchanged, and one `ChoiceRequest` carries five options (shape D1).
- **B-7.** **Three outcomes per cell.** *Accepted skill*: the gate took a skill.
  *Accepted `none`*: the gate took `none`. *Escalated*: the gate blocked
  (`decided_by is None`, run `BLOCKED`), because the proposal was below the
  thresholds, the provider failed, or there was no distribution. There is no
  fallback option (shape D4). Downstream, an escalated selection runs the
  **native** arm, so a refused proposal costs exactly the baseline and never
  loads a wrong skill.
- **B-8.** **Comparators**, each a `DecisionProvider` registered as the
  `decision` strategy, each seeing the same `ChoiceRequest` and nothing else
  (no `id`, `expected`, `stratum`, `rationale`, `origin`):
  - **hermetic**: Phase 3's `hermetic()` (Jev, `jev-1.13-free`), unchanged.
  - **frontier**: Phase 3's `FrontierRouter` (`codex exec`, `gpt-6-astra`,
    effort `medium`), unchanged. Its schema and prompt are built from the five
    options.
  - **deterministic**: a keyword table over `state`, written from the five
    meanings only and **committed before the corpus is drafted**. The first
    match proposes its skill one-hot. No match proposes `none` with a uniform
    `0.20` distribution, which the margin rule refuses, so the cell escalates.
  - **native** (accuracy only, shape D6): `claude_router.call_api` from
    `evals/providers/`, loaded by path. It is **not** a `DecisionProvider` and
    not judged by the gate. Its cell records `selected` (or `none` when no
    `functualize*` skill fired), cost and wall-clock latency, with no
    distribution.
- **B-9.** **A provider failure is data.** Phase 3's rules carry over: a rate
  limit, refusal, malformed answer or timeout is recorded, never retried and
  never dropped. A rate-limited cell is recorded and the invocation exits 0 with
  the reopen time, never sleeping. A frontier model mismatch is `invalid_model`
  (exit 3). Cells not attempted when the time box closes are `not_attempted`.

### 4.4 The replay: repeated, ordered, chunked, resumable, time-boxed

- **B-10.** One comparator over the corpus is `40 × 5 = 200` cells. Repeats are
  outermost, and repeat `r` runs in `random.Random(20261013 + r)` order (Phase
  3's `ordered_cells`). An invocation runs until `--budget-seconds` (default
  360) and then exits 0 naming the next cell. Re-invoking with the same run
  directory resumes. The ledger is append-only and flushed per cell.
- **B-11.** Each gated cell boots a fresh `FunctualizeApp` in a scratch project
  inside the run directory, with scope `<comparator>-r<repeat>-<id>`. The run
  directory defaults to `$XDG_STATE_HOME/functualize-skill-router-eval/<run id>/`,
  **outside the repository**. Outcome, proposal, distribution, probability,
  margin, verdict, failure and latency come from `decision_record(...)`. The
  harness adds only the label, stratum, repeat and, for the frontier, the CLI
  block.

### 4.5 The measurement protocol (routing and context)

Computed by `tests/skill_router_eval/metrics.py` from the ledgers, per
comparator, overall and per stratum.

- **B-12. Selection accuracy.** `selected` is the accepted option, or
  `escalated`. **Routed accuracy** is the share of cells with `selected ==
  expected`, over every cell, so escalated and failed cells count as wrong
  (Phase 3's convention). Also reported: a 5×6 confusion matrix (columns are the
  five options plus `escalated`); the proposed confusion (with a `failed`
  column); per-option precision and recall; and macro-F1. For **native**:
  accuracy, confusion and macro-F1 only.
- **B-13. The four selection errors**, counted separately at every sweep point:
  - **wrong skill**: a skill accepted, but a different one expected;
  - **unsafe none**: `none` accepted while a skill was expected (shape Risk 1,
    **blocking** in the verdict);
  - **over-load**: a skill accepted while `none` was expected;
  - **false escalation**: escalated while the proposal equalled `expected`
    (benign: it costs the native baseline).
- **B-14. Coverage and selective accuracy.** Coverage is the share of cells
  accepted (a skill or `none`). Selective accuracy is the accuracy of the
  accepted cells.
- **B-15. Calibration.** As Phase 3 (ten bins, ECE), with the Brier score over
  the **five** options. The provider's `confidence` is reported separately and
  never used as an input.
- **B-16. Variance, agreement, latency, cost.** These reuse Phase 3's generic
  functions (F-7) unchanged: modal agreement and flips per scenario (the
  deterministic comparator must show zero flips); Cohen's κ between every pair
  of comparators, native included; latency p50/p95/max; and cost. Cost is `$0`
  for deterministic, `$0` for hermetic on the free tier (tokens reported),
  tokens only for frontier (*subscription, unpriced*), and `cost_usd` as
  reported by `claude` for native.
- **B-17. Threshold sweep and conformance.** Recomputed offline over Phase 3's
  grid (`accept_at` 0.50…0.95 × `min_margin` 0.00…0.20) using
  `metrics.accepts`, with a failed cell treated as escalated. **Conformance**:
  at the declared point (0.70, 0.10), the offline rule must reproduce every
  gated cell's recorded outcome, or the report exits 4.
- **B-18. Static context economics (E3, corpus half).** For every gated cell
  and arm, the bytes in context **before the first task turn**:
  - **native**: the catalog listing, i.e. the four descriptions;
  - **load everything**: the four descriptions plus all 13 skill files;
  - **router**: the accepted skill's `SKILL.md` plus its description, `0` for
    an accepted `none`, or the native listing for an escalated cell.
  All of these are computed from the frozen catalog (B-1). Reported per
  comparator as a mean per cell and as a ratio to native. The **headline is the
  ratio to native** (shape D2). "Load everything" is shown beside it and never
  as the headline.

### 4.6 The downstream subset (E3 tokens and E4 success)

- **B-19. Tasks, fixed here for the maintainer's approval** (shape D3). Five
  cases are copied verbatim (prompt, fixture, setup, checks, asserts) from the
  existing suites. Each is graded by deterministic asserts only (F-11):

  | id | source suite → case `description` | expected skill |
  |---|---|---|
  | `d1` | `functualize.yaml` → "uses Secret for a credential instead of a plain string" | `functualize` |
  | `d2` | `functualize.yaml` → "diagnoses a silently undiscovered job via the CLI, not by guessing" | `functualize` |
  | `d3` | `functualize-app.yaml` → "reaches for JobConfig rather than a pile of flags" | `functualize-app` |
  | `d4` | `functualize-app.yaml` → "standalone — one file with a PEP 723 header, not a scaffolded project" | `functualize-app` |
  | `d5` | `functualize-skill.yaml` → "authors a skill whose script runs and whose frontmatter is legal" | `functualize-skill` |

  `functualize-cli` and `none` have no downstream task: no suite exists for the
  first (F-12), and a `none` task has nothing for a skill to improve. The
  finding states this gap.
- **B-20. Three arms** in one suite, `evals/suites/skill-router.yaml`, each a
  `claude_agent.py` provider with config `arm`. The model is pinned to
  `claude-sonnet-5`, the sandbox is `docker`, and promptfoo runs with
  `--repeat 3`. That gives 5 × 3 × 3 = **45 agent runs**.
  - **`load-everything`**: all skills mounted, and all four `SKILL.md` bodies
    appended to the system prompt.
  - **`native`**: all skills mounted and nothing appended, which is today's
    behaviour (`with_skills: true`).
  - **`router`**: the selection for the case is read from the file named by
    `FZ_SKILL_ROUTER_SELECTIONS`. An accepted skill means only that skill is
    mounted and its `SKILL.md` is appended. An accepted `none` means nothing is
    mounted or appended. An escalated selection means the native configuration.
    A case **missing** from the file is a provider error, never a silent native
    run.
- **B-21. The selection for the router arm** is made **once per task** by the
  `select` command (C-7). It runs the task prompt through the B-6 workflow with
  the **hermetic** comparator and writes `selections.json`, carrying each
  case's outcome and its gate evidence, outside the repository. All three
  repeats of a task use that one selection. Selection variance is measured on
  the corpus (B-16), not here. The router arm's latency and cost are the
  selection's recorded latency plus the agent run.
- **B-22. What each run records.** Pass/fail per the case's asserts,
  `cost_usd`, `num_turns`, wall-clock duration, `skills_loaded`, and
  **`first_turn_input_tokens`**: the first `assistant` event's `usage`,
  `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. If T5
  step 0 shows that the stream carries no per-message usage, the field is
  `null`, the finding says so as a deviation, and E3 rests on B-18's bytes
  alone.
- **B-23. Downstream metrics.** Per arm: success rate over 15 runs with a 95 %
  Wilson interval; the router-minus-native difference; mean and p95 of
  `first_turn_input_tokens`; mean cost; mean turns; and mean duration. The
  promptfoo results JSON is the ledger. The report reads it (`--downstream
  <results.json>`) and never re-runs anything.

### 4.7 The verdict

- **B-24.** Constants are fixed in the lock before the first cell: `min_lead =
  0.05` and `max_unsafe_none = 0`. The verdict is computed **by rule** from the
  hermetic comparator at the declared point:
  - **negative result**: hermetic routed accuracy < deterministic routed
    accuracy + `min_lead`. This is the shape's "wrong if Jev is no better than
    the keyword table" (E2). Nothing is promoted, and the parent's disposition
    stage receives the result.
  - **promote to Phase 5**: E2 holds, the hermetic unsafe-`none` count is ≤
    `max_unsafe_none`, the router context is below native on the corpus (B-18;
    E3), and router downstream success ≥ native downstream success (B-23; E4,
    point estimates, intervals printed beside them).
  - **continue research**: otherwise, naming every condition that failed.
  The verdict is a recommendation; the disposition is the maintainer's.

### 4.8 The evidence artifact

- **B-25.** `uv run python -m tests.skill_router_eval.report --run-dir <hermetic>
  --run-dir <frontier> --run-dir <deterministic> --run-dir <native>
  --downstream <results.json> --selections <selections.json> --out <dir>`
  writes `benchmark.md`, `finding.md`, `metrics.json` and `verdict.json`. Every
  file carries the corpus version and SHA-256, the catalog digest, each
  identity digest, each ledger's SHA-256, the selections file's SHA-256, the
  downstream file's SHA-256 and the repository commit. Nothing in them is typed
  by hand.
- **B-26.** Re-running over the same inputs produces byte-identical files.
  `--check <dir>` exits 1 on any difference.
- **B-27.** **Not committed.** Run directories, `selections.json`, promptfoo
  results and report output live outside the repository. They are delivered on
  the tracker, and published as one Confluence page in `SD`, a child of
  `5144577`, titled `Skill Router — Corpus v1 Results` (the evidence row of the
  shape). The page body is `finding.md` and `benchmark.md`, and the inputs and
  outputs are attached. The repository keeps only the method
  (`contributor/reference/skill-router-evaluation.md`), with **no measured
  number**.

### 4.9 The scope guard

- **B-28.** Routing and context economics only: one catalog (the four shipped
  skills plus `none`), one corpus, five downstream tasks. No general benchmark,
  no model gateway, no provider registry, no self-growing catalog.
- **B-29.** No product change: no file under `skills/**`, `src/functualize/**`,
  `plugins/**`, `examples/` or `docs/` changes, and `tests/hermetic_eval/**` is
  unchanged (its frozen lock and published results stay re-derivable). Jev
  stays a candidate behind the existing gate.
- **B-30.** No offline test makes a network call, spawns `claude` or `codex`
  (or any process), or sleeps. The live replay, `select` and the promptfoo
  suite are commands, never collected by pytest.

## 5. Acceptance criteria

Each criterion is decided by the command beside it, run from the repository
root. `tasks.md` binds each to its task.

- **AC-1** (B-1, B-2). `uv run pytest tests/skill_router_eval/test_catalog.py -q`
  passes. It derives the catalog from `skills/` and checks 5 entries in B-1
  order, each skill digest stable across two derivations, and that a scratch
  copy with a fifth skill directory or a missing one raises `CatalogError`.
- **AC-2** (B-3). `uv run pytest tests/skill_router_eval/test_corpus.py -q`
  passes, including the case that loads `corpus/v1/scenarios.jsonl`. It checks
  40 scenarios, 8 per option, 5/3 per stratum, unique ids, the six keys, 21
  `triggering:` origins whose labels equal `triggering.yaml`'s `expect`, and
  that no `state` equals a `skill-router.yaml` task prompt.
- **AC-3** (B-4, B-5). `test_replay.py`: replay exits 2 and writes nothing when
  the lock is absent, when one byte of `scenarios.jsonl` differs, and when the
  catalog derived from a scratch `skills/` with one changed byte differs from
  the lock.
- **AC-4** (B-6, B-7). `test_selection.py`: with a fake provider proposing
  `functualize-cli` at 0.90 the record reads `decided_by == "decision"` and
  outcome `functualize-cli`. At 0.55 the run is `BLOCKED`, `decided_by is None`
  and the outcome is `escalated`. Proposing `none` at 0.90 gives outcome
  `none`. A provider raising `DecisionUnavailableError` gives `escalated`.
- **AC-5** (B-8). `test_replay.py`: a recording fake provider receives
  `ChoiceRequest`s whose `state` equals the scenario's, whose `options` equal the
  catalog's five meanings in B-1 order, and which contain no `id`, `expected`,
  `stratum`, `rationale` or `origin` text.
- **AC-6** (B-8). `test_comparators.py`: the keyword table is deterministic over
  100 calls, one-hot on a match and uniform `0.20` on no match; its identity
  digest equals the lock's. The native adapter, driven through an injected
  `call_api` fake, maps `{"selected": "functualize-app"}` to
  `functualize-app`, `{"selected": None}` to `none`, and `{"error": …}` to a
  failed cell.
- **AC-7** (B-9, B-10). `test_replay.py`: a fake provider raising `rate_limited`
  on cell 2 yields a 2-line ledger, exit 0, a printed reopen time and no
  `time.sleep` call. Resuming continues at cell 3. A run interrupted by
  `--budget-seconds` and resumed equals an uninterrupted run, excluding
  timestamps and latencies.
- **AC-8** (B-12…B-17). `uv run pytest tests/skill_router_eval/test_metrics.py -q`
  passes against hand-computed fixtures for every metric: each of the four
  errors, the five-option Brier score, and a deterministic ledger with zero
  flips.
- **AC-9** (B-17). `test_metrics.py`: at (0.70, 0.10) the offline rule
  reproduces every outcome of a ledger produced through the real selection
  workflow (`test_replay.py` fixture), and a doctored ledger makes the report
  exit 4.
- **AC-10** (B-18). `test_metrics.py`: over a fixture catalog with known byte
  sizes, router bytes for an accepted skill, an accepted `none` and an
  escalated cell equal the hand-computed values, and the ratio to native is
  their mean divided by the listing size.
- **AC-11** (B-20, B-22). `uv run pytest tests/evals -q` passes. The new suite
  satisfies the existing contracts (F-13). A new `tests/evals/test_skill_router_arms.py`
  shows the following, with no process spawned: `build_workspace(…,
  skills=["functualize-app"])` mounts exactly that directory;
  `skills=[]` mounts none; `run_claude(…, append_system_prompt=X)` places `X`
  after `--append-system-prompt` in the argv (fake `Sandbox.popen`); `_absorb`
  sets `first_turn_input_tokens` from the first `assistant` usage and not from
  a later one; the router arm with a missing case returns `{"error": …}`; and
  the five `skill-router.yaml` cases equal their source cases field for field.
- **AC-12** (B-23, B-24). `test_report.py`: four fixture input sets built to land
  on each verdict branch yield `promote to Phase 5`, `negative result`,
  `continue research` (naming the failed conditions) and, with one unsafe
  `none`, `continue research` even when every other condition holds. The Wilson
  interval for 12/15 matches a hand-computed value to 4 decimals.
- **AC-13** (B-25, B-26). `test_report.py`: two runs over the same inputs are
  byte-identical, `--check` exits 0, and exits 1 after one byte of
  `benchmark.md` changes. Every output carries the corpus SHA-256 and the
  catalog digest.
- **AC-14** (B-10, B-11, B-20, live). For each of the four comparators the
  ledger has 200 lines. `selections.json` has 5 entries. The promptfoo results
  hold 45 rows. The report over them exits 0. *(Decided by the evaluator at the
  live tasks; delivered, not committed.)*
- **AC-15** (B-27, B-29, scope). `git diff --name-only origin/master...HEAD --
  skills src plugins examples docs tests/hermetic_eval | wc -l` returns 0, and
  `git ls-files | rg -c 'cells\.jsonl|benchmark\.md|selections\.json'` returns 0.
- **AC-16** (B-30). `rg -l "^(from|import) functualize\._" tests/skill_router_eval | wc -l`
  returns 0, and `rg -l "^import subprocess|^from subprocess"
  tests/skill_router_eval tests/evals/test_skill_router_arms.py | wc -l`
  returns 0.
- **AC-17** (standing). `rg -c functualize_decision_jev src` returns 0, and
  `uv run pytest tests/hermetic_eval -q` passes unchanged.
- **AC-18** (B-27, live). After the publication task, the Confluence page exists
  in `SD` under `5144577`, and its body carries the corpus SHA-256 and the
  catalog digest, read back live with the Atlassian tools.

## 6. Out of scope

- "One or more skills": the selection proposes exactly one option (shape D1,
  Risk 5). If corpus drafting finds a request that genuinely needs two skills,
  it is **listed in the finding**, not labelled. A v2 corpus may encode subsets
  as options.
- A user-visible router (`examples/`), new skill metadata in `SKILL.md`, a
  widened seam: these belong to Phase 5 under its own shape, or nowhere.
- Changing `tests/hermetic_eval/**`, re-running or re-measuring Phase 3.
- A downstream suite for `functualize-cli`, or the full downstream suites (D3).
- Funding the paid zen tier or changing the Jev plugin.

## 7. Standing constraints, restated as testable lines

- **Bounded catalog**: B-1, B-2; AC-1.
- **Routing and context economics, not general intelligence**: B-28; AC-15.
- **No new authority primitive**: B-6 (the unchanged seam and gate, no
  fallback), B-29; AC-15.
- **Jev stays a candidate; never a dependency outside this track**: B-8; AC-17.
- **No confidence-only authorization**: the selection has no effecting step;
  `confidence` is calibrated, never consulted (B-15).
- **Nothing published without the maintainer**: B-27; AC-15. The shape's
  evidence row approves the one Confluence page; nothing else is published.
