# decision-provider-seam — plan

**Phase state.** Specify **confirmed** by the member (2026-09-28);
architecture gate run; every decision, smell and open question answered
(*Decisions* below); task list revised to the answers (T16 added). Execute is
authorised against `tasks.md` as it stands at the commit that carries this
line. Pull request #68 merged as `02c6a96`, and the ten seam
files are byte-identical to `d5747f85` (empty `git diff --name-only`), so no part
of the Gate half needed re-specifying.

## Retrieval, as run

| pass | tool | what it answered |
|---|---|---|
| Specify · prior art | `zg` (index built in this worktree: 838 files, 13 308 entities) | ADR-026 (vocabulary goes in `_types/`, no new layer); ADR-029 on #68 (candidates recorded, not recomputed); `docs/guides/ai.md` §*Strategies vs. presets* (closed strategy set is deliberate, ladders expanded by the walker); `FromStep` (`_types/from_job.py:246`) as the existing name for "this walk's recorded result of a step"; `plugins/PUBLISHING.md` tiers |
| Specify · premises | `rg`, `git grep` at `d5747f85` | every count in `spec.md` §1.1 and `research.md` |
| Plan 3a · shape | `graphify explain GateRegistry` (graph is 27 commits behind `HEAD`; used for edge direction only) | `GateRegistry` is used by `FunctualizeApp`, `_app/boot.py` (`boot_static`, `boot_standard`) and `_engine/capabilities/invoke.py`; uses `GateContext`, `GateResolver`, `GateStrategy` |
| Plan 3a · surface | direct reads at `d5747f85` of `_gate/_registry.py`, `_gate/_context.py`, `_gate/_resolver.py`, `_gate/_evaluation.py`, `_types/gate_resolution.py`, `_engine/gate_service.py`, `_types/workflow.py` | the ladder, the context, what the walk passes |
| Plan 3a · codemaps | `contributor/architecture/codemaps/overview.md`, `modules.md`, `dependencies.md` | two findings below |
| Plan 3b · blast radius | `git grep` at `d5747f85` | hit sets feeding `tasks.md` |

**Disclosed gap.** serena was not used for the 3b pass: the MCP registry is
path-keyed and every checkout is named `functualize`; the branch under
reference (`d5747f85`) is not checked out anywhere this run may write, and its
own worktree has another writer. The 3b hit sets were taken with `git grep`
against the commit object instead. Task T6 re-runs the reference queries with serena against the rebased branch
before editing, and T7/T8 inherit its counts.

**Codemap findings.** `modules.md:100` lists four `_gate/` modules; `master`
has five (`prompt_strategy.py` is missing from the list), and #68 adds a sixth
(`_evaluation.py`).
`overview.md:73` says "12 official plugins" — true today
(`ls -d plugins/*/*/ | wc -l` → 12) and false after this feature. Both are
corrected in task T11.

## Design skills consulted

- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) —
  loaded. Source of every smell name below, and of the Strategy / Adapter /
  Chain of Responsibility readings.
- `python-design-patterns` (in-repo, `.claude/skills/python-design-patterns`,
  `SKILL.md` read; `references/details.md` not read). Two of its rules bite
  here. *Rule of Three* argues against a `DecisionProvider` Protocol with one
  implementation; it is kept because provider neutrality is a standing
  constraint of the track and Phase 3 adds two more providers (an LLM router and
  a deterministic baseline) — recorded as S-3 rather than argued away. *Inject
  dependencies* is why the resolver takes its provider and the provider takes
  its transport by constructor.

## BEFORE — the region at `d5747f85` (#68's head)

```
 PUBLIC                    INTERNAL
 workflow/  ──re-exports──▶ _types/workflow.py ─────────────── Gate(name, awaits, tools, strategy)
                            │   _VALID_GATE_STRATEGIES = {resolve, prompt, ai_inbound, ai_outbound}   (closed)
                            ▼
 _engine/ (peer) ── gate_service.py ── _gate_strategy_list(gate)   if/elif on the name
                            │   registry.evaluate(awaits, gate_strategy, gate_name)   ◀── no workflow_context
                            │   (registry arrives injected; _engine never imports _gate)
                            ▼
 _gate/ (peer) ─── _registry.py  GateRegistry.evaluate ──▶ GateContext(workflow_context={})
                   _resolver.py  GateResolver (Protocol) ◀── ResolveResolver, PromptGateResolver
                   _strategy.py  STRATEGY_PROVIDERS {4 names → package}   pinned == _VALID_GATE_STRATEGIES
                   _evaluation.py blocked_reason_from, evaluate_submission
                            │
 _types/ ───────── gate_resolution.py  EvaluationOutcome, CandidateEvaluation, LadderOutcome …

 plugins/domains/functualize-ai ─ registers "ai_inbound" ─▶ app.gates (GatesView, _types/host.py)
 plugins/adapters/functualize-mcp ─ registers "ai_outbound" ─▶ app.gates

 tests/jev_probe/**  ── stdlib urllib ──▶ opencode.ai (measurement only; no src/ dependency)
```

Dependencies point down; `_engine` and `_gate` are independent peers joined
only by `_app` injecting the registry (contract "Peer layers are independent").

### Smells the BEFORE already carries

- **Shotgun surgery** — adding a gate strategy name touches
  `_types/workflow.py:276` (`_VALID_GATE_STRATEGIES`),
  `_gate/_strategy.py:40` (`STRATEGY_PROVIDERS`), `_engine/gate_service.py:46`
  (`_gate_strategy_list`), `docs/guides/ai.md` (the error message quoted at
  :228) and `tests/gate/test_provider_tables.py:251`. This feature pays it once;
  it does not fix it (S-1).
- **Switch statements** — `_gate_strategy_list` (`gate_service.py:46-56`) is an
  if/elif on the strategy string that encodes each ladder.
- **Primitive obsession** — `GateContext.workflow_context: dict[str, Any]`
  (`_gate/_context.py:34`), and on the walked path it is always `{}` because
  `gate_service.py:104-106` passes nothing. A resolver on the walked path is
  blind to the walk.

## Candidate AFTERs, and what each introduced

**A-1. A Jev-specific gate strategy in a plugin** (`functualize_decision_jev` builds the
Jev request from `GateContext` and applies a threshold itself). Rejected: the
threshold would live in the provider's adapter — the provider package would own
acceptance, which is exactly the authority the track forbids — and a second
provider would duplicate the policy (**duplicate code**, then **divergent
change**).

**A-2. Policy registered at boot, keyed by the awaits model class**
(`DecisionGateResolver(provider, policies={Route: …})`). No `Gate` change, but
the threshold moves from the workflow declaration to app wiring — the workflow
no longer owns it — and a policy keyed on a model class used by two gates is
ambiguous. Kept as D-2's alternative.

**A-3. Policy as a `ClassVar` on the awaits model.** Workflow-owned, no `Gate`
change, but the resolver finds it by attribute name — an implicit convention the
constitution forbids for ports, and invisible to `Gate`'s declaration checks.
Rejected.

**A-4 (settled). Provider-neutral seam in core, policy on the `Gate`, adapter in
its own plugin.** The generic resolver in `_gate/` applies a policy the workflow
declared on the gate, over a result any `DecisionProvider` returns; the Jev
plugin only translates the wire and registers the strategy. Introduces: one
field on `Gate`, one field on `GateContext`, one keyword on `evaluate`, and one
more branch in the switch statement — S-1, S-2 below.

**Spec iteration this caused.** The first draft of `spec.md` let the strategy
read "the gate's workflow context"; the BEFORE map showed that context is empty
on the walked path, so `spec.md` B-13 now names the state source explicitly
(`FromStep`) and C-7 makes the walk pass its results. The first draft also
thresholded on `confidence`; B2 and the track's "no confidence-only
authorisation" moved the rule onto the distribution (B-16).

## AFTER

```
 PUBLIC                    INTERNAL
 workflow/  ──re-exports──▶ _types/workflow.py ─── Gate(…, strategy, decide: ChoiceDecision|None)   [+field]
                            │   _VALID_GATE_STRATEGIES += "decision"
                            │        imports ▼
                            │   _types/decision.py   [NEW]  DecisionResult[T], DecisionProvenance,
                            │                               ChoiceRequest, DecisionProvider (Protocol),
                            │                               ChoiceDecision            (imports _types/from_job)
                            │   _types/errors.py     [+]    DecisionFailure, DecisionUnavailableError
                            ▼
 _engine/ (peer) ── gate_service.py  _gate_strategy_list: "decision" → [decision, prompt, resolve]
                            │   registry.evaluate(…, workflow_context=ledger.results, decision=node.decide)
                            │   (still injected; still no _engine → _gate import)
                            ▼
 _gate/ (peer) ─── _registry.py   evaluate(…, decision=) ──▶ GateContext(…, decision=)       [+kw, +field]
                   decision_strategy.py [NEW]  DecisionGateResolver(provider: DecisionProvider)
                        │  reads ctx.decision, ctx.workflow_context[state step]
                        │  calls provider.choose(ChoiceRequest) ──▶ DecisionResult[str]
                        │  accepts on distribution only; else raises → rung `failed`
                   _strategy.py   STRATEGY_PROVIDERS += {"decision": "functualize-decision-jev"}
                   _evaluation.py unchanged — blocked text composed as before

 plugins/domains/functualize-decision-jev  [NEW, Tier 3]
     _wire.py      request build, response parse, status → DecisionFailure   (imports functualize.plugin)
     _provider.py  JevDecisionProvider, JevTransport (Protocol), UrllibTransport, JevConfig
     _plugin.py    JevPlugin ── app.gates.register_gate_strategy("decision", DecisionGateResolver(…))
                   (imports DecisionGateResolver from functualize.plugin — S-4 resolved)
 core never imports functualize_decision_jev.

 PUBLIC re-exports, provisional:  functualize.plugin  ◀── _types/decision.py, _types/errors.py, _gate/decision_strategy.py
                                  functualize.workflow ◀── ChoiceDecision
```

**Boundary check.** `_types/decision.py` imports only stdlib and
`_types/from_job.py` (allowed: "Types import nothing internal" forbids
`_primitives`…`_cli`, not `_types`). `_gate/decision_strategy.py` imports
`_types` only. `_engine/gate_service.py` gains no import. Plugins are outside
`root_package = "functualize"`, so import-linter does not see them;
`uv run lint-imports` must stay "7 kept, 0 broken" (T12 runs it).

**Forbidden-pattern check** (`.spec/CONSTITUTION.md`): no ABC (Protocols
only); no implicit callable port (`JevTransport` is a Protocol); no global
mutable state (the probe's module-level counters are not copied); no hard-coded
config path (`app.configuration` resolves `[jev]`); no peer cross-import; no
class near 500 LOC (largest new class, `JevDecisionProvider`, is expected
under 150); no shim. None found.

## Why this is not a new authority primitive

The Gate stays the only thing that accepts an answer. The `decision` strategy is
one more rung on the existing ladder; its verdict is recorded by #68's existing
candidate machinery with the existing five `EvaluationOutcome`s; its failure
falls to `prompt` and then to a block, exactly as `ai_inbound`'s does. No node
type, walk outcome, request status or evaluation outcome is added (AC-16).

## Technical approach

Two halves, one branch, one pull request (the branch is merged only after both
halves and the two-push clearing sequence):

1. **Provider half — no external dependency.** `_types/decision.py` and the
   error type; the `functualize-decision-jev` package with its wire mapping and provider;
   offline tests against wire-shaped bodies taken verbatim from the capability
   matrix, plus one credential-gated live test that skips without
   `OPENCODE_API_KEY`.
2. **Seam checkpoint.** Rebase onto the `master` that carries #68, and diff the
   five seam files against `d5747f85`. Any difference stops the run and sends
   the Gate half back to Specify — only the Gate half.
3. **Gate half.** Declaration, resolver, walk wiring, plugin registration,
   end-to-end tests through `app.execute`, docs.

**Offline fixtures and the probe's no-fixture rule.** The capability matrix
refuses recorded bodies *as evidence* ("a recorded body would be evidence about
the recording"). This feature's offline tests use bodies copied from the
matrix's rows *as test inputs for a parser*, which is a different claim: they
assert the adapter maps the shapes the matrix measured, not that the service
still returns them. The live test is the only evidence about the service, and
it is gated like the probe. Stated here because it contradicts the matrix's
wording on its face.

## Files to change (from the hit sets in `research.md`)

Provider half: `src/functualize/_types/decision.py` (new),
`src/functualize/_types/errors.py`, `plugins/domains/functualize-decision-jev/**` (new),
`pyproject.toml` (`[tool.uv.sources]`, `all` extra), `uv.lock`,
`tests/types/test_decision_values.py` (new), `tests/plugins/test_jev_wire.py`
(new), `tests/plugins/test_jev_decision_provider.py` (new),
`tests/plugins/test_jev_live.py` (new).

Public API (T14, T15): `src/functualize/plugin/__init__.py`,
`src/functualize/workflow/__init__.py`, `tests/test_public_api_surface.py`.

Gate half: `src/functualize/_types/decision.py`, `src/functualize/_types/workflow.py`,
`src/functualize/_gate/_strategy.py`, `src/functualize/_gate/_context.py`,
`src/functualize/_gate/_registry.py`, `src/functualize/_gate/decision_strategy.py`
(new), `src/functualize/_engine/gate_service.py`,
`plugins/domains/functualize-decision-jev/src/functualize_decision_jev/{_plugin.py,__init__.py}`,
`plugins/domains/functualize-decision-jev/pyproject.toml`, tests as listed per task,
`docs/guides/ai.md`, `docs/guides/workflows.md`,
`contributor/architecture/codemaps/{overview.md,modules.md}`, `CHANGELOG.md`.

## Risks

- **#68 changes before merge.** Mitigated by task T5's diff; only the Gate half
  is re-specified.
- **Live test spends the free tier's window** (F4, Q2). One request per run;
  skipped without a credential; never in CI (no key there).
- **`ledger.results` holds non-JSON values.** `json.dumps(default=str)`
  (C-6 step 2) renders them; a value whose `str` is its identity yields a poor
  prompt, not a failure. Accepted for Phase 1.
- **Near-tie flips (C2).** The margin rule exists for this; the threshold values
  in tests are illustrative, not recommendations — calibration is Phase 3.

## Surviving smells

| # | smell | where | why accepted | maintainer review? |
|---|---|---|---|---|
| S-1 | **Shotgun surgery** (pre-existing) | adding `"decision"` touches `_types/workflow.py`, `_gate/_strategy.py`, `_engine/gate_service.py`, `docs/guides/ai.md`, `tests/gate/test_provider_tables.py` | fixing the strategy-naming spread is explicitly out of scope in `_gate/_strategy.py:36-38` ("Reconciling the two is deliberately out of scope"), and the time box forbids growing this phase into it | no — recorded |
| S-2 | **Switch statements** (grows by one branch) | `_engine/gate_service.py::_gate_strategy_list` | one branch mirrors `ai_inbound`'s; replacing the switch with polymorphism is the same out-of-scope redesign as S-1 | no — recorded |
| S-3 | **Speculative generality** (mild) | `DecisionProvider` Protocol with one implementation; `DecisionResult.distribution` / `.confidence` optional while Phase 1's only producer always fills both | provider neutrality is a track constraint, not a guess; `noul` (A3) has neither field, and Phase 3's LLM and deterministic baselines report no distribution — making them required now forces a breaking change next phase. Now that the names are public, the optional fields are also what keeps Phase 3 from breaking a published name | accepted by the member, 2026-09-28 |

**S-4 is resolved, not accepted** (member, 2026-09-28): *inappropriate
intimacy* — the plugin importing `functualize._*` — is removed by making the
decision types public API (T14, T15), and the gate in T3 holds the plugin to
`functualize.plugin` imports. What that introduces instead is **public surface
before a second consumer**, the risk the design review's A-Q01 names ("every
public class … is a potential headache"); it is contained by marking all seven
names provisional, per the review's D2.

No entry is on *Forbidden Patterns*.

## Decisions

**Answered by the member (2026-09-28):**

- **D-1 → A, renamed.** Own Tier-3 workspace package, named
  `functualize-decision-jev` (`plugins/domains/functualize-decision-jev`,
  import `functualize_decision_jev`). The middle part follows the
  `<contract>-<implementation>` naming of `functualize-ai-pydantic` and
  `functualize-tasks-local` (`contributor/architecture/codemaps/overview.md:73`);
  here the contract is the core `decision` seam.
- **D-2 → A.** `Gate(decide=ChoiceDecision(...))`. Alignment with the North
  Star and the design review is checked in *Alignment* below.
- **S-4 → public API.** T14 and T15; see *Surviving smells*.

**Answered by the member (2026-09-28, second round):**

- **D-3 → yes.** T1, T3 and T4 close on their own gates with
  `# TRANSITIONAL(decision-provider-seam/T9)` markers; T12 proves every call
  path by sabotage and removes them.
- **S-3 → accepted** (see *Surviving smells*).
- **Q-1 → (b), expressed with existing syntax.** The member's reasoning:
  whether an option needs a person's approval is the functualize user's
  decision, and conditional edges already express it. So there is no
  `auto_accept` field and no declaration-time refusal: the gate's answer feeds a
  `ConditionalEdge`, and the author routes a branch that must be approved
  through a second `Gate` before its effecting step (`spec.md` B-22, AC-17).
  Consequence recorded plainly: the framework no longer enforces the track's
  "no confidence-only authorisation of consequential side effects" — it holds
  where the author draws the approval gate. T10 proves the pattern and T11
  documents it, with that consequence stated.
- **Q-2 → (b) now, (a) later.** The decision rule joins the gate's entry in
  `WorkflowShape.to_dict()` and so the graph digest (T16; `spec.md` B-23,
  AC-18). Structured storage on the request follows with the review's FUN-4
  follow-up, FUN-18/FUN-21 and Phase 2.
- **`spec.md` confirmed**, name `functualize-decision-jev` confirmed.

## Alignment with the North Star and the O'Reilly design review

Read 2026-09-28: the review's 13 pages in the SD space (root page 9240577;
findings G 9240667, C 9306153, A 9306133; decisions 9273345). Verdicts on the
Gate model and what they mean for this design:

| review item | what it says | this design | verdict |
|---|---|---|---|
| G-Q07, claim G-30 | the Gate owns authority; resolvers only propose typed candidates; *which strategy may auto-accept is declared on the Gate* | `decide` on the `Gate` is exactly that declaration; Jev only proposes; acceptance is #68's candidate machinery | aligned |
| G-Q07 failure mode: automation bias | show source and evidence, not just a summary | `blocked_reason` names provider, model, proposed option, probability, margin and thresholds (C-6) | aligned for the block; the answer surfaces' candidate display is FUN-21's |
| G-Q07 failure mode: prompt injection through candidates | candidate content is data, never interpolated into a later prompt | the state text travels in Jev's `state` field, never in `instructions`; the accepted value must be one of the declared `Literal` options, so no free text can come out | aligned — add as a test in T10 |
| G-Q07 / G-Q17 / review D1: stalls | a gate needs a deadline | a decision gate that blocks is an ordinary open request; D1's deadline applies to it unchanged | aligned, delivered by FUN-21 |
| G-Q07: threshold misalignment | thresholds declared per gate | `accept_at` / `min_margin` per gate | aligned |
| G-Q10 | bounded correction loop; an **authorised**-resolver list on the Gate | not needed for `decision` (no generation to correct; an invalid label fails the rung); the authorised-resolver list is not built here | compatible — see risk R-A |
| G-Q11, claim G-36 | record the *policy* that decided; the policy is not in `graph_digest` | the rule joins the graph digest now (T16); structured storage later | **fenced now, recorded later** (Q-2) |
| G-Q18, C-Q04 | record model / prompt / tool bindings | `DecisionResult` carries provider, model and provenance; persisting them is Phase 2 (the review routes it to the Jev ticket, FUN-6, and FUN-18) | aligned in shape, deferred in storage |
| G-Q19, claim G-50 | drop "hermetic"; aim for functional reproducibility | no hermeticity claim anywhere (`spec.md` §7) | aligned |
| A-Q01, review D2 | minimal stable surface; the rest provisional | the new public names are provisional (T14, T15) | aligned |

**R-A (watch item, not a Phase 1 task).** When the authorised-resolver list
(G-Q10) is designed, `decide` should become one entry in it — "the `decision`
strategy may auto-accept under these thresholds" — rather than a second,
parallel authorisation mechanism on `Gate`. Nothing in `decide` blocks that; it
is recorded so the FUN-4 follow-up sees it.
