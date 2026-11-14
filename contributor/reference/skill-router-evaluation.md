# Skill router evaluation — the selection instrument

Phase 4 of the decision-layer experiment: one **frozen corpus** of requests,
each asking which functualize skill an agent should load before work starts,
replayed through one selection gate against four comparators, plus a small
downstream subset that runs real agent tasks under three ways of loading
skills. It ends in a computed verdict the maintainer rules on. The instrument
is `tests/skill_router_eval/` with the downstream arms in `evals/`, it runs as
four commands, and it changes nothing under `src/functualize/**`,
`plugins/**` or `examples/`.

## What it measures

An agent working in a functualize project can load one of four bundled skills
— `functualize`, `functualize-app`, `functualize-cli`, `functualize-skill` — or
none. Today the agent sees every skill's description and picks for itself
(the **native** behaviour). The question is **whether a gated selection made
before the first turn — one `ChoiceRequest`, five options, the existing
decision seam — picks the right skill reliably enough, and whether loading only
that skill makes the agent's work cheaper without making it worse.**

Two halves answer it:

- **Routing, on the corpus.** Every comparator sees exactly the `ChoiceRequest`
  the gate builds: `state` is the request text, `instructions` and `options`
  come from the frozen catalog. No scenario id, expected label, stratum,
  rationale or origin reaches a comparator.
- **Downstream, on five agent tasks.** The same tasks run under three arms
  that differ only in which skills are mounted and appended to the system
  prompt. Success is graded by each task's deterministic asserts.

## The catalog and the corpus freeze

**The catalog** (`tests/skill_router_eval/catalog.py`) is derived from
`skills/*/SKILL.md`: each skill's name, description, the digest of its files
and their byte counts, plus the meaning of `none` ("No functualize skill
applies; answer without loading one."). The five option meanings the gate
offers are those descriptions, word for word. The catalog has a version and
a SHA-256 digest; editing any `SKILL.md` changes it.

**Corpus `v1`** is `tests/skill_router_eval/corpus/v1/scenarios.jsonl`: 40
scenarios, 8 per option, each option split 5 `clear` and 3 `borderline`.
Twenty-one are seeded from `evals/suites/triggering.yaml` and keep that suite's
label; the rest were drafted against the rubric `corpus/v1/LABELING.md`, whose
five clauses are the option meanings plus tie-breaks. No model labelled the
corpus and no comparator output was consulted while drafting. A reviewer who
did not draft it checked every rationale against the rubric before the freeze.
Requests that genuinely need two skills are listed in `corpus/v1/TWO_SKILL.md`
and deliberately not labelled.

**The freeze pins the whole question, not only the scenarios.**
`corpus/v1/corpus.lock.json` holds:

- the scenarios' digest and counts, the seed, the repeat count and the time box;
- the catalog JSON and its digest — what the options *say*;
- the selection rule: field, instructions, the five meanings, `accept_at`,
  `min_margin`, `fallback`, and the gate's own `rule_digest` for that rule,
  taken from one probe selection through the real workflow;
- the **instrument digest**: one SHA-256 over every file whose code decides
  what a cell asks or how its answer is read — `corpus.INSTRUMENT_FILES`, the
  six measuring modules of `tests/skill_router_eval/` plus
  `evals/providers/{_harness,claude_agent,claude_router}.py` and
  `evals/suites/skill-router.yaml`. `metrics.py` and `report.py` are
  deliberately absent: they derive numbers from ledgers already recorded and
  can be fixed and re-run without invalidating anything;
- each comparator's identity digest, and the verdict constants.

The replay and `select` refuse to start or resume (exit 2, nothing written)
when any re-derived value differs from the lock. A `SKILL.md`, an option
meaning, a threshold or a measuring module edited after the first cell
therefore voids the corpus; the remedy is a new version directory (`v2/`),
never a re-freeze of a measured one. Model overrides (`FZ_EVAL_MODEL`,
`FZ_EVAL_SANDBOX`) are refused rather than obeyed.

## The selection gate

The selection is a workflow defined inside the instrument
(`tests/skill_router_eval/selection.py`): `intake → Gate("select") →` one stub
step per option `→ END`. Its decision is
`ChoiceDecision(field="skill", accept_at=0.70, min_margin=0.10,
fallback=None)` over the five options, through the unchanged
`DecisionProvider` seam.

Each cell ends in one of three outcomes:

- **accepted skill** — the gate took a skill;
- **accepted `none`** — the gate took `none`;
- **escalated** — the gate blocked, because the proposal was below the
  thresholds, the provider failed, or no distribution came back.

There is no fallback option. Downstream, an escalated selection runs the
native configuration, so a refused proposal costs exactly the baseline and
never loads a wrong skill.

## The comparators and the arms

Four comparators, registered as the gate's `decision` strategy where they are
gated, each seeing the same `ChoiceRequest` and nothing else
(`tests/skill_router_eval/comparators.py`):

- **hermetic** — Phase 3's `hermetic()` provider (Jev), unchanged.
- **frontier** — Phase 3's `FrontierRouter` over `codex exec`, unchanged; its
  schema and prompt are built from the five options.
- **deterministic** — a keyword table over `state`, written from the five
  meanings alone and committed before the corpus was drafted. The first match
  proposes its skill one-hot; no match proposes a uniform distribution, which
  the margin rule refuses, so the cell escalates.
- **native** — `evals/providers/claude_router.py`, loaded by path and called
  with a pinned config (model, three turns, tools, timeout, host sandbox). It
  is not a `DecisionProvider` and is not gated: it is measured for accuracy
  only, as the baseline every other number is read against.

Three downstream **arms**, one suite (`evals/suites/skill-router.yaml`), each a
`claude_agent.py` provider with a pinned model, a docker sandbox, and five
cases copied verbatim from the existing suites (two `functualize`, two
`functualize-app`, one `functualize-skill`):

- **`load-everything`** — all skills mounted and all four `SKILL.md` bodies
  appended to the system prompt;
- **`native`** — all skills mounted, nothing appended: today's behaviour;
- **`router`** — the case's selection is read from the file named by
  `FZ_SKILL_ROUTER_SELECTIONS`. An accepted skill mounts only that skill and
  appends its `SKILL.md`; an accepted `none` mounts and appends nothing; an
  escalated selection runs the native configuration. A case missing from the
  file is a provider error, never a silent native run.

The router's selection is made **once per task** by `select`, with the
hermetic comparator, and every repeat of that task uses it. Selection variance
is measured on the corpus, not downstream.

## Running it

All commands run from the repository root. Outputs go under
`~/.local/state/functualize-skill-router-eval/` — never into the repository;
`select` refuses an output path inside it.

```bash
# 1. Routing: one run directory per comparator. Re-invoke the same command
#    with the same --run-dir until it prints "run complete".
uv run python -m tests.skill_router_eval.replay --corpus v1 \
  --comparator hermetic --run-dir "$STATE/v1-hermetic" </dev/null
# … and the same for frontier, deterministic and native.

# 2. Selections for the router arm.
uv run python -m tests.skill_router_eval.select \
  --tasks evals/suites/skill-router.yaml --out "$STATE/v1-selections.json" </dev/null

# 3. Downstream: one call per arm, each writing its own results file.
cd evals && FZ_SKILL_ROUTER_SELECTIONS="$STATE/v1-selections.json" \
  npx promptfoo eval -c suites/skill-router.yaml --no-cache --repeat 3 \
  --filter-providers router -o "$STATE/v1-downstream-router.json"

# 4. The report, then its byte-for-byte check.
uv run python -m tests.skill_router_eval.report \
  --run-dir "$STATE/v1-hermetic" --run-dir "$STATE/v1-frontier" \
  --run-dir "$STATE/v1-deterministic" --run-dir "$STATE/v1-native" \
  --selections "$STATE/v1-selections.json" \
  --downstream "$STATE/v1-downstream.json" --out "$STATE/v1-report"
uv run python -m tests.skill_router_eval.report … --check "$STATE/v1-report"
```

What the commands expect and how they stop:

- **The replay is chunked and resumable.** Each invocation runs until its
  `--budget-seconds` and prints `budget reached; next cell <n>` — a normal
  pause, not a failure. A rate-limited provider pauses it with
  `resume after <UTC>`: stop that comparator and resume after that time. Exit
  3 (an invalid model) voids the run. A completed comparator is never re-run to
  improve its numbers, and the lock's time box closes a run that has not
  finished in time, recording the rest as not attempted.
- **Close stdin.** A cell the gate escalates can reach an interactive prompt;
  with stdin left open the invocation waits forever. Run the replay and
  `select` with `</dev/null`.
- **Credentials.** The native comparator and the downstream arms run the
  `claude` CLI under the evaluation credential (`cd evals && npm run doctor`
  must pass, docker mode for the arms); frontier needs the maintainer's Codex
  login; hermetic needs the Jev credential. None is read by any offline test.
- **One downstream file.** `--downstream` takes one promptfoo results
  document holding every arm. Per-arm files are combined by concatenating
  their run lists — each entry keeps its own `output.arm` — never by
  re-running the suite. The report reads arms from each entry, never from
  promptfoo's `stats`.
- **Report exits.** `0` when it wrote (or, with `--check`, reproduced) the
  four files `finding.md`, `benchmark.md`, `metrics.json` and `verdict.json`;
  `2` when the inputs disagree — run directories whose headers name different
  corpora, catalogs, instruments, rule digests or commits, selections from a
  different instrument, or more than one observed model; `4` when conformance
  fails (below).

The four ledgers and the selections must come from one commit, instrument and
rule; the report checks their headers against each other.

## The measurements

Computed by `tests/skill_router_eval/metrics.py` from the ledgers, per
comparator, overall and per stratum. Generic functions are imported from
Phase 3 where they already were generic.

- **Selection accuracy.** Routed accuracy is the share of cells whose selected
  outcome equals the expected option, over every cell, so escalated and failed
  cells count as wrong. Also: a 5×6 confusion matrix (five options plus
  `escalated`), the proposed confusion with a `failed` column, per-option
  precision and recall, and macro-F1. Native reports accuracy, confusion and
  macro-F1 only.
- **The four selection errors**, counted separately at every sweep point:
  **wrong skill** (a skill accepted, another expected); **unsafe none**
  (`none` accepted while a skill was expected — blocking in the verdict);
  **over-load** (a skill accepted while `none` was expected); **false
  escalation** (escalated although the proposal was right — benign, it costs
  the native baseline).
- **Coverage and selective accuracy** — the share of cells accepted, and the
  accuracy of those.
- **Calibration, variance, agreement, latency, cost** — as Phase 3: ten-bin
  calibration and a five-option Brier score; modal agreement and flips per
  scenario; Cohen's κ between every pair of comparators; latency p50/p95/max.
  Cost is tokens for frontier and hermetic; native dollars are the
  instrument's own sum of the provider's reported `cost_usd`, never a token
  price.
- **Threshold sweep and conformance.** Recomputed offline over the
  `accept_at` × `min_margin` grid with no provider call, a failed cell
  counting as escalated. At the declared point the offline rule must
  reproduce every gated cell's recorded outcome, or the report exits 4.
- **Context before the first turn (E3, corpus half).** For every gated cell,
  the bytes the agent would hold before its first task turn: native, the four
  descriptions; load-everything, those plus every skill file; router, the
  accepted skill's `SKILL.md` and description, nothing for `none`, or the
  native listing when escalated. The headline is the router's **ratio to
  native**; load-everything is shown beside it, never as the headline.
- **Downstream (E3 tokens, E4 success).** Per arm: success over its runs with a
  95 % Wilson interval, the router-minus-native difference, mean and p95
  first-turn input tokens, mean cost, turns and duration, and the mean number
  of skills the agent loaded through its own `Skill` tool (an empty list is a
  measured zero).

## The verdict rule

The constants are fixed in the lock before the first cell — `min_lead` and
`max_unsafe_none` — and the verdict is computed by rule from the hermetic
comparator at the declared point:

- **negative result** — hermetic routed accuracy is below the deterministic
  comparator's plus `min_lead` (E2): a model-backed selection that is no better
  than a keyword table is not worth promoting;
- **promote to Phase 5** — E2 holds, the hermetic unsafe-`none` count is at
  most `max_unsafe_none`, the router's context is below native's (E3), and
  router downstream success is at least native's (E4, point estimates, with
  the intervals printed beside them);
- **continue research** — otherwise, naming every condition that failed.

The verdict is a recommendation; the disposition is the maintainer's. The
corpus `v1` result, with its provenance block, ledgers, selections and
downstream results attached, is the page
[Skill Router — Corpus v1 Results](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/26542082).

## What it does not measure

- **Two-skill requests.** The label set is single-skill; requests that need
  two skills are listed in `TWO_SKILL.md`, not scored.
- **Downstream effect for every option.** The five downstream cases cover
  `functualize`, `functualize-app` and `functualize-skill`. No suite exists for
  `functualize-cli`, and a `none` task has nothing for a skill to improve, so
  E4 says nothing about those two options.
- **Selection variance downstream.** The router arm uses one selection per
  task; variance is measured on the corpus only.
- **Any production change.** No file under `src/functualize/**`, `plugins/**`
  or `examples/` moves; the selection workflow lives in the instrument.
- **Anything over the network, in CI.** No offline test makes a network call
  or spawns a process; the replay, `select` and the downstream suite are
  commands, never collected by pytest.
- **A decision.** The verdict is computed by rule; the disposition is the
  maintainer's.
- **A universal answer.** It speaks for one catalog, one corpus version and
  one pinned agent model; five repeats bound the routing variance it reports,
  and three repeats of five tasks give wide downstream intervals.

## Extending to a third question

Phase 3 (`tests/hermetic_eval/`) and Phase 4 (`tests/skill_router_eval/`) ask
two questions with the same shape: a frozen labelled corpus, a gate over a
fixed option set, comparators behind `DecisionProvider`, a chunked resumable
replay, an offline sweep, and a report with a rule-computed verdict. Phase 4
**imports** what Phase 3 already had in generic form and **duplicates** the
rest — the replay loop (header, chunking, rate-limit pause, time box, resume),
the option-count-specific confusion, calibration and sweep, and the report
renderer — rather than editing a frozen, published instrument. That
duplication is accepted on purpose (rule of three): two instances do not yet
show which parts vary.

A **third question** is the moment to extract a shared `Question` abstraction,
and this is where it lands:

- **What a `Question` declares** — its options and their meanings, its
  fallback (`human_review` in Phase 3, none in Phase 4), its label rubric, its
  comparators, its error taxonomy (false-continue/stop versus the four
  selection errors) and its verdict rule.
- **What becomes shared** — the lock and freeze (corpus, catalog-like option
  source, rule digest, instrument digest, identities), the replay loop and its
  ledger header, the confusion/calibration/sweep functions parameterised by
  the option list, the conformance check, and the report's provenance block
  and file set.
- **What stays per question** — the corpus and rubric, the comparator
  adapters, any downstream suite, and the verdict constants.

The extraction must leave both existing instruments' frozen digests and
published results re-derivable: it either keeps their instrument files
byte-identical or lands as a new instrument that the two old ones are not
migrated into.
