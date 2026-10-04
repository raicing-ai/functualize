# hermetic-evaluation — plan

**Approved** — `spec.md` confirmed and D-1…D-7, S-1, S-4 answered by the maintainer on 2026-10-04.
Authored against `e8e3b867` (`origin/master`, observed 2026-10-04).

## Retrieval record

| pass | tool | what it answered |
|---|---|---|
| prior art | `zg query` (index built in this worktree: 1 061 files, 14 529 entities, 1 m 7 s) | `tests/jev_probe/` is the instrument precedent (module-level gates, numbers transcribed to a reference, never read by the product); `contributor/reference/jev-system-one-capability-matrix.md` rows C (argmax flips 9/20 on a near tie), D (cost is per request), F/Q2 (≈100-request burst, ≈5 h reset window); `evals/README.md` (live-model work is deliberately not pytest; `--repeat` because one run is noise) and `evals/providers/_harness.py::run_claude` (the repo already drives `claude -p` as a provider); ADR-030 (decisions are candidates; the resolver never names `confidence`); `.spec/STATUS.md` → *Still open after the hermetic router* (monetary cost is Phase 3's; margin comparison exact) |
| premises | `rg`, `test -e`, a scratch probe, three `curl` calls, one `claude -p` call, one `codex exec` call | F-1…F-14 in `spec.md` §1.1 — replay-in-process (F-1) and the frontier invocation (F-8) were found by running them, the unfunded paid tier (F-7) by asking it |
| 3a shape | serena (activated by absolute worktree path) `find_referencing_symbols(decision_record)`; graphify `get_neighbors` | `decision_record` is referenced from `app/utils.py` (re-export), the router example's tests, `tests/integration/test_decision_fallback_e2e.py`, `tests/workflow/test_decision_record.py` — a stable public reader to build on. **graphify is 40 commits stale** (`built_at_commit..HEAD`) and has no node for `DecisionGateResolver` or `decision_strategy.py`, so it could not answer dependency direction for the Phase 1/2 region; direction below is read from imports (`rg -n "^from functualize"`) instead |
| 3b blast radius | `rg`, serena | the AFTER changes **no product symbol**: `git diff --name-only origin/master -- src plugins` → 0 now and after (AC-13). The blast radius is the new directory plus two docs (`.spec/STATUS.md`, a new `contributor/reference/hermetic-evaluation.md`) |

Codemaps read: `overview.md`, `modules.md`, `dependencies.md`, `data-flow.md`,
`entry-points.md`. None mentions `tests/` instruments, `examples/` or `evals/`
(`rg -n "jev_probe|evals/|examples/" contributor/architecture/codemaps/` → no
match), which is consistent with this AFTER: an instrument outside the package
graph adds no node to the codemaps and needs no codemap edit.

## Skills consulted

- `python-design-patterns` (in-repo, `.claude/skills/python-design-patterns`):
  KISS, single responsibility, rule of three — the reason metrics are pure
  functions over ledger rows and the report is a separate module from the
  replay.
- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue,
  `cheatsheet.md`): *Strategy* (the comparators behind the existing
  `DecisionProvider` port), *Adapter* (the frontier comparator over a CLI),
  smell names *Duplicate Code*, *Primitive Obsession*, *Divergent Change*,
  *Shotgun Surgery*, *Speculative Generality*, *Inappropriate Intimacy*.

## BEFORE

```
                                      PRODUCT (import-linter governs this box only)
            ┌────────────────────────────────────────────────────────────────────────────┐
 public     │ functualize.workflow   functualize.app / app.utils    functualize.plugin   │
            │  ChoiceDecision, Gate   FunctualizeApp, decision_record  DecisionProvider,  │
            │                         ScopeStore, execute             DecisionGateResolver│
            │        │                      │                               │            │
 internal   │        ▼                      ▼                               ▼            │
            │  _types/decision.py ◀── _gate/decision_strategy.py ──▶ _gate/decision_evidence.py
            │                         (rule: p>=accept_at ∧ margin>=min_margin)          │
            └────────▲──────────────────────▲───────────────────────────────▲────────────┘
                     │ public API only      │                               │ public API
   examples/standalone/hermetic_router/     │                plugins/domains/functualize-decision-jev
     router.py  ROUTER, build_router ───────┘                  JevDecisionProvider ──HTTP──▶ opencode zen
     tests/test_router.py (FakeProvider)                         (free tier; F-5)
                                                                          ▲
   tests/jev_probe/   ── raw HTTP, never imports functualize ─────────────┘   (row-by-row matrix)
   evals/ (promptfoo, node) ── claude -p ──▶ Claude (skill evals; not pytest)

   nothing replays a corpus · nothing compares providers · nothing computes cost in $
```

Smells the BEFORE carries, relevant to this region:

- **Missing measurement, not a catalogue smell** — the router can only be
  exercised one hand-written case at a time (`test_router.py`); stated plainly
  rather than given a catalogue-shaped name.
- **Primitive Obsession, pre-existing and accepted** — decision evidence is a
  JSON mapping (`decision-evidence/1`); Phase 2's S-2. This plan consumes it as
  is.
- None introduced into `src/` by this feature, because this feature does not
  touch `src/`.

## Candidate AFTERs considered

| | where the evaluation lives | how comparators plug in | introduced smells / costs | verdict |
|---|---|---|---|---|
| **A** | a product module (`functualize.workflow.evaluate`, an `EvaluationContract` type) | a new evaluator registry | a public surface and a new primitive for one experiment — **Speculative Generality**; breaks the guard *no new authority primitive*; needs a Shape intent page | rejected |
| **B** | a promptfoo suite in `evals/` | promptfoo providers | promptfoo takes the cross-product of providers × tests (`evals/README.md`); node toolchain; a provider there cannot run inside the Python gate, so it would measure **proposals without the gate** — the opposite of the phase; mixes a routing benchmark into the skills-eval tree (**Divergent Change**) | rejected |
| **C** | `examples/standalone/hermetic_router/evaluation/` | `DecisionProvider` + `DecisionGateResolver` | user-visible (examples are user documentation) ⇒ Shape intent gate; puts a model-CLI subprocess beside a README whose claim is "no model client" (**Inappropriate Intimacy** with the example's promise); collected by the `examples` CI job | viable, not recommended (D-1) |
| **D (chosen)** | `tests/hermetic_eval/`, an instrument like `tests/jev_probe/` | the existing `DecisionProvider` port (**Strategy**) registered through `DecisionGateResolver`, so the real gate decides every cell | offline rule restated for the sweep (S-1); JSON ledger rows (S-2); router loaded by file path (S-3); a CLI's JSON as a contract (S-4) | chosen |
| **E** | as D, but the sweep re-drives the real gate with a replay provider per threshold | — | 50 points × 600 cells × ≈0.25 s (F-1) ≈ 2 h per report, far past one tool call | rejected; replaced by D's offline rule **plus** a conformance check at the declared point (spec B-20, AC-9) |

Iteration that changed the spec: (1) the first draft let `min_support` count
cells; drawing D showed support inflated by repeats of one scenario, so B-21
now also requires 4 distinct scenarios. (2) The first draft placed the
instrument under `examples/` (C); checking it against `AGENTS.md`'s shape-intent
rule showed that would make it user-visible and stop the spec, which is what
moved it to `tests/` and made the location a member decision (D-1).

## AFTER

```
            ┌───────────────── PRODUCT — unchanged (AC-13: 0 files in src/ plugins/) ─────────────────┐
 public     │ functualize.workflow     functualize.app / app.utils      functualize.plugin   functualize.types
            │  ChoiceDecision           FunctualizeApp, ScopeStore,       DecisionProvider,     RunRequest
            │                           decision_record                   DecisionGateResolver,
            │                                                             DecisionResult, …    │
            └───────▲───────────────────────────▲───────────────────────────▲─────────────▲────┘
                    │ public API only (AC-15)   │                           │             │
 tests/hermetic_eval/  (instrument; root pytest collects only test_*.py, all offline — B-28)
   corpus.py ── load · validate · sha256 · lock check ◀── corpus/v1/{scenarios.jsonl, LABELING.md, corpus.lock.json}
   _router.py ── importlib by path ──▶ examples/standalone/hermetic_router/router.py  (ROUTER, build_router; unchanged)
   comparators.py   (Strategy: three DecisionProviders, one identity() each)
     DeterministicBaseline  RULES regex table          (no I/O)
     hermetic()  ── lazy import ──▶ functualize_decision_jev.JevDecisionProvider ──HTTP──▶ zen free tier
     FrontierRouter (Adapter) ── subprocess (the only one) ──▶ `codex exec … -m gpt-6-astra`
   replay.py  (command)  per cell: fresh FunctualizeApp → build_router → register DecisionGateResolver(cmp)
                          → app.execute → decision_record → one line to <run-dir>/cells.jsonl
                          <run-dir> = $XDG_STATE_HOME/functualize-hermetic-eval/<run-id>/  (outside the repo)
   metrics.py (pure functions over ledger rows; offline rule for the sweep — S-1)
   report.py  (command) ledgers ×3 + lock ──▶ <out>/{benchmark.md, finding.md, metrics.json, boundary.json}
   test_corpus.py · test_comparators.py · test_replay.py · test_metrics.py · test_report.py

 contributor/reference/hermetic-evaluation.md  (method only, no numbers — B-25)   .spec/STATUS.md (entry)
```

Boundary crossings, against the seven import-linter contracts in
`pyproject.toml`: every contract names `functualize.*` modules as its source
or forbidden target; `tests.hermetic_eval` is neither, so none applies, and the
instrument still keeps to the stricter rule of public modules only (AC-15). No
product module gains an import. `uv run lint-imports` stays part of every
task's checks.

## Decisions (answered by the maintainer, 2026-10-04)

- **D-1 — where the instrument lives:** `tests/hermetic_eval/` (as
  recommended). No user-visible surface, so no Shape intent page.
- **D-2 — the frontier comparator:** **Codex**, the frontier model —
  `gpt-6-astra` ("Frontier intelligence for the most demanding work" in
  codex's model cache), reasoning effort `medium`, through `codex exec` on the
  maintainer's Codex (ChatGPT) login on contabo (F-14). This overrode the
  recommended Claude Sonnet binding. Consequences written into the spec:
  contracts C-3 is a `codex exec` adapter; the frontier's cost is tokens, not
  dollars (B-18 — a subscription reports no price and none is invented); the
  success-path output shape is unmeasured, so T3 measures it first; the
  shared-model bias of R-1 shrinks (the corpus drafter is Claude-based, the
  frontier is not).
- **D-3 — the frontier distribution:** verbalized probabilities in one
  structured call (as recommended).
- **D-4 — labels:** the implementer drafts against `LABELING.md`; the
  maintainer approves before the freeze (as recommended).
- **D-5 — constants:** as written — support ≥ 10 cells from ≥ 4 scenarios,
  accuracy gap ≤ 0.05 vs the frontier's non-failed cells, zero
  unsafe-continues, adopt needs coverage ≥ 25 % and availability ≥ 90 %, 72 h
  time box, N = 5, seed 20261004.
- **D-6 — evidence:** kept outside the repository and delivered on the tracker
  (as recommended), **and** published to Confluence in the Functualize space
  (`SD`) as a child of `5144577` (B-25, T9, AC-17).
- **D-7 — monetary cost:** instrument only; product evidence unchanged.
- **S-1 and S-4:** accepted by the maintainer.

## Technical approach

Files (the hit set of the retrieval above; `tasks.md` restates them per task —
every path is new unless marked):

- `tests/hermetic_eval/__init__.py` — the instrument's boundary rules (docstring).
- `tests/hermetic_eval/corpus.py`, `corpus/v1/LABELING.md`,
  `corpus/v1/scenarios.jsonl`, `corpus/v1/corpus.lock.json`.
- `tests/hermetic_eval/_router.py` — loads `ROUTER`/`build_router` from the
  example by path, under the module name `hermetic_router_reference`.
- `tests/hermetic_eval/comparators.py` — C-3, C-4, C-5.
- `tests/hermetic_eval/replay.py` — C-6, C-7, S-1.
- `tests/hermetic_eval/metrics.py` — B-15…B-20, S-3.
- `tests/hermetic_eval/report.py` — C-8, C-9, B-21…B-24.
- Tests: `tests/hermetic_eval/test_{corpus,comparators,replay,metrics,report}.py`.
- Docs: `contributor/reference/hermetic-evaluation.md` (new),
  `.spec/STATUS.md` (modified).

Order matters for provenance: the deterministic rule table (T3) is committed
before the corpus is drafted (T6), and the corpus is frozen (T7) before any
live cell (T8).

## Risks

- **R-1 — drafter bias.** The corpus is drafted by a model-based agent, so its
  labels carry that agent's notion of the routes. With D-2 the frontier is a
  different vendor's model (Codex), so the labels no longer flatter the
  frontier by construction. Mitigation: rubric-cited rationales, maintainer
  approval before freeze (D-4), per-stratum reporting.
- **R-2 — the free-tier budget.** 200 hermetic cells need at least two ≈5 h
  windows (F-5); B-12 spends one failed cell per exhausted window. If windows
  are tighter than measured, availability falls and the verdict rule lands on
  *continue research* — which is the honest result, not a harness failure.
- **R-3 — the Codex usage window is shared and already spent once today.**
  The maintainer's Codex login refused a call with "usage limit … try again at
  11:22 PM" (F-14), and another agent on the same login hit the same limit
  earlier. 200 `gpt-6-astra` calls may span several windows; each costs one
  failed cell (B-12). Two guards: frontier availability is reported, and the
  boundary compares against the frontier's **non-failed** cells (B-21), so a
  lost frontier cell cannot make the hermetic decision look better than it is.
  Avoid running other Codex work on the login during T8.
- **R-4 — CLI and model drift mid-run.** The `codex` version is recorded per
  cell; a model the stream names that differs from `gpt-6-astra` stops the run
  (B-7). If the stream never names the model (T3 finds out), drift behind the
  pinned `-m` is undetectable and the finding says so.
- **R-5 — small corpus.** 40 scenarios bound every per-route statistic; the
  distinct-scenario floor in B-21 keeps repeats from manufacturing support.
- **R-6 — root-suite cost.** Offline tests boot the router (≈0.25 s per cell,
  F-1); fixtures stay at ≤ 3 scenarios × 2 repeats per test.
- **R-7 — tracker inconsistency, outside this package.** FUN-6 reads Done while
  its evaluation rows were recorded unmet (F-13). Raised with the maintainer;
  not changed here.

## Surviving smells

| # | smell (catalogue name) | where | why accepted | maintainer review? |
|---|---|---|---|---|
| S-1 | **Duplicate Code** — the acceptance rule restated offline for the threshold sweep | `tests/hermetic_eval/metrics.py` vs `src/functualize/_gate/decision_strategy.py:140-150` | Re-driving the gate per sweep point costs ≈2 h (candidate E). The copy is pinned by a conformance check: at the declared point it must reproduce every recorded route or the report exits 4 (AC-9), so drift is loud, not silent. | accepted (maintainer, 2026-10-04) |
| S-2 | **Primitive Obsession** — ledger rows and metrics as JSON mappings | `cells.jsonl`, `metrics.json` | An append-only interchange file read by a second command; the shape is fixed in `schema.md` and pinned by tests. A typed class would add a third representation of the same evidence Phase 2 already keeps as JSON (its S-2). | no |
| S-3 | **Inappropriate Intimacy (mild)** — the instrument loads the example's `router.py` by file path | `tests/hermetic_eval/_router.py` | The router *is* the subject; copying `ROUTER` would let the measured rule drift from the shipped one. Every ledger row carries `rule_digest`, and `test_replay.py` asserts it is one value across every row and every comparator (`decision_digest` is internal, so the instrument compares digests rather than recomputing one). | no |
| S-4 | **Inappropriate Intimacy** with an external tool — the frontier comparator depends on `codex exec`'s JSONL event shape | `tests/hermetic_eval/comparators.py::FrontierRouter` | An Adapter over the frontier route the maintainer chose (D-2, F-14); the success shape is pinned from a live fixture in T3. Pinned by AC-4 fixtures; a shape change surfaces as `malformed` cells and a model change as `invalid_model`, both visible in the ledger. Rides on D-2. | accepted (maintainer, 2026-10-04) |

No *Forbidden Patterns* entry appears in the AFTER: no product module changes,
so no god-object growth, no peer cross-import, no `_cli` internals; the
instrument holds no module-level mutable state (each provider instance owns its
`calls` list), uses no ABC, and every port is the existing `DecisionProvider`
Protocol.
