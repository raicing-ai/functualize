# skill-router — plan

**Drafted 2026-10-13, awaiting the maintainer's confirmation**, together with
`spec.md`. Authored against `36eaeabf` (`origin/master`, re-fetched
2026-10-13).

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
  on demand, never in CI". This plan covers T5 (`skill-router.yaml`, C-10,
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

| pass | tool | what it answered |
|---|---|---|
| prior art | `zg query --mode direct` (worktree index, root `~/orca/workspaces/functualize/sdd-skill-router`) | `skills/functualize-skill/SKILL.md:84-93`: the description is the whole activation surface, so agents already load skills progressively. ADR-006 §5: frontmatter stays on the portable six fields. ADR-030 §Decision: one `Protocol`, one method, a provider proposes. ADR-009: skills ship in the distribution. `evals/README.md` § *Relationship to `tests/skills/`*: a rule decidable without a model belongs in pytest |
| premises | `rg`, `find`, `wc`, frontmatter parse, `claude --help`, `ls`, file reads | F-1…F-14 in `spec.md` §1.1. Two premises are **unmeasured** and become step 0 of their tasks: per-message `usage` in claude's stream (F-10 → T5) and Jev's acceptance of 2.5 kB of option meanings (F-14 → T3) |
| 3a shape | graphify (`graph_stats`, `get_neighbors`); `rg` import scan; function bodies read | graphify's graph was built at `2269b8d3`, **54 commits** behind HEAD. It has no node for `FrontierRouter` or anything under `tests/hermetic_eval/`, so dependency direction is read from imports instead: `tests/hermetic_eval/{replay,metrics,report}.py` import `tests.hermetic_eval.corpus`, and nothing outside that package imports it (`rg -l 'from tests\.hermetic_eval' tests` returns 9 files, all inside the package). serena was not used: the region is a test-tree instrument with no product symbol, and the reference questions were answered by that exhaustive `rg` |
| 3b blast radius | `rg`, `git diff` | Product symbols touched: **0**. `evals/providers/_harness.py` gains keyword-only parameters with defaults, and its callers are `claude_agent.py`, `claude_router.py`, `claude_grader.py` and `evals/scripts/{doctor,preflight,case}.py` (`rg -l _harness`). None passes the new keywords, so all keep today's argv (AC-11) |

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
   comparators.py: identity_sha256 · hermetic() ─lazy─▶ functualize_decision_jev
                   FrontierRouter ─subprocess─▶ codex exec   ·   DeterministicBaseline (route RULES)

 skills/{functualize,-app,-cli,-skill}/  (shipped in the wheel; 13 files, 110 855 B)
        │ copied whole (all or none)
 evals/providers/_harness.py ◀── claude_agent.py  (with_skills: true|false)
                             ◀── claude_router.py (native routing; triggering.yaml, 21 cases)
   AgentRun: turns, cost, skills_loaded — no token usage

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
                   re-exports hermetic(), FrontierRouter ◀── import ── tests/hermetic_eval/comparators.py (UNCHANGED)
   replay.py  (command) per cell: fresh app → build_selection → DecisionGateResolver(cmp) → execute
              → decision_record → <run-dir>/cells.jsonl     (native: NativeRouter.select → row)
   select.py  (command) 5 task prompts → hermetic → selections.json (outside the repo)
   metrics.py five-option metrics + static context bytes ── imports ──▶ tests/hermetic_eval/metrics.py
              (accepts, agreement, variance, latency, cost — UNCHANGED)
   report.py  (command) 4 ledgers + selections + promptfoo results ──▶ benchmark.md finding.md metrics.json verdict.json

 evals/providers/_harness.py   build_workspace(…, skills=) · run_claude(…, append_system_prompt=) · AgentRun.first_turn_input_tokens
 evals/providers/claude_agent.py   config arm ∈ {load-everything, native, router}; router ◀── $FZ_SKILL_ROUTER_SELECTIONS
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
- **R-7 — `triggering.yaml` drift.** If a triggering case changes after the
  freeze, AC-2's seeded-label check fails loudly. The corpus stays frozen, and
  a v2 is cut.

## Surviving smells

| # | smell (catalogue name) | where | why accepted | maintainer review? |
|---|---|---|---|---|
| S-1 | **Duplicate Code**: the replay loop (header, chunking, rate-limit pause, time box, resume), the five-option confusion, calibration and sweep, and the report renderer parallel Phase 3's four-route versions | `tests/skill_router_eval/{replay,metrics,report}.py` vs `tests/hermetic_eval/{replay,metrics,report}.py` | The alternative (candidate A) edits a frozen, published instrument outside the shape's in-scope list. Only the parts already generic are imported (`contracts.md` header). Rule of three: a third question is the moment to extract a shared `Question`, and the reference page records that | **yes**: it fixes where the next refactor lands |
| S-2 | **Inappropriate Intimacy (mild)**: the instrument loads `evals/providers/claude_router.py` by path | `comparators.NativeRouter` | Native routing *is* that provider. Copying it would let the measured native arm drift from the one `triggering.yaml` runs. Its file digest is in the native identity, so an edit voids the lock | no |
| S-3 | **Duplicate Code (pinned)**: five downstream cases copied verbatim from their source suites | `evals/suites/skill-router.yaml` | promptfoo cannot include individual tests from another suite file. AC-11 fails the build when a copy drifts from its source | no |
| S-4 | **Primitive Obsession**: ledger rows, selections and verdict as JSON mappings | `cells.jsonl`, `selections.json`, `verdict.json` | Same reason as Phase 3's S-2: an append-only interchange file, with its shape pinned by C-8/C-9 and the tests | no |

No *Forbidden Patterns* entry appears in the AFTER. No product module changes.
The instrument holds no module-level mutable state (provider instances own
their call lists), uses no ABC, and every port is the existing
`DecisionProvider` Protocol.
