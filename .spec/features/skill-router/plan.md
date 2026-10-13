# skill-router — plan

**Drafted 2026-10-13, awaiting the maintainer's confirmation**, together with
`spec.md`. Authored against `36eaeabf` (`origin/master`, re-fetched
2026-10-13). **Revised 2026-10-13** after the package review of `d34b70d3`:
the Plan 3a retrieval was re-run with all three tools on the committed region
at `d34b70d3`, and its evidence changed the native adapter, the cost row and the
freeze (record and *Iteration* below). Shape SD/16515075 was re-read live for
this revision: still version 3, `Authority: Approved`, updated
2026-10-13T07:57:49Z.

## Alignment

Shape intent: **[SD/16515075](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/16515075)**,
*Shape Intent — Skill Router: Pre-Context Skill Selection from a Bounded
Catalog (Phase 4)*, version 3, `Authority: Approved`, `Status: Approved`, last
reviewed 2026-10-13. Read live on 2026-10-13. The issue property `Shape intent`
points at it, and `Shape state = approved`.

**In scope**, in the shape's own words:

- "`tests/skill_router_eval/`: a new contributor instrument that holds the
  catalog declaration, the corpus, the selection workflow, the comparators,
  replay and report. It reuses `tests/hermetic_eval/` parts where they are
  already generic over `ChoiceRequest`". This plan covers tasks T1–T4, T6 and
  T8. The reused parts are listed in `contracts.md`.
- "`evals/`: one downstream suite and the harness option it needs to mount a
  chosen subset of skills, or to inline all bodies. This is contributor tooling,
  on demand, never in CI". This plan covers T2 (`skill-router.yaml`, C-10,
  C-11). Its offline test, `tests/evals/test_skill_router_arms.py`, sits beside
  the existing `tests/evals/test_suite_contracts.py`, which is where tests of
  `evals/` already live. It is the test half of that same surface, not a new
  one.
- "`contributor/reference/`: one reference page for the method, the durable
  half, like `hermetic-evaluation.md`". This plan covers T13
  (`skill-router-evaluation.md`).
- "The catalog declaration: name, description and content digest of each
  shipped skill, derived from `skills/` at freeze time". This plan covers T1
  (C-1).
- "Measured evidence: delivered on the tracker and on one Confluence page,
  never committed (Phase 3 rule)". This plan covers T11 and T12.

**Out of scope**, in the shape's own words:

- "`skills/**`: no edit to any shipped skill, its frontmatter or its text. The
  catalog is *read* from it (D0)". AC-15 checks this.
- "`src/functualize/**` **and** `plugins/**`: no change. In particular the
  decision seam is not widened (D1)". AC-15 and AC-17 check this.
- "`examples/`, `docs/`, the public API, the CLI: nothing user-visible.
  Publishing is Phase 5, under its own Shape intent (D0)". AC-15 checks this.
- "A self-growing or user-extensible catalog. More than the four shipped skills
  plus `none` would break the scope guard". B-2 and AC-1 check this.
- "Any claim of general intelligence, any model gateway, any provider
  registry". B-28 covers this.

Behaviour the shape says must **not** change: "what `func builtin skills`
installs, what the wheel carries, the six-field frontmatter rule, the decision
seam and ADR-030's rule that a provider proposes and the gate decides". No
`skills/`, `src/` or packaging file is touched (AC-15), and every selection
passes through `DecisionGateResolver` and the gate (B-6).

How the shape's decisions land:

- **D0**: everything lives in `tests/` + `evals/`.
- **D1**: there are five options and one `ChoiceRequest` (B-6).
- **D2**: three arms, with native as the headline (B-18, B-23).
- **D3**: five tasks × three arms × three repeats = 45 runs (B-19, B-20).
- **D4**: no fallback, and an escalated cell runs native (B-7).
- **D5**: 40 scenarios, 8 per option, 5 `clear` + 3 `borderline`, seeded from
  `triggering.yaml`, with the catalog digest in the lock (B-3–B-5). The owner
  later waived label review.
- **D6**: hermetic, frontier and keyword comparators through the gate, plus
  native for accuracy only (B-8).
- **E1–E4**: each maps to B-10, B-24 (E2), B-18 + B-22 (E3) and B-23 (E4).

**One addition the shape did not name**, disclosed rather than slipped in:
`tests/hermetic_eval/**` is listed as **unchanged** (B-29). The shape says the
new instrument "reuses" its generic parts. This plan reads "reuse" as *import*,
never *edit*. Editing them would change a frozen instrument whose published
results (SD/13959170) must stay re-derivable. The cost of that reading is S-1
below.

## Retrieval record

Re-run 2026-10-13 on the committed region at `d34b70d3` (the previous record
skipped serena and relied on a graph 55 commits stale; it is replaced, not
amended).

| pass | tool | what it answered |
|---|---|---|
| prior art | **zvec-grep**: `zg query --mode direct` (CLI at `/usr/local/bin/zg`; the MCP server refused the connection), worktree index root `~/orca/workspaces/functualize/sdd-skill-router`, `zg status` 868/868 files, 0 pending | Unchanged from the first pass: `skills/functualize-skill/SKILL.md:84-93`, ADR-006 §5, ADR-030 §Decision, ADR-009, `evals/README.md` § *Relationship to `tests/skills/`*. **New**: `contributor/reference/hermetic-evaluation.md:34-68` — Phase 3's own method says "changing … a comparator's model, prompt, schema or rule table needs a new corpus version", which this package's first lock did not enforce (finding 3). `evals/README.md:330-356` — `FZ_EVAL_SANDBOX` "beats the `sandbox:` key in a suite, in both directions"; the same precedence holds for `FZ_EVAL_MODEL` (`claude_router.py:69`, `claude_agent.py:103`). `evals/README.md:608-620` — the routing probe "stops the agent after its first step", the basis for treating a turn-budget stop as a selection, not a failure. ADR-030 §Addendum — the fallback is "fenced by the graph digest like the rest of the rule" |
| premises | `rg`, `find`, `wc`, frontmatter parse, `claude --help`, `ls`, file reads | F-1…F-17 in `spec.md` §1.1. Unmeasured, each step 0 of its task: per-message `usage`, the `init` event's `model` and the turn-budget `result` subtype (F-8, F-10 → T2); Jev's acceptance of 2.5 kB of option meanings (F-14 → T5) |
| 3a shape | **serena** (project activated by absolute path `~/orca/workspaces/functualize/sdd-skill-router`): `get_symbols_overview` on `tests/hermetic_eval/metrics.py` and `evals/providers/claude_router.py`; `find_referencing_symbols` on `metrics.cost`, `claude_router.call_api`, `app._decision_record.decision_record` | `metrics.cost` is referenced by `report._block` and one test only, and its body prices nothing (F-15). `claude_router.call_api` has **no Python referrer**: promptfoo loads it by file, and `rg -n claude_router` finds one consumer, `triggering.yaml:23`, so adding an output key reaches no other code. `decision_record` is public through `app/utils.py:122,222`, and Phase 3's `replay_cell` already reads the rule digest from it (`replay.py:290`, F-16) |
| 3a shape | **graphify**: the committed `graphify-out/graph.json` was built at `2269b8d3`, 55 commits behind `d34b70d3` (`git log --oneline 2269b8d3..d34b70d3 \| wc -l`), **and** `.graphifyignore` excludes `tests/` and `evals/` by design, so no rebuild of the committed graph can see this region. Two graphs were therefore built with `graphify extract --code-only` from `git archive d34b70d3` exports outside the checkout (the committed graph is untouched): the configured product scope (10 303 nodes), and a region scope of `src/` + `tests/hermetic_eval/` + `evals/providers/` with the `tests/`/`evals/` exclusions dropped (10 094 nodes, 21 243 edges). `graphify explain` on the region graph | Dependency direction, now from extracted edges instead of an import scan: `claude_router.call_api → build_workspace, resolve_sandbox_mode, run_claude`, with no inbound edge; `run_claude ←` the three providers' `call_api`; `_absorb ← run_claude` only; `metrics.cost ← report._block` + its test; `check_lock ← replay.main` + six tests; `FrontierRouter ← replay._default_factories` + tests; `decision_record ← tests/hermetic_eval/replay.replay_cell` (INFERRED). Product graph: `decision_digest ← build_decision_evidence` only, inside `functualize._gate`, so the instrument reads the digest from evidence, never imports it. Nothing outside `tests/hermetic_eval/` points into it (same answer as the earlier `rg -l 'from tests\.hermetic_eval' tests`: 9 files, all inside the package) |
| 3b blast radius | `rg`, `git diff`, serena references above | Product symbols touched: **0**. `evals/providers/_harness.py` gains keyword-only parameters with defaults and one `AgentRun` field; its callers are `claude_agent.py`, `claude_router.py`, `claude_grader.py` and `evals/scripts/{doctor,preflight,case}.py` (`rg -l _harness`). None passes the new keywords, so all keep today's argv (AC-11). `claude_router.py` gains one output key (`model`); its only consumer's grader reads `selected`/`skills_loaded`/`any_fired` (`evals/asserts/skill_selected.py`) |

Codemaps (`contributor/architecture/codemaps/`) describe `src/` only. As in
Phase 3, an instrument outside the package graph adds no codemap node.

## Skills consulted

- `python-design-patterns` (in-repo): KISS, single responsibility. Metrics stay
  pure functions over ledger rows, and the catalog, selection, replay and
  report are one module each.
- `design-patterns-refactoring` (user-level, Refactoring.Guru catalogue): the
  *Strategy* pattern (comparators behind the existing `DecisionProvider`), the
  *Adapter* pattern (native routing over a promptfoo provider), and the smell
  names *Duplicate Code*, *Inappropriate Intimacy*, *Speculative Generality*,
  *Divergent Change* and *Shotgun Surgery*.

## BEFORE

```
          PRODUCT (import-linter governs this box only) — not touched by this feature
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │ functualize.workflow (ChoiceDecision, Gate)   functualize.plugin (DecisionProvider,
   │ functualize.app / app.utils (FunctualizeApp,      DecisionGateResolver, ChoiceRequest)
   │   decision_record, ScopeStore)                functualize.types (RunRequest, RunStatus)
   └──────▲───────────────────────────────────────────────────────▲───────────────┘
          │ public API only                                       │
 tests/hermetic_eval/  (Phase 3, frozen v1, results published SD/13959170)
   corpus.py (ROUTES) ◀── metrics.py ◀── report.py
        ▲                    ▲
   replay.py ── by path ──▶ examples/standalone/hermetic_router/router.py (4 routes, fallback=human_review)
             row.rule_digest ◀── decision_record(...)["evidence"]["rule"]["digest"]  (one digest per ledger, tested)
   metrics.cost: tokens only; usd_total = None if frontier else 0.0 — prices nothing
   comparators.py: identity_sha256 · hermetic() ─lazy─▶ functualize_decision_jev
                   FrontierRouter ─subprocess─▶ codex exec   ·   DeterministicBaseline (route RULES)

 skills/{functualize,-app,-cli,-skill}/  (shipped in the wheel; 13 files, 110 855 B)
        │ copied whole (all or none)
 evals/providers/_harness.py ◀── claude_agent.py  (with_skills: true|false)
                             ◀── claude_router.py (native routing; triggering.yaml, 21 cases)
        claude_router.call_api → {"error"} on setup | {"output": {selected, error, …}, "cost"} on a run
        model = $FZ_EVAL_MODEL or config · max_turns = config or 4 · sandbox = $FZ_EVAL_SANDBOX or config or host
   AgentRun: turns, cost, skills_loaded — no token usage, no model (init event only logged)

 nothing selects a skill before the agent starts · nothing mounts one skill ·
 nothing measures context size
```

Smells the BEFORE already carries in this region:

- **Duplicate Code, latent**: the Phase 3 instrument mixes four-route
  vocabulary into otherwise generic modules (`metrics._brier` sums over
  `ROUTES`, and `escalation` hard-codes `human_review`). Any second question
  must either copy the module or edit a frozen one. This is the root of S-1.
- **Missing measurement, not a catalogue smell**: the harness cannot mount a
  subset of skills or report context tokens (F-9).
- **Configuration in two places, not a catalogue smell**: the native probe's
  model, sandbox and turn budget come from env, then suite config, then a
  code default (4 turns), so the provider file alone does not say which call
  is made (F-8). A consumer that does not pass the config, or runs with the
  env set, measures a different question.

## Candidate AFTERs considered

| | shape | introduced smells / costs | verdict |
|---|---|---|---|
| **A** | Generalise `tests/hermetic_eval/` over a `Question` (options, fallback, labels) and run Phase 4 as a second question inside it | Edits a frozen, published instrument: the Phase 3 lock's comparator identities and conformance must stay re-derivable, and its 1 842 test lines would be rewritten (**Shotgun Surgery** across five modules). It goes beyond the shape's in-scope list ("reuses … where they are already generic") | rejected |
| **B** | A promptfoo-only Phase 4: routing via `claude_router`-style providers for every comparator | Proposals would never pass through the gate, which contradicts "a skill selection is a candidate … decided by a gate". There is no distribution, calibration or sweep (**Divergent Change** in `evals/`) | rejected |
| **C** | Live selection inside the `router` arm's promptfoo provider | Couples `evals/` (promptfoo's Python) to `functualize` + the Jev plugin + credentials. Selection variance would also be confounded with agent variance across repeats | rejected; replaced by a separate `select` command and `selections.json` (B-21) |
| **D (chosen)** | A new `tests/skill_router_eval/` that **imports** Phase 3's generic parts and owns its five-option parts. The selection workflow is defined in the instrument with `fallback=None`. Native routing is adapted by path from `evals/providers/claude_router.py`. `evals/` gains keyword-only harness options plus one suite | S-1, S-2, S-3, S-4 below | chosen |

Iteration that changed the spec:

1. The first draft re-used Phase 3's `calibration()` whole. Reading `_brier`
   showed it sums over the four Phase 3 routes, which gives a silently wrong
   five-option Brier score. B-15 now owns a five-option calibration.
2. The first draft let the router arm select live per repeat (candidate C).
   Drawing D showed that confounds selection and agent variance, which is what
   produced B-21.
3. The first draft used Phase 3's escalation metric. With no fallback, "needed
   escalation" has no `human_review` label to key on. B-13 replaces it with the
   four selection errors, unsafe `none` among them.

Iteration from the package review and the re-run retrieval (no change of
candidate; D stays, and its dependency direction is unchanged):

4. **The native adapter read a shape the provider does not return.** The
   graph shows `claude_router.call_api`'s only outputs are a setup `{"error"}`
   and the `{"output", "cost"}` envelope, and serena shows no Python caller to
   copy a reading from. B-8 now states the envelope rules, both error
   locations and cost, and C-5 makes `NATIVE_CONFIG` the single source of the
   call and of the identity, so the provider's 4-turn default never applies.
5. **Phase 3's `cost` cannot price a native cell** (serena: one caller, body
   reads no price). B-16 gives native its own `native_cost`; `cost` stays for
   tokens. The AFTER now shows that ownership.
6. **The freeze fenced the corpus, not the question.** Prior art
   (`hermetic-evaluation.md:34-68`) already counts prompt and rule as part of
   the question; the graph shows the rule digest is produced only inside
   `functualize._gate`, so the AFTER reads it from evidence (as Phase 3 does)
   and pins it in the lock via a keyword-comparator probe, plus a file digest
   over the measuring code. Env overrides that change the native model or
   sandbox are refused, and the observed model is recorded and checked.
7. Editorial: T-number references for the stream probe and the `evals/`
   harness corrected to T2.

## AFTER

```
   ┌──────────── PRODUCT — unchanged (AC-15: 0 files in skills/ src/ plugins/ examples/ docs/) ───────────┐
   │ functualize.workflow  functualize.app(.utils)  functualize.plugin  functualize.types                 │
   └──────▲──────────────────────▲───────────────────────▲──────────────────▲──────────────────────────────┘
          │ public API only (AC-16)
 tests/skill_router_eval/   (instrument; pytest collects test_*.py only, all offline — B-30)
   catalog.py ── reads ──▶ skills/*/  (never writes; exactly 4 dirs or CatalogError)
   corpus.py  ── corpus/v1/{scenarios.jsonl, LABELING.md, corpus.lock.json}
   selection.py  SELECT = ChoiceDecision(5 options, 0.70/0.10, fallback=None) · build_selection · select()
   comparators.py  KeywordTable (Strategy, no I/O) · NativeRouter (Adapter) ── by path ──▶ evals/providers/claude_router.py
                     NativeRouter: NATIVE_CONFIG (model, max_turns 3, timeout, sandbox) passed on every call;
                     refuses FZ_EVAL_MODEL/FZ_EVAL_SANDBOX overrides; unwraps {"output", "cost"} / top-level {"error"}
                   re-exports hermetic(), FrontierRouter ◀── import ── tests/hermetic_eval/comparators.py (UNCHANGED)
   replay.py  (command) --freeze / start / resume: check_lock(scenarios, catalog, selection rule_digest,
              instrument sha256, identities) ── rule probe: select(PROBE_STATE, KeywordTable)
              per cell: fresh app → build_selection → DecisionGateResolver(cmp) → execute
              → decision_record → row (rule_digest == lock, else exit 2) → <run-dir>/cells.jsonl
              (native: NativeRouter.select → row.native {selected, error, model, cost_usd})
   select.py  (command) same check_lock · 5 task prompts → hermetic → selections.json (outside the repo)
   metrics.py five-option metrics + static context bytes + native_cost ── imports ──▶ tests/hermetic_eval/metrics.py
              (accepts, agreement, variance, latency, cost[tokens only] — UNCHANGED)
   report.py  (command) 4 ledgers + selections + promptfoo results ──▶ benchmark.md finding.md metrics.json verdict.json
              exit 2 on a foreign/mixed rule_digest or a mixed observed model
   corpus/v1/corpus.lock.json  pins the question: scenarios · catalog · selection rule (+ gate rule_digest)
              · instrument sha256 (10 measuring files) · comparator identities (native config) · verdict constants

 evals/providers/_harness.py   build_workspace(…, skills=) · run_claude(…, append_system_prompt=) · AgentRun.first_turn_input_tokens, .model
 evals/providers/claude_router.py  output gains "model" (one key; triggering.yaml's grader ignores it)
 evals/providers/claude_agent.py   config arm ∈ {load-everything, native, router}; router ◀── $FZ_SKILL_ROUTER_SELECTIONS
                                   with arm set: env model/sandbox override refused; output gains "model"
 evals/suites/skill-router.yaml    d1…d5 (copied cases) × 3 arms × --repeat 3
 tests/evals/test_skill_router_arms.py   offline harness tests (fake Sandbox.popen)

 contributor/reference/skill-router-evaluation.md (method, no numbers)    .spec/STATUS.md (entry)
```

Dependency direction: `tests.skill_router_eval → tests.hermetic_eval` (one
way; nothing in Phase 3 learns about Phase 4), and `tests.skill_router_eval →
evals/providers/claude_router.py` by file path. Every import-linter contract in
`pyproject.toml` names `functualize.*` modules only, so none applies to either
tree. `uv run lint-imports` stays in every task's checks.

## Decisions taken in this plan (designer; open to the maintainer at confirmation)

- **P-1 — the downstream tasks** (`spec.md` B-19, shape D3 asks the owner to
  approve the list): `d1`–`d5`, two each for `functualize` and
  `functualize-app` and one for `functualize-skill`. All are graded by
  deterministic asserts only.
- **P-2 — the verdict constants** (B-24): `min_lead = 0.05`,
  `max_unsafe_none = 0`. They are frozen in the lock.
- **P-3 — one selection per downstream task** (B-21), not one per repeat.
- **P-4 — S-1 accepted as Duplicate Code** rather than editing Phase 3. This is
  flagged for review below.

## Risks

- **R-1 — Jev and long option meanings (F-14).** The five meanings total about
  2.5 kB, versus Phase 3's four one-line meanings. If T3 step 0 shows Jev
  refusing or truncating them, the catalog meanings are shortened **in the
  instrument only** (a first-sentence cut, declared in C-1, digested in the
  lock), and the finding says so. `skills/` is never edited.
- **R-2 — per-message usage may be absent from claude's stream (F-10).** In that
  case `first_turn_input_tokens` is `null`, and E3 rests on bytes alone (B-22).
- **R-3 — the inlined body and the `Skill` tool overlap.** In the router and
  load-everything arms the agent may still call `Skill` on a mounted skill
  whose body is already in context. That costs a turn and inflates the arm's
  tokens against itself, so it is conservative. `skills_loaded` is reported per
  arm.
- **R-4 — budgets.** Jev's free tier gives about 100 requests per burst and a
  window of about 5 h (capability matrix Row F). 200 hermetic cells plus 5
  selections need at least two windows. Codex usage limits cost frontier
  cells, as in Phase 3. The 45 downstream runs and 200 native cells are billed
  to the eval credential. The member approved 45 runs (D3), and T10 prints
  cumulative cost.
- **R-5 — small signal (shape Risk 3).** 15 runs per arm detect only a large
  effect, so the Wilson interval is printed beside every rate.
- **R-6 — drafter bias in labels.** The owner waived label review. A
  rubric-cited rationale per scenario and a reviewer check (T7) are the only
  guards, and the finding says so.
- **R-8 — the turn-budget subtype is unmeasured (F-8).** If T2 step 0 shows
  that a turn-budget stop is not reported as an error subtype at all, the
  `MAX_TURNS_SUBTYPE` row of C-5 never fires and nothing else changes. If it
  is reported under a different string, that string is recorded in C-5's
  constant before the freeze; it is pinned by the instrument digest.
- **R-9 — the instrument digest is file-coarse.** Any byte change to a pinned
  file after T10, a comment included, voids v1. That is deliberate (cheaper
  than arguing which edits are behavioural); T15 says a fix to a pinned file
  after the freeze is a stop-and-report, never an edited lock.
- **R-7 — `triggering.yaml` drift.** If a triggering case changes after the
  freeze, AC-2's seeded-label check fails loudly. The corpus stays frozen, and
  a v2 is cut.

## Surviving smells

| # | smell (catalogue name) | where | why accepted | maintainer review? |
|---|---|---|---|---|
| S-1 | **Duplicate Code**: the replay loop (header, chunking, rate-limit pause, time box, resume), the five-option confusion, calibration and sweep, and the report renderer parallel Phase 3's four-route versions | `tests/skill_router_eval/{replay,metrics,report}.py` vs `tests/hermetic_eval/{replay,metrics,report}.py` | The alternative (candidate A) edits a frozen, published instrument outside the shape's in-scope list. Only the parts already generic are imported (`contracts.md` header). Rule of three: a third question is the moment to extract a shared `Question`, and the reference page records that | **yes**: it fixes where the next refactor lands |
| S-2 | **Inappropriate Intimacy (mild)**: the instrument loads `evals/providers/claude_router.py` by path and knows its response envelope | `comparators.NativeRouter` | Native routing *is* that provider. Copying it would let the measured native arm drift from the one `triggering.yaml` runs. The envelope rules are written once (C-5) and tested against the provider's real shapes (AC-6); the file's digest is in the native identity and the instrument digest, so an edit voids the lock | no |
| S-3 | **Duplicate Code (pinned)**: five downstream cases copied verbatim from their source suites | `evals/suites/skill-router.yaml` | promptfoo cannot include individual tests from another suite file. AC-11 fails the build when a copy drifts from its source | no |
| S-4 | **Primitive Obsession**: ledger rows, selections and verdict as JSON mappings | `cells.jsonl`, `selections.json`, `verdict.json` | Same reason as Phase 3's S-2: an append-only interchange file, with its shape pinned by C-8/C-9 and the tests | no |

No *Forbidden Patterns* entry appears in the AFTER. No product module changes.
The instrument holds no module-level mutable state (provider instances own
their call lists), uses no ABC, and every port is the existing
`DecisionProvider` Protocol.
