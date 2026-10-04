# hermetic-evaluation — specification

Phase 3 of the decision-layer experiment: **one frozen corpus, replayed through
the Phase 2 hermetic router against three comparators**, measured for routing
quality, ending in a boundary statement and a computed adopt / continue /
reject verdict that the maintainer then rules on.

**Status: confirmed by the maintainer, 2026-10-04**, with D-1…D-7 and the
review-flagged smells S-1 and S-4 answered (`plan.md` → *Decisions*). Two
answers changed this file after the first draft: the frontier comparator is
**Codex** (`gpt-6-astra`), not Claude (D-2), and the report is also published
to Confluence in the Functualize space (D-6). The frontier's success-path
output shape is not yet measured (F-14), so the first step of T3 measures it
and pins it; a mismatch with `contracts.md` C-3 is fixed in C-3 before any
code is written.

**User-visible surface: none.** This change adds a contributor instrument under
`tests/` and touches no `src/functualize/**`, no `plugins/**`, no CLI, MCP or
TUI surface, no `docs/` page and no `examples/` directory (AC-14 decides it
mechanically). Under `AGENTS.md` → *Shape intent comes before the spec*, a
change with no user-visible surface does not need a `Shape intent` page; this
issue carries none, and neither did its Phase 2 sibling. **If D-1 is answered
with the `examples/` location instead, that judgment flips** — the instrument
becomes user-visible and the spec stops until a Shape intent page is approved.
The evidence this instrument produces is **not** committed by this change;
with the maintainer's approval (D-6) it is published to Confluence in the
Functualize space, not to the repository (B-25).

## 1. Problem

Phase 2 (merged; `examples/standalone/hermetic_router/`) routes one request
among `deterministic | cheap_model | frontier_agent | human_review`: a
`DecisionProvider` proposes, the gate's declared rule (`accept_at=0.70`,
`min_margin=0.10`, `fallback="human_review"`) decides, and every decision rung
records evidence readable through `functualize.app.utils.decision_record`.

What nobody can say yet is **whether a hermetic (Jev-backed) proposal is good
enough to replace a frontier model's routing decision, and where it is not.**
FUN-6's acceptance asks for exactly that and it is unmet: a replayable corpus
defined before quality is judged; recorded decision accuracy, latency, cost and
run-to-run variance; the boundary where the hermetic decision is trustworthy and
where escalation is still required; and a result that ends in adopt, continue
or reject.

A single pass cannot answer it: the wire varies run to run (F-6), so the
measurement must repeat; and a corpus edited after the numbers are seen measures
the editor, not the router, so the corpus must be frozen first.

### 1.1 Facts this specification rests on (measured on this branch, `e8e3b867`, 2026-10-04)

| # | fact | how it was measured |
|---|---|---|
| F-1 | The router can be replayed many times in one process: a fresh `FunctualizeApp` per run, `build_router(app, text)`, `register_gate_strategy("decision", DecisionGateResolver(provider))`, `app.execute(RunRequest(job_name="router", surface="app.execute", workflow_scope_id=…))`, then `decision_record(ScopeStore(app.substrate), scope, "route")`. 30 runs took **7.54 s** (≈0.25 s each) with no `AppState.reset()`, and every record carried the expected route, `decided_by` and verdict. | scratch probe outside the repo against the worktree's `.venv`, cwd a scratch project holding `.functualize/` |
| F-2 | The one seam all comparators can share already exists and is public: `DecisionProvider.choose(ChoiceRequest) -> DecisionResult[str]`, exported with `DecisionGateResolver`, `DecisionResult`, `DecisionProvenance`, `DecisionUnavailableError`, `DecisionFailure` from `functualize.plugin`. | `src/functualize/_types/decision.py`; imports in `examples/standalone/hermetic_router/tests/test_router.py:31-38` |
| F-3 | A decision rung's evidence (schema `decision-evidence/1`) carries 17 keys: `schema field state rule provider model requested_model proposal distribution confidence probability margin verdict failure latency_seconds input_tokens output_tokens`; `failure` carries `kind status retry_after`. | `src/functualize/_gate/decision_evidence.py:30,64-105`; `test_router.py:53-71` |
| F-4 | The acceptance rule is `p >= accept_at and margin >= min_margin`, `margin = p − max(other probabilities)`, compared exactly (no rounding). | `src/functualize/_gate/decision_strategy.py:140-150`; `.spec/STATUS.md` *Margin comparison is still exact* |
| F-5 | Free-tier Jev budget: about a hundred requests per burst, then `429 FreeUsageLimitError` with `Retry-After` counting down to a reset about five hours out; the ceiling itself is unmeasured. | `contributor/reference/jev-system-one-capability-matrix.md` → Row F (F4) and Q2 |
| F-6 | Identical Jev requests vary: a near-tied decision flipped argmax 9 times in 20; a clear one did not. | capability matrix Row C (C1–C2) |
| F-7 | The paid zen tier is unfunded: `jev-1.13`, `claude-sonnet-5` and `gpt-5.5` on `https://opencode.ai/zen/v1/chat/completions` each answered **HTTP 402** `Insufficient account funds` (2026-10-04T09:16Z). No `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` is set on this host. | three one-shot `curl` calls; `env` |
| F-8 | `claude` 2.1.281 on this host answered one router question headless — `claude -p … --model claude-sonnet-5 --output-format json --json-schema <4-option schema> --tools "" --system-prompt … --setting-sources "" --strict-mcp-config --disable-slash-commands --no-session-persistence --max-turns 2` — with `structured_output = {"choice": "human_review", "probabilities": {…4 keys…}}`, `total_cost_usd 0.00884` (`costBasis: list`), `modelUsage` keyed `claude-sonnet-5`, `duration_ms 5828`. Kept as the measured alternative; D-2 chose Codex instead. | one call, 2026-10-04T09:21Z, cwd an empty scratch directory |
| F-9 | The repo already drives `claude -p` as an evaluation provider (`evals/providers/_harness.py::run_claude`, `claude_router.py`, `claude_grader.py` defaulting to `claude-sonnet-5`) and keeps live-model work out of pytest (`evals/README.md`: "deliberately not pytest"). | files read |
| F-10 | The instrument precedent: `tests/jev_probe/` is "an instrument, not a feature" — module-level credential gates, numbers transcribed into a `contributor/reference/` document, nothing read by the product. | `tests/jev_probe/__init__.py` |
| F-11 | `tests/hermetic_eval/` does not exist; `src/` imports `functualize_decision_jev` in 0 files; `examples/standalone/hermetic_router/router.py` imports no model client (0 matches for `functualize_ai\|openai\|anthropic\|httpx\|urllib\|subprocess\|functualize_decision_jev`). | `test -e`, `rg -c` |
| F-12 | CI installs the Jev plugin for the root suite: `uv sync --all-extras` and the `all` extra lists `functualize-decision-jev`. | `.github/workflows/ci.yml:110-181`; `pyproject.toml:110-122` |
| F-14 | `codex` 0.156.1 on this host is logged in through a ChatGPT subscription (`auth_mode: chatgpt`); its model cache lists `gpt-6-astra` as "Frontier intelligence for the most demanding work". `codex exec` offers `--json` (JSONL events), `--output-schema <file>`, `-o <file>`, `-m`, `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `-s read-only`, `-C`. One router call at 2026-10-04T20:04:48Z was refused before answering: JSONL `error` + `turn.failed` with `"You've hit your usage limit. … try again at 11:22 PM."` (host time Europe/Berlin ⇒ 21:22Z), exit 1. **The success-path event shape (final message, `usage` block, whether the answering model is named) is therefore not yet measured.** | `codex --version`, `codex exec --help`, `~/.codex/models_cache.json`, one call |
| F-13 | FUN-6 reads **Done** in Jira (updated 2026-10-04 09:08 UTC, comment 10098), while its own comment 10075 recorded the evaluation-corpus and verdict rows as unmet. This phase delivers those rows; FUN-6's status is not this package's to change. | Jira read 2026-10-04 |

## 2. Users

- **Maintainer** — rules on the verdict and on publication; needs one table and
  one finding that can be re-derived from a command.
- **Evaluator (the implementer of this package)** — runs the corpus against the
  three comparators inside a time box and a rate-limited budget.
- **Reviewer** — checks that no number was hand-edited and that the corpus was
  frozen before the first measurement.

## 3. User stories

- **US-1.** As the maintainer, I approve a fixed corpus *before* any comparator
  sees it, and know that any later edit forces a new version and a full re-run.
- **US-2.** As an evaluator, I replay the same corpus against a hermetic, a
  frontier and a deterministic comparator through one seam, none of them seeing
  more than another.
- **US-3.** As an evaluator, I run the replay in chunks no longer than one tool
  call, resume it where it stopped, and have a rate limit recorded as a failed
  comparison rather than lost.
- **US-4.** As the maintainer, I read where the hermetic decision may replace the
  frontier one and where escalation is still required, with the rule that
  derived it.
- **US-5.** As a reviewer, I regenerate the benchmark table from the run ledger
  and the corpus digest and get the same bytes.

## 4. Behaviour

### 4.1 The corpus — versioned, frozen before the first measurement

- **B-1.** The corpus is version `v1`: one JSON-Lines file
  `tests/hermetic_eval/corpus/v1/scenarios.jsonl` of **40 scenarios**, **10 per
  expected route**, and in each route **6 `clear` and 4 `borderline`**.
- **B-2.** Each scenario carries exactly: `id` (`s01`…`s40`), `state` (the
  unstructured request text, 1–600 characters), `expected` (one of the four
  routes), `stratum` (`clear` | `borderline`) and `rationale` (one sentence
  naming the rubric clause that decides the label).
- **B-3.** **Label provenance.** Labels are assigned against a written rubric,
  `tests/hermetic_eval/corpus/v1/LABELING.md`, whose four clauses are the four
  option meanings `ROUTER` declares, plus tie-break rules (any risk of harm,
  money movement, legal or account-security consequence ⇒ `human_review`; a
  question a fixed rule or lookup answers ⇒ `deterministic` even when phrased
  loosely). The implementer drafts scenarios and labels; **the maintainer
  approves the corpus before it is frozen** (D-4). No model labels the corpus,
  and no comparator output is consulted while drafting it.
- **B-4.** **Freeze.** Freezing writes `tests/hermetic_eval/corpus/v1/corpus.lock.json`
  carrying the SHA-256 of the scenario file's bytes, the counts of B-1, the seed
  `20261004`, the repeat count `5`, the time box of B-9, the SHA-256 of each
  comparator's identity (B-6), the boundary constants of B-21, and `frozen_at`
  (UTC). The lock is committed before the first measurement cell.
- **B-5.** **No tuning after the first measurement.** The replay refuses to
  start or resume (exit 2, nothing written) when the lock is missing, when the
  scenario file's digest differs from the lock, or when a comparator's identity
  digest differs from the lock. Changing a scenario, a label, a comparator's
  model, prompt, schema or rule table therefore needs a **new corpus version**
  (`v2/`, `v1/` kept) and a **full re-run** of every comparator. The corpus
  digest is written into every evidence artifact (B-23).

### 4.2 Three comparators through one seam

- **B-6.** Each comparator is a `DecisionProvider` registered as the router's
  `decision` strategy through `DecisionGateResolver`, so each is judged by the
  **same gate, the same declared rule and the same fallback**. Each receives the
  same `ChoiceRequest` the gate builds — `state` = the scenario's `state`,
  `instructions` and `options` = `ROUTER`'s, `model` = `None` — and nothing else:
  no `id`, `expected`, `stratum`, `rationale`, no other scenario, no examples.
  Each declares an **identity** — a JSON object whose SHA-256 the lock pins:
  - **hermetic** — `JevDecisionProvider(JevConfig(model="jev-1.13-free",
    endpoint="https://opencode.ai/zen/v1/systemone"))` from
    `functualize_decision_jev`, credential from `OPENCODE_API_KEY` (exported
    from the `opencode-go` entry of `~/.local/share/opencode/auth.json`).
    Identity: provider, model, endpoint, plugin version.
  - **frontier** — a provider that renders the `ChoiceRequest` into one fixed
    prompt and runs one `codex exec` call on the maintainer's Codex login
    (exact argv in `contracts.md` C-3; model `gpt-6-astra`, reasoning effort
    `medium`, D-2), constrained by `--output-schema` to
    `{"choice": <option>, "probabilities": {<option>: number, …}}`, reading
    `choice` as the proposal and `probabilities` as the distribution (D-3).
    Identity: CLI, model, effort, argv template, SHA-256 of the prompt template
    and of the JSON schema.
  - **deterministic** — an ordered table of case-insensitive regular expressions
    over `state` only; the first match proposes its route with distribution
    `{route: 1.0, others: 0.0}`; no match proposes `human_review` with a uniform
    `0.25` distribution, which the gate's margin rule refuses, so the fallback
    takes it. Identity: SHA-256 of the rule table. **The table is written and
    committed before the corpus is drafted** (task order), from `ROUTER`'s
    option meanings only.
- **B-7.** **Model drift invalidates the run.** Every frontier cell records the
  CLI version and, when the event stream names it, the model that answered; a
  cell whose named model differs from the identity's is recorded as
  `invalid_model` and the replay stops that run (exit 3). If T3's probe shows
  the stream never names the model, the cell records `model: null`, the pinned
  `-m gpt-6-astra` is the only identity, and the finding says so as a
  deviation. A CLI version change is recorded per cell and reported as a
  deviation; it does not by itself invalidate a run.
- **B-8.** **A provider failure is data.** A rate limit, an outage, a refusal,
  a malformed answer or a timeout is a **failed comparison** — the gate's own
  fallback takes the cell exactly as it would in production, and the cell is
  recorded with its failure kind, status and `retry_after`. A failed cell is
  never retried and never dropped; no scenario is ever skipped.

### 4.3 The replay — repeated, ordered, chunked, resumable, time-boxed

- **B-9.** **Time box.** A run of one comparator over the corpus is `40 × 5 =
  200` cells and must reach its last cell within **72 hours** of its first.
  Cells not attempted when the box closes are recorded as `not_attempted` and
  counted as failures in availability, never omitted.
- **B-10.** **Order.** For repeat `r` in `1..5`, the scenarios run in the order
  of `random.Random(20261004 + r).sample(ids, k=40)`. Repeats are outermost, so
  an interruption shortens repeats uniformly rather than dropping scenarios.
- **B-11.** **Chunking.** One invocation runs cells until a wall-clock budget
  (`--budget-seconds`, default 360) has elapsed — checked before each cell, so
  one invocation overruns by at most one cell's provider timeout (180 s
  frontier, 30 s hermetic) and stays inside a 600 s tool call — then exits 0
  with the next cell named. Re-invoking with the same run directory resumes at the first
  unattempted cell. The ledger is append-only: one JSON line per attempted cell,
  written and flushed before the next cell starts.
- **B-12.** **Rate-limit pause.** After a cell fails `rate_limited`, the
  invocation records that cell and exits 0, printing the UTC time the window
  reopens (`resume after unknown` when the provider gave none); it never sleeps
  and never re-attempts that cell. So each exhausted window costs exactly one
  failed cell, recorded as data. The Codex usage limit (F-14) is a
  `rate_limited` failure; its `retry_after` is the seconds until the "try again
  at <time>" it names, read in the host's local time zone.
- **B-13.** **Isolation.** Each cell boots a fresh `FunctualizeApp` in a scratch
  project inside the run directory and uses its own scope id
  (`<comparator>-r<repeat>-<scenario id>`); the run directory defaults to
  `$XDG_STATE_HOME/functualize-hermetic-eval/<run id>/` (else
  `~/.local/state/…`), **outside the repository**.
- **B-14.** **Where each number comes from.** Route, `decided_by`, proposal,
  distribution, provider confidence, probability, margin, verdict, failure and
  latency come from `decision_record(...)` and its evidence — the gate's own
  record. The harness adds only what the evidence cannot carry: the expected
  label, the stratum, the repeat, and for the frontier comparator the CLI
  version, the model the stream names (if any) and its token breakdown.

### 4.4 The measurement protocol

Each metric is computed by `tests/hermetic_eval/metrics.py` from the ledgers
and printed by the report command (B-23), per comparator, overall and per
stratum.

- **B-15. Agreement / accuracy.** Two 4×4 confusion matrices, rows = expected
  route, columns = outcome: (a) **routed** — the route the gate took; (b)
  **proposed** — the comparator's proposal before the gate (failed cells form a
  fifth `failed` column). Per route: precision, recall; overall: accuracy and
  macro-F1. Pairwise agreement of routed outcomes between comparators on the
  same scenario and repeat, with Cohen's κ.
- **B-16. Calibration.** Over cells with a distribution, the probability the
  gate reads (`evidence.probability`, the proposal's) is binned into ten
  equal-width bins `[0,0.1)…[0.9,1.0]`; per bin: count, mean probability,
  proposal accuracy. Scalars: expected calibration error (count-weighted mean
  of |accuracy − mean probability|) and the multi-class Brier score over the
  four options. The provider's own `confidence`, where reported, is calibrated
  the same way and reported separately; it is never an input to anything else.
- **B-17. Abstention and escalation quality.** *Escalated* = cells the gate
  routed to `human_review`, split by cause (`fallback`: below threshold, no
  distribution, uncovered proposal, provider failure; `proposal`: the
  comparator proposed `human_review` and it was accepted). *Needed escalation* =
  cells whose expected route is `human_review` **or** whose proposal differs
  from the expected route. Report coverage (share auto-routed), selective
  accuracy (accuracy of auto-routed cells), escalation precision
  (|escalated ∩ needed| / |escalated|) and recall (|escalated ∩ needed| /
  |needed|).
- **B-18. Latency and cost.** Latency is `evidence.latency_seconds` (measured by
  the gate around the provider call): p50, p95, max. Cost per cell and per run:
  **deterministic** `$0`, no tokens; **hermetic** billed `$0` on the free tier,
  with input/output tokens reported — no price is invented for the unfunded
  paid tier; **frontier** — the Codex login is a ChatGPT subscription that
  reports tokens, not dollars, so the frontier's cost is its **tokens**: input
  (with the cached share reported separately) and output (with the reasoning
  share reported separately), from the stream's `usage` block. No dollar figure
  is invented for it; the report labels its dollar cell *subscription,
  unpriced*. The run's **frontier intelligence consumption** = frontier tokens ÷
  correctly routed cells.
- **B-19. Run-to-run variance.** Per scenario over its 5 repeats: the share of
  repeats equal to the modal routed outcome, whether the routed outcome flipped
  (more than one distinct value), and the standard deviation of the proposal's
  probability. Overall: mean modal agreement, flip count, mean standard
  deviation. The deterministic comparator must show **zero** flips and zero
  deviation — a self-check of the harness.
- **B-20. Threshold sensitivity and the two asymmetric errors.** Recomputed
  offline from the recorded distributions, with no new provider call, over the
  declared sweep `accept_at ∈ {0.50, 0.55, …, 0.95}` × `min_margin ∈ {0.00,
  0.05, 0.10, 0.15, 0.20}` (50 points), using the gate's rule (F-4) and
  treating a failed cell as the fallback. At each point, per comparator:
  coverage, selective accuracy, and two errors counted separately —
  - **false-continue**: the gate auto-routed (decided by the decision) to a
    route other than the expected one; of these, **unsafe-continue**: expected
    `human_review`, auto-routed elsewhere;
  - **false-stop**: the cell ended at `human_review` while its expected route
    is automated, split by cause (fallback vs. proposal).
  Per scenario, the report names the `accept_at` (at the declared
  `min_margin=0.10`) where its routed outcome flips. **Conformance:** at the
  declared point `(0.70, 0.10)` the offline rule must reproduce the gate's
  recorded route for every cell; any mismatch fails the report (exit 4).

### 4.5 The boundary statement and the verdict

- **B-21.** The boundary is derived by rule, with constants fixed in the lock
  before the first cell (D-5): for each **proposed route** `r` of the hermetic
  comparator, `t_r` is the lowest swept `accept_at` (at `min_margin=0.10`) such
  that the hermetic cells proposing `r` with probability ≥ `t_r` have
  (i) at least **10** cells drawn from at least **4** distinct scenarios — repeats of one scenario are correlated, so cells alone overstate support — (ii) **zero** unsafe-continues, and (iii) accuracy
  no more than **0.05** below the frontier comparator's routed accuracy on the
  same scenarios, over the frontier's **non-failed** cells only — a frontier
  cell lost to its own usage limit falls back to `human_review`, and counting it
  would lower the bar the hermetic decision has to clear. Where `t_r` exists, the hermetic decision is **trusted to
  replace the frontier decision** for proposals of `r` at probability ≥ `t_r`;
  everywhere else — other routes, lower probabilities, failed cells —
  **escalation is still required**. A route that misses (i) at every threshold reads
  **insufficient evidence**, never trusted.
- **B-22.** The **computed verdict** follows from the boundary, by rule:
  - **adopt** (for a bounded resolver class) — at least one route has a `t_r`
    covering at least **25 %** of the hermetic cells proposing it, the hermetic
    comparator's availability (non-failed cells) is at least **90 %**, and the
    hermetic comparator has zero unsafe-continues at the declared point;
  - **reject** — no route has a `t_r` and the hermetic routed accuracy at the
    declared point is below the deterministic baseline's;
  - **continue research** — otherwise, naming the uncertainty that blocked
    adopt (insufficient evidence on route X, availability Y %, unsafe-continue
    on scenario Z).
  The computed verdict is a recommendation; the disposition is the
  maintainer's (parent Stage 6).

### 4.6 The evidence artifact

- **B-23.** One command — `uv run python -m tests.hermetic_eval.report
  --run-dir <hermetic> --run-dir <frontier> --run-dir <deterministic> --out
  <dir>` — writes `benchmark.md` (the table), `finding.md` (boundary, verdict,
  deviations), `boundary.json` and `metrics.json`. Every file carries the corpus
  version and SHA-256, each comparator's identity digest, each ledger's SHA-256,
  the run ids and the repository commit. Nothing in them is typed by hand.
- **B-24.** Re-running the command over the same ledgers produces byte-identical
  files; `--check <dir>` recomputes and exits 1 on any difference.
- **B-25.** **Not committed; published to Confluence only.** Run directories
  and report output live outside the repository (B-13). They are delivered to
  the maintainer on the tracker **and**, approved under D-6, published as one
  Confluence page in the Functualize space (key `SD`), a child of the research
  plan page `5144577`, titled `Hermetic Evaluation — Corpus v1 Results`: the
  page body carries `finding.md` and `benchmark.md`, and the four report files
  plus the three ledgers are attached. The page states the corpus digest and
  that the computed verdict is a recommendation. The durable half committed to
  the repository is the *method* (`contributor/reference/hermetic-evaluation.md`)
  — the corpus, the protocol, the commands — and **no measured number**.

### 4.7 The scope guard

- **B-26.** Routing only: one corpus, one workflow class (the Phase 2 router),
  three comparators. No general capability benchmark, no leaderboard, no
  second workflow, no model gateway, no provider registry.
- **B-27.** No product change: no file under `src/functualize/**` or
  `plugins/**` changes; Jev stays a candidate generator behind the existing
  gate; nothing makes Jev a dependency outside this instrument.
- **B-28.** No offline test makes a network call or spawns `codex` (or any process); the live
  replay is a command, never collected by pytest.

## 5. Acceptance criteria

Each is decided by the command beside it; `tasks.md` binds each to its task.
Commands run from the repository root.

- **AC-1** (B-1, B-2). `uv run pytest tests/hermetic_eval/test_corpus.py -q` passes,
  including the case that loads `corpus/v1/scenarios.jsonl` and asserts 40
  scenarios, 10 per route, 6/4 per stratum, unique ids, the five keys.
- **AC-2** (B-4, B-5). `uv run python -m tests.hermetic_eval.replay --corpus v1
  --comparator deterministic --run-dir <tmp>` exits 2 and writes nothing when
  one byte of `scenarios.jsonl` differs from the lock, and when the lock is
  absent; `test_replay.py` covers both.
- **AC-3** (B-6). `test_replay.py`: a recording fake provider replayed over a
  3-scenario corpus receives requests whose `state` equals each scenario's
  `state`, whose `options`/`instructions` equal `ROUTER`'s, and that contain no
  scenario `id`, `expected`, `stratum` or `rationale` text.
- **AC-4** (B-6, B-7, B-12). `test_comparators.py`: the frontier comparator,
  driven through a fake process runner, builds exactly the argv of
  `contracts.md` C-3; maps the success JSONL fixture T3 measured to the
  `DecisionResult` of C-3; maps the measured usage-limit JSONL (F-14) to
  `rate_limited` with `retry_after` equal to the seconds until the named local
  time; maps any other `turn.failed`/non-zero exit, a missing or non-JSON final
  message, a `choice` outside the options, an out-of-range probability and a
  timeout to `DecisionUnavailableError` with the C-3 kinds; and, where the
  stream names a model, reports a mismatch so the replay records
  `invalid_model`.
- **AC-5** (B-6). `test_comparators.py`: the deterministic comparator returns
  the same result for the same state across 100 calls, a one-hot distribution
  on a match and the uniform `0.25` distribution on no match; and its identity
  digest equals the lock's.
- **AC-6** (B-8, B-12). `test_replay.py`: a fake provider raising
  `rate_limited` (`retry_after=19014`) on cell 2 yields a ledger of exactly 2
  lines, the second with `failure.kind == "rate_limited"` and route
  `human_review`, exit 0, a printed reopen time, and no `time.sleep` call;
  resuming continues at cell 3, never re-attempting cell 2.
- **AC-7** (B-10, B-11). `test_replay.py`: a run interrupted by
  `--budget-seconds` and resumed produces the same ledger (excluding
  timestamps and latencies) as an uninterrupted run, in the B-10 order.
- **AC-8** (B-15…B-20). `uv run pytest tests/hermetic_eval/test_metrics.py -q`
  passes against hand-computed fixtures for each metric, including a
  deterministic ledger with zero flips.
- **AC-9** (B-20). `test_metrics.py`: the offline rule at `(0.70, 0.10)`
  reproduces the routed outcome of every cell of a ledger produced through the
  real router (`test_replay.py` fixture), and a doctored ledger makes the report
  exit 4.
- **AC-10** (B-21, B-22). `test_report.py`: three fixture ledgers built to land
  on each verdict yield `adopt`, `continue research` (naming the blocking
  uncertainty) and `reject`; a route with 9 qualifying cells, and one with 12
  cells from 3 scenarios, each read `insufficient evidence`.
- **AC-11** (B-23, B-24). `test_report.py`: two report runs over the same
  ledgers are byte-identical, `--check` exits 0 on them and 1 after one byte of
  `benchmark.md` is changed; every output file contains the corpus SHA-256.
- **AC-17** (B-25, live). After T9, the Confluence page exists in space `SD`
  under page `5144577`, its body contains the corpus SHA-256, and it carries
  seven attachments — read back live with the Atlassian tools.
- **AC-12** (B-9…B-14, live). For each of the three comparators, the ledger in
  its run directory has 200 lines, one per cell, each with a route; the report
  command over the three exits 0. *(Decided at T8 by the evaluator; the ledger
  is delivered, not committed.)*
- **AC-13** (B-25, B-27). `git diff --name-only origin/master...HEAD -- src
  plugins | wc -l` returns 0, and no file under the repository matches
  `cells.jsonl` or `benchmark.md` (`git ls-files | rg -c
  'cells\.jsonl|benchmark\.md'` returns 0).
- **AC-14** (B-26, scope). `git diff --name-only origin/master...HEAD -- examples
  docs | wc -l` returns 0; the router file still imports no model client
  (F-11's count stays 0).
- **AC-15** (B-28). `rg -l "^(from|import) functualize\._" tests/hermetic_eval | wc -l`
  returns 0 (public API only), and no test module under `tests/hermetic_eval/`
  imports `subprocess` (`rg -l "^import subprocess|^from subprocess"
  tests/hermetic_eval/test_*.py | wc -l` returns 0).
- **AC-16** (standing). `rg -c functualize_decision_jev src` returns 0; the
  Phase 2 suites `examples/standalone/hermetic_router/tests/test_router.py` and
  `tests/workflow/test_decision_record.py` pass unchanged.

## 6. Out of scope

- The parent's Phase 4 (skill router), Phase 5 (publication) and Stage 6
  (disposition).
- Benchmark configurations A–E of the research plan (coding agents, judges):
  this phase measures routing only.
- Recording monetary cost inside product evidence (`.spec/STATUS.md` → *Still
  open after the hermetic router*): cost is computed by this instrument, not
  written into `decision-evidence/1` (D-7).
- Funding the paid zen tier, the paid `jev-1.13`, or any change to the Jev
  plugin's wire mapping.
- Tuning `ROUTER`'s thresholds: the sweep is descriptive; the declared point is
  the one the boundary and the verdict are judged at.

## 7. Standing constraints, restated as testable lines

- **Routing, not general intelligence** — B-26; AC-14.
- **No model gateway, no new authority primitive, no Gate renames** — B-27;
  AC-13 (no `src/`/`plugins/` change at all).
- **Jev stays a candidate generator; never a dependency outside this track** —
  B-6 (registered through `DecisionGateResolver`), AC-16.
- **Never authorize a consequential side effect from confidence alone** — the
  router has no effecting step (Phase 2), and the provider's `confidence` is
  calibrated but never consulted (B-16).
- **The time box is part of the experiment** — B-9; a second workflow, a broader
  catalogue or a gateway means the scope is wrong.
- **No publication without the maintainer** — B-25; AC-13. The maintainer
  approved Confluence (D-6); the repository still carries no measured number.
