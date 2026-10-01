# hermetic-router — plan

**Provisional** until `spec.md` is confirmed and D-1…D-4 below are answered.
Authored against `ef1939d` (`origin/master`, observed 2026-10-01).

## Retrieval record

| pass | tool | what it answered |
|---|---|---|
| prior art | `zg query` (index built in this worktree: 853 files, 13 429 entities) | ADR-030 (decisions are candidates; resolver never names `confidence`), ADR-029 (resolutions are recorded, not recomputed; evidence must later be readable outside the scope document), `contributor/reference/runtime-persistence-data-model.md` §2.4/§3 (`input_candidates` columns; opaque provider metadata is JSON), `docs/guides/workflows.md` → *Decision gates*, `.spec/STATUS.md` → *Decision gates — delivered* (Phase 2 owns structured evidence) |
| premises | `rg`, a scratch probe | F-1…F-10 in `spec.md` §1.1 — the default-route bypass (F-1) was found by running it, not by reading |
| 3a shape | serena `get_symbols_overview`/`find_referencing_symbols` (activated by absolute worktree path), graphify `get_neighbors` | `GateContext` referenced from 21 files (all constructions keyword or trailing-default safe); `CandidateEvaluation` constructed in 3 src modules (`_registry.py`, `_evaluation.py`, `gate_requests.py`); graphify is **31 commits stale** (`built_at_commit..HEAD`) — trusted for direction, not line numbers |
| 3b blast radius | serena, `rg` | `GateRegistry.evaluate` has two callers (F-6); `_decision_shape` two references (F-8); `test_gate_drafts.py:176` pins the projected candidate dict exactly (F-5) |

Codemaps read: all five; gate content is in `modules.md:98-100` (the `_gate/`
catalogue, "Eight modules" — T9 makes it nine and names `decision_evidence.py`),
`overview.md:31,36`, `dependencies.md` and `data-flow.md` §5; `entry-points.md`
has none. Two findings, both pre-existing and **not** this feature's to fix
beyond T9's doc touch:

- `dependencies.md` draws `_gate/` *below* the peers and lists the
  independence contract over four modules; `pyproject.toml`'s "Peer layers are
  independent" contract lists **five**, `_gate` included. The AFTER obeys the
  contract (the stricter reading): `_gate` imports no peer, no peer imports
  `_gate` at runtime.
- `data-flow.md` §5 names `RESOLVE`/`PROMPT`/`AI_INBOUND` only — no `decision`
  rung, no candidates. T9 adds the decision rung and evidence to that flow.

## Skills consulted

- `python-design-patterns` (in-repo, `.claude/skills/python-design-patterns`):
  KISS, single responsibility, rule of three.
- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue):
  smell names below; *Collecting Parameter*-style sink; *Move Method* for
  feature envy; *Speculative Generality* and *Primitive Obsession* checks on the
  candidate AFTERs.

## BEFORE

```
layer:      public            internal peers (independent)            foundation
          ┌──────────┐   ┌──────────────────────┐ ┌───────────────┐  ┌──────────────────────────┐
 author → │ workflow │──▶│                      │ │               │  │ _types/workflow.py       │
          │  Gate,   │   │ _engine/gate_service │ │ _gate/        │  │   Gate._check_decision   │
          │ Choice-  │   │  _gate_strategy_list │ │  _registry.py │  │   _decision_shape ◀─envy─┼─ ChoiceDecision
          │ Decision │   │  ["decision",        │ │   evaluate()  │  │ _types/decision.py       │
          └──────────┘   │   "prompt","resolve"]│ │   step 2 short│  │   ChoiceDecision         │
                         │  registry.evaluate ──┼─┼─▶ circuit (F-1)│  │ _types/gate_resolution.py│
                         │  (registry injected; │ │   rungs:      │  │   CandidateEvaluation    │
                         │   no import of _gate)│ │  (name, Eval, │  │   {outcome,detail,errors}│
                         └──────────┬───────────┘ │   payload)    │  └──────────────────────────┘
                                    │             │ decision_     │            ▲ (all layers import _types)
                                    │ ladder_     │  strategy.py  │
                                    ▼ candidates  │  accept? else │  _primitives/gate_requests.py
                         _engine/recording ──────▶│  raise text   │    append_candidate / candidates_for
                                    │             └───────────────┘    {…, outcome, detail, errors, payload}
                                    ▼                                          │
                          FrontierWalk.record_candidates ─▶ store (scopes.json, TRANSITIONAL(FUN-21))
                                                                               │
          ┌────────────────────────────┐                                       ▼
 reader → │ app.utils.gate_draft       │◀── app/_workflow_resume._resolution_view (7 keys / candidate)
          └────────────────────────────┘
plugin:   functualize_decision_jev ──registers "decision"──▶ app.gates (public)   [core never imports it]
```

Smells the BEFORE carries:

- **Feature Envy** — `_decision_shape` (`_types/workflow.py:845`) reads only
  `ChoiceDecision`'s fields; it lives in the 1 083-line workflow module.
- **Large Class/Module (bloater), pre-existing** — `_types/workflow.py` is
  1 083 lines. Not a god *object* (no class near 500 LOC); untouched beyond
  removing `_decision_shape`.
- **Primitive Obsession (text as data)** — the decision's facts (distribution,
  model, thresholds) exist only as a formatted `detail` string on a failed rung
  and are discarded on an accepted one (F-2).
- **A silent trap, not a catalogue smell** — F-1: a default on the decided
  field short-circuits the ladder. Stated plainly rather than given a
  catalogue-shaped name.

## Candidate AFTERs considered

| | evidence lives… | default route via… | introduced smells | verdict |
|---|---|---|---|---|
| **A** | on the **answer model** (an `evidence` field the resolver fills) | resolver applies fallback | evidence forgeable — an answer surface can submit any `evidence`; answer and provenance mixed in one model (**Divergent Change** on every awaits model); absent provider has no evidence | rejected |
| **B** | in a **new evidence store/table** | new `decision_fallback` strategy | duplicates FUN-18/FUN-21's `input_candidates` work (**Shotgun Surgery** when they land); new strategy name breaks `STRATEGY_PROVIDERS == _VALID_GATE_STRATEGIES` pin and edges toward a new primitive | rejected |
| **C** | in a provider **Decorator** that logs `DecisionResult`s | — | provider cannot see the scope, so records are uncorrelated with runs; side channel outside the run record (**Inappropriate Intimacy** with a sink) | rejected |
| **D (chosen)** | on the **rung's `CandidateEvaluation.evidence`**, filled through a per-rung write-once sink on `GateContext` | declared `ChoiceDecision.fallback`, taken by the **existing `resolve` rung** | mutable sink on a frozen context (accepted, S-1); evidence as JSON mapping (accepted, S-2) | chosen |

Iteration that changed the spec: drafting D first put the evidence builder in
`decision_strategy.py`; that would make the resolver module name `confidence`,
breaking ADR-030 point 3 (F-7). The builder moved to its own module and the
standing-guard gate was added to AC-7.

## AFTER

```
layer:      public                 internal peers (independent)                 foundation
          ┌───────────────┐   ┌───────────────────────┐ ┌────────────────────────┐ ┌───────────────────────────────┐
 author → │ workflow      │──▶│ _engine/gate_service  │ │ _gate/_registry.py     │ │ _types/decision.py            │
          │ ChoiceDecision│   │  fallback? ["decision",│ │  evaluate():           │ │  ChoiceDecision(+fallback)    │
          │  (+fallback)  │   │   "resolve"]          │ │   fallback → field     │ │  decision_shape  ◀ moved      │
          └───────────────┘   │  else Phase-1 ladder  │ │   resolved + forced    │ │  decision_digest (new)        │
                              │  registry.evaluate ───┼▶│   per-rung ctx with    │ │ _types/workflow.py            │
                              └──────────┬────────────┘ │   RungEvidence sink ───┼▶│  Gate._check_decision(+3 rules)│
                                         │              │   rung Eval(+evidence) │ │  imports decision_shape       │
                                         │              │ _gate/_context.py      │ │ _types/gate_resolution.py     │
                                         │              │   GateContext(+evidence)│ │  CandidateEvaluation(+evidence)│
                                         │              │   RungEvidence (new)   │ └───────────────────────────────┘
                                         │              │ _gate/decision_strategy│        ▲ all layers import _types
                                         │              │   rule only; no        │
                                         │              │   `confidence` ────────┼─▶ _gate/decision_evidence.py (new)
                                         ▼              └────────────────────────┘     builds C-3 JSON
                               _engine/recording (unchanged: passes evaluation through)
                                         ▼
                               FrontierWalk.record_candidates ─▶ _primitives/gate_requests.py
                                                                  append_candidate (+"evidence" when present)
                                                                  candidates_for   (+evidence)
                                                                         │ scopes.json (TRANSITIONAL(FUN-21))
          ┌──────────────────────────────┐                               ▼
 reader → │ app.utils.gate_draft         │◀── app/_workflow_resume._resolution_view (+"evidence" when present)
          │ app.utils.decision_record NEW│◀── app/_decision_record.py (projection over candidates_for)
          └──────────────────────────────┘
example:  examples/standalone/hermetic_router/ ── public API only ──▶ workflow, app, app.utils, plugin
plugin:   functualize_decision_jev (unchanged)  ──registers "decision"──▶ app.gates
```

Boundary crossings, checked against the seven import-linter contracts:
`_gate → _types` (allowed), `_primitives → _types` (allowed), `app → _primitives`
(already present in `_workflow_resume.py`), `_engine → _types` only (no `_gate`
import; peer independence holds). No new `_types` import of anything internal.
`uv run lint-imports` is part of every task's checks.

## Decisions (for the member — each also in the issue comment)

- **D-1 — the default route.** `ChoiceDecision(fallback="human_review")`,
  taken by the existing `resolve` rung (recommended) · or keep Phase 1's
  block-for-a-person and add no fallback · or allow a field default (today it
  bypasses the decision, F-1). Recommendation: the declared fallback, and
  refuse a default on the decided field.
- **D-2 — where evidence lives.** On the rung's `CandidateEvaluation`
  (recommended) · on the answer model (forgeable) · a new store (FUN-21's
  scope).
- **D-3 — cost.** Token usage only now; monetary cost in Phase 3's replay
  (recommended) · or a price table in config now.
- **D-4 — `decision_record`.** A public, provisional reader in
  `functualize.app.utils` (recommended) · or document reading
  `gate_draft(...)["resolution"]` and deriving fallback from `source`.

## Technical approach

Files (each list is the hit set of the retrieval above; `tasks.md` restates
them per task):

- `src/functualize/_types/decision.py` — `fallback`; `decision_shape` (moved);
  `decision_digest`.
- `src/functualize/_types/workflow.py` — `Gate._check_decision` three rules;
  import `decision_shape`; drop `_decision_shape`.
- `src/functualize/_types/gate_resolution.py` — `CandidateEvaluation.evidence`.
- `src/functualize/_primitives/gate_requests.py` — persist/read evidence.
- `src/functualize/app/_workflow_resume.py` — project evidence.
- `src/functualize/_gate/_context.py` — `RungEvidence`, `GateContext.evidence`.
- `src/functualize/_gate/_registry.py` — per-rung sink; fallback seeding.
- `src/functualize/_gate/decision_evidence.py` (new) — C-3 builder.
- `src/functualize/_gate/decision_strategy.py` — record evidence; time the call.
- `src/functualize/_engine/gate_service.py` — fallback ladder.
- `src/functualize/app/_decision_record.py` (new), `src/functualize/app/utils.py`.
- `examples/standalone/hermetic_router/**` (new), `examples/standalone/README.md`.
- Docs: `docs/guides/workflows.md`, ADR-030 addendum,
  `contributor/reference/runtime-persistence-data-model.md`, `CHANGELOG.md`,
  `.spec/STATUS.md`.

## Risks

- **R-1 — the store change is in a transitional location.** Evidence lands in
  `scopes.json`'s candidate entries; FUN-21 moves candidates to
  `input_candidates`. Mitigation: T9 adds `evidence JSON` to the data-model
  table so FUN-18/21 carry it; the key is omitted when absent, so old documents
  read unchanged.
- **R-2 — the default-on-decided-field refusal is a behaviour change.** A
  Phase 1 workflow with such a default stops loading. Measured: the files
  using `decide=` are six (`rg -l "decide=" tests examples docs`); the only
  defaulted `Literal` field among them is `Loose.numbered` / `Loose.maybe` in
  `tests/workflow/test_gate_decide_declaration.py:46-48`, which are refused
  earlier for their annotation — so the new check must run **after** the
  annotation check, or that test's expected message changes. Pre-release;
  breaking changes are free.
- **R-3 — evidence size.** Distribution ≤ 32 options (`ChoiceRequest` cap);
  bounded.
- **R-4 — the exact margin comparison** (Phase 1 open item) is unchanged; a
  printed `0.10` lead can fail `min_margin=0.10` and fall back. The fallback
  makes that outcome safe (human review), not wrong.

## Surviving smells

| # | smell (catalogue name) | where | why accepted | maintainer review? |
|---|---|---|---|---|
| S-1 | **Temporal coupling via a mutable collecting parameter** — a write-once `RungEvidence` held by the frozen `GateContext` | `_gate/_context.py`, `_gate/_registry.py` | Keeps the `GateResolver` protocol (`resolve(ctx) -> BaseModel`) unchanged for four resolvers in core and plugins; the alternative (a second return/raise shape) changes every resolver. One sink per rung, created by the registry, never global. | **yes** |
| S-2 | **Primitive Obsession** — evidence is a JSON mapping, not a typed value | `CandidateEvaluation.evidence`, C-3 | The data-model doc's rule: provider metadata documented as opaque is JSON (`runtime-persistence-data-model.md` §3); the shape is versioned (`schema`) and fixed by C-3 and its tests. A typed class would add a third representation to keep in sync. | no |
| S-3 | **Large Class/Module**, pre-existing | `_types/workflow.py` (1 083 lines) | Not introduced; this change shrinks it by moving `_decision_shape` out. | no |
| S-4 | **Inappropriate Intimacy (mild)** — `decision_record` reads `source` strings (`strategy:resolve` ⇒ fallback) | `app/_decision_record.py` | `GateCandidate` reserves `source` for readers; this is a reader and routes nothing. The mapping lives in one function. | **yes** |

No *Forbidden Patterns* entry appears in the AFTER: no global mutable state, no
ABC, no implicit `Callable` port, no peer cross-import, no `_cli` internals, no
god-object growth.
