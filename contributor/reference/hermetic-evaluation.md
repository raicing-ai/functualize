# Hermetic evaluation — the routing instrument

Phase 3 of the decision-layer experiment: one **frozen corpus**, replayed through
the Phase 2 hermetic router against three comparators, measured for routing
quality, ending in a boundary statement and a computed verdict the maintainer
rules on. The instrument is `tests/hermetic_eval/`, it runs as two commands, and
it changes nothing under `src/functualize/**` or `plugins/**`.

## What it measures

The router (`examples/standalone/hermetic_router/`) routes one request among
`deterministic | cheap_model | frontier_agent | human_review`: a
`DecisionProvider` proposes, the gate's declared rule decides, and the decision
rung records evidence. What no single pass can say is **whether a hermetic
(Jev-backed) proposal is good enough to replace a frontier model's routing
decision, and where it is not** — the question the experiment exists to answer.

Comparison is under the closest thing to one protocol the experiment could make
it: all three comparators are registered as the router's `decision` strategy
through `DecisionGateResolver`, so they are judged by the **same gate, the same
declared rule** (`accept_at=0.70`, `min_margin=0.10`) **and the same fallback**
(`human_review`). Each receives exactly the `ChoiceRequest` the gate builds —
`state` is the scenario text, `instructions` and `options` come from the
router's option meanings, `model` is `None` — and nothing else: no scenario id,
no expected label, no stratum or rationale, no other scenario, no examples.

Scope is routing only: one corpus, one workflow class, three comparators. It is
not a general capability benchmark, not a leaderboard, and it adds no second
workflow, model gateway or provider registry. The measurement ends in a
**computed verdict** — adopt for a bounded resolver class, reject, or continue
research naming the uncertainty that blocked adopt — and that verdict is a
**recommendation**: the disposition is the maintainer's.

## The corpus and its freeze

The corpus is version `v1`, one JSON-Lines file,
`tests/hermetic_eval/corpus/v1/scenarios.jsonl`: **40 scenarios**, **10 per
expected route**, and within each route **6 `clear` and 4 `borderline`**. Each
line carries exactly `id` (`s01`…`s40`), `state` (the unstructured request
text, 1–600 characters), `expected` (one of the four routes), `stratum`
(`clear` | `borderline`) and `rationale` (one sentence naming the rubric clause
that decided the label).

Labels are assigned against a written rubric,
`tests/hermetic_eval/corpus/v1/LABELING.md`, whose clauses are the router's four
option meanings plus the tie-breaks: any risk of harm, money movement, legal or
account-security consequence is `human_review`, and a question a fixed rule or
lookup answers is `deterministic` even when it is phrased loosely. The
implementer drafts the scenarios and the labels and the **maintainer approves
them before the freeze**; no model labels the corpus, and no comparator output
is consulted while drafting it.

Freezing writes `corpus/v1/corpus.lock.json` carrying the SHA-256 of the
scenario file's bytes, the counts above, the seed `20261004`, the repeat count
`5`, the 72-hour time box, the SHA-256 of each comparator's identity, the
boundary constants and `frozen_at` (UTC). The lock is committed before the first
measurement cell, and the replay refuses to start or resume — exit 2, nothing
written — when the lock is missing, when the scenario file's digest differs from
it, or when a comparator's identity digest differs from it.

**No tuning after the first measurement.** Changing a scenario, a label, a
comparator's model, prompt, schema or rule table needs a new corpus version
(`v2/`, with `v1/` kept) and a full re-run of every comparator. The corpus
digest is written into every evidence artifact, so a result can always be traced
to the exact measuring stick that produced it. The deterministic comparator's
rule table is written and committed before the corpus is drafted, from the
option meanings alone.

## The three comparators

- **hermetic** — `JevDecisionProvider` with `model="jev-1.13-free"` at
  `https://opencode.ai/zen/v1/systemone` (plugin `functualize-decision-jev`,
  version `0.1.0`), its credential read from `OPENCODE_API_KEY`. Identity:
  provider, model, endpoint and plugin version.
- **frontier** — a provider that renders the `ChoiceRequest` into one fixed
  prompt and runs one CLI call on the maintainer's subscription login, pinned to
  a named model and reasoning effort, constrained by `--output-schema` to
  `{"choice": <option>, "probabilities": {<option>: number, …}}`: `choice` is
  read as the proposal and `probabilities` as the distribution. Identity: CLI
  version, model, effort, argv template, and the SHA-256 of the prompt template
  and of the JSON schema.
- **deterministic** — an ordered table of case-insensitive regular expressions
  over `state` only; the first match proposes its route with the distribution
  `{route: 1.0, others: 0.0}`. No match proposes `human_review` with a uniform
  `0.25`, which the margin rule refuses, so the gate's fallback takes the cell.
  Identity: the SHA-256 of the rule table. Its zero flips and zero probability
  deviation across repeats are the harness's own self-check.

Two rules keep the comparison honest. **Model drift invalidates a run:** every
frontier cell records the CLI version and, when the event stream names it, the
model that answered; a cell whose named model differs from the identity's is
recorded `invalid_model` and stops that run (exit 3). A CLI version change is
recorded per cell and reported as a deviation; it does not by itself invalidate a
run. **A provider failure is data:** a rate limit, an outage, a refusal, a
malformed answer or a timeout is a failed comparison — the gate's own fallback
takes the cell exactly as it would in production, the cell is recorded with its
failure kind, status and `retry_after`, and it is never retried and never
dropped. No scenario is ever skipped.

## Running it

Measured on a served machine. The frontier comparator needs the maintainer's CLI
login live (it draws on that subscription's usage window), and no other work on
the same login runs while a measurement is in flight — it shares the window.
The hermetic comparator reads `OPENCODE_API_KEY` from the environment; export it
in the same shell call as the replay, from the `opencode-go` entry of the CLI's
`auth.json`, and never print it.

One run of one comparator over the corpus is `40 × 5 = 200` cells:

```bash
uv run python -m tests.hermetic_eval.replay --corpus v1 --comparator hermetic \
    --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-hermetic"
uv run python -m tests.hermetic_eval.replay --corpus v1 --comparator frontier \
    --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-frontier"
uv run python -m tests.hermetic_eval.replay --corpus v1 --comparator deterministic \
    --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-deterministic"
```

For repeat `r` in `1..5` the scenarios run in the order of
`random.Random(20261004 + r).sample(ids, k=40)`. Repeats are outermost, so an
interruption shortens repeats uniformly rather than dropping scenarios. One
invocation runs cells until a wall-clock budget (`--budget-seconds`, default
360) has elapsed — checked before each cell, so an invocation overruns by at
most one cell's provider timeout — then exits 0 and names the next cell;
re-invoking with the same `--run-dir` resumes at the first unattempted cell. The
ledger is append-only, and the run directory (default
`$XDG_STATE_HOME/functualize-hermetic-eval/<run id>/`, else `~/.local/state/…`)
is **outside the repository**. A run must reach its last cell within **72 hours**
of its first; cells not attempted when the box closes are recorded
`not_attempted` and counted as failures in availability, never omitted.

`OPENCODE_API_KEY` extracts from `~/.local/share/opencode/auth.json` as:

```bash
export OPENCODE_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.local/share/opencode/auth.json')))['opencode-go']['key'])")"
```

After a cell fails `rate_limited` the invocation records that cell and exits 0,
printing the UTC time the provider's window reopens (`resume after unknown` when
the provider named none). It never sleeps and never re-attempts that cell, so
each exhausted window costs exactly one failed cell, recorded as data. On exit 3
(`invalid_model`) the run is void and is reported, not resumed. A comparator
that has completed its 200 cells is never re-run to "improve" its numbers: a
second run is a new run id, and both are reported.

Once all three ledgers hold 200 rows, one command writes the evidence:

```bash
uv run python -m tests.hermetic_eval.report \
    --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-hermetic" \
    --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-frontier" \
    --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-deterministic" \
    --out "$HOME/.local/state/functualize-hermetic-eval/v1-report"
uv run python -m tests.hermetic_eval.report --run-dir … --check <dir>
```

It writes `benchmark.md` (tables), `finding.md` (boundary, verdict, deviations),
`boundary.json` and `metrics.json`, each carrying the corpus version and
SHA-256, each comparator's identity digest, each ledger's SHA-256, the run ids
and the repository commit — nothing in them is typed by hand. Re-running it over
the same ledgers is byte-identical; `--check` recomputes and exits 1 on any
difference. Its exit codes are 0 for written or identical, 1 for a `--check`
difference, 2 when the three runs disagree on corpus digest or a comparator is
missing or duplicated, and 4 for a **conformance failure**: the offline rule at
the declared point disagrees with a route the gate recorded, which means the
ledger is not self-consistent and no report is written. Exit 4 is a finding to
report, never a line to patch.

The evidence is **not committed**. Run directories and report output live
outside the repository; they are delivered to the maintainer on the work tracker
and published as one page in the project's Confluence space. The durable half
committed here is the method — this page, the corpus, the protocol and the
commands — and no measured number.

## The measurements

Every number comes from `decision_record(...)` and its evidence — the gate's own
record. The harness adds only what the evidence cannot carry: the expected
label, the stratum, the repeat, and for the frontier comparator the CLI version,
the model the stream names (if any) and its token breakdown.

- **Agreement and accuracy.** Two 4×4 confusion matrices, rows = expected route,
  columns = outcome: the route the gate took (`routed`) and the comparator's
  proposal before the gate (`proposed`; failed cells form a fifth `failed`
  column). Per route: precision and recall. Overall: accuracy and macro-F1.
  Pairwise agreement of routed outcomes between comparators on the same scenario
  and repeat, with Cohen's κ.
- **Calibration.** The probability the gate reads is binned into ten equal-width
  bins `[0,0.1)…[0.9,1.0]`; per bin: count, mean probability, proposal
  accuracy. Scalars: expected calibration error (the count-weighted mean of
  |accuracy − mean probability|) and the multi-class Brier score over the four
  options. A provider's own `confidence`, where it reports one, is calibrated
  the same way and reported separately; it is never an input to anything else.
- **Abstention and escalation quality.** *Escalated* = cells routed to
  `human_review`, split by cause (`fallback`, from below-threshold, no
  distribution, an uncovered proposal or a provider failure, versus `proposal`,
  where the comparator proposed `human_review` and it was accepted). *Needed
  escalation* = cells whose expected route is `human_review` **or** whose
  proposal differs from the expected route. Reported: coverage (the share
  auto-routed), selective accuracy (accuracy of the auto-routed cells), and
  escalation precision and recall.
- **Latency and cost.** Latency is `evidence.latency_seconds`, measured by the
  gate around the provider call: p50, p95, max. Cost per cell and per run: the
  deterministic comparator is `$0` with no tokens; the hermetic comparator is
  billed `$0` on its free tier and reports input/output tokens — no price is
  invented for the unfunded paid tier; the frontier runs on a subscription that
  reports tokens, not dollars, so its cost **is** its tokens (input, with the
  cached share reported separately, and output, with the reasoning share
  reported separately) and its dollar cell reads *subscription, unpriced*. The
  run's frontier intelligence consumption is frontier tokens ÷ correctly routed
  cells.
- **Run-to-run variance.** Per scenario over its five repeats: the share of
  repeats equal to the modal routed outcome, whether the routed outcome flipped,
  and the standard deviation of the proposal's probability. Overall: mean modal
  agreement, flip count, mean standard deviation.
- **Threshold sensitivity and the two asymmetric errors.** Recomputed offline
  from the recorded distributions, with no new provider call, over the declared
  sweep `accept_at ∈ {0.50, 0.55, …, 0.95}` × `min_margin ∈ {0.00, 0.05, 0.10,
  0.15, 0.20}` (50 points), using the gate's rule and treating a failed cell as
  the fallback. At each point, per comparator: coverage, selective accuracy and
  two errors counted separately — **false-continue** (the gate auto-routed to a
  route other than the expected one; of these, **unsafe-continue** where the
  expected route was `human_review`) and **false-stop** (the cell ended at
  `human_review` while its expected route is automated), the latter split by
  cause. Per scenario the report names the `accept_at` at the declared
  `min_margin=0.10` where its routed outcome flips.

## The boundary and the verdict rule

The boundary is derived by rule, from constants fixed in the lock before the
first cell. For each **proposed route** `r` of the hermetic comparator, `t_r` is
the lowest swept `accept_at` (at `min_margin=0.10`) such that the hermetic cells
proposing `r` with probability ≥ `t_r` have at least **10** cells drawn from at
least **4** distinct scenarios — repeats of one scenario are correlated, so
cells alone overstate support — **zero** unsafe-continues, and an accuracy no
more than **0.05** below the frontier comparator's routed accuracy on the same
scenarios, over the frontier's **non-failed** cells only, since a frontier cell
lost to its own usage limit falls back to `human_review` and counting it would
lower the bar.

Where `t_r` exists, the hermetic decision is **trusted to replace the frontier
decision** for proposals of `r` at probability ≥ `t_r`. Everywhere else — other
routes, lower probabilities, failed cells — **escalation is still required**. A
route that misses the support test at every threshold reads *insufficient
evidence*, never trusted.

The computed verdict follows: **adopt** (for a bounded resolver class) when at
least one route has a `t_r` covering at least **25 %** of the hermetic cells
proposing it, hermetic availability (non-failed cells) is at least **90 %**, and
the hermetic comparator has zero unsafe-continues at the declared point;
**reject** when no route has a `t_r` and hermetic routed accuracy at the declared
point is below the deterministic baseline's; **continue research** otherwise,
naming the uncertainty that blocked adopt — insufficient evidence on a route, an
availability figure, an unsafe-continue on a scenario.

## What it does not measure

- **Anything but routing.** One corpus, one workflow class, three comparators:
  no general capability benchmark, no leaderboard, no second workflow, no model
  gateway, no provider registry.
- **Any production change.** No file under `src/functualize/**` or `plugins/**`
  moves; Jev stays a candidate generator behind the existing gate and becomes a
  dependency of nothing outside this instrument.
- **Anything over the network, in CI.** No offline test makes a network call or
  spawns any process; the live replay is a command, never collected by pytest.
- **A decision.** The verdict is a recommendation computed from the boundary;
  the disposition is the maintainer's.
- **Dollars for the frontier**, and real cost for the hermetic comparator: both
  report tokens, and the hermetic tier is free at the measured model.
- **A universal answer.** It speaks for one corpus version and one workflow
  class, its borderline labels rest on the maintainer's judgement against the
  rubric, and five repeats bound the variance estimate it reports — not the
  tail.
