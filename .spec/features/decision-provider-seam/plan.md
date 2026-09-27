# decision-provider-seam — plan

**Phase state.** Specify drafted, **not confirmed**; architecture gate run; task
list drafted, **not reviewed**. Execute is not authorised. Three decisions
below need the member before it is (D-1 … D-3), and the Gate half additionally
waits for pull request #68 to reach `master`.

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

**A-1. A Jev-specific gate strategy in a plugin** (`functualize_jev` builds the
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
                   _strategy.py   STRATEGY_PROVIDERS += {"decision": "functualize-jev"}
                   _evaluation.py unchanged — blocked text composed as before

 plugins/domains/functualize-jev  [NEW, Tier 3]
     _wire.py      request build, response parse, status → DecisionFailure   (imports functualize._types)
     _provider.py  JevDecisionProvider, JevTransport (Protocol), UrllibTransport, JevConfig
     _plugin.py    JevPlugin ── app.gates.register_gate_strategy("decision", DecisionGateResolver(…))
                   (imports functualize._gate.decision_strategy at runtime — see S-4)
 core never imports functualize_jev.
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
   error type; the `functualize-jev` package with its wire mapping and provider;
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
`src/functualize/_types/errors.py`, `plugins/domains/functualize-jev/**` (new),
`pyproject.toml` (`[tool.uv.sources]`, `all` extra), `uv.lock`,
`tests/types/test_decision_values.py` (new), `tests/plugins/test_jev_wire.py`
(new), `tests/plugins/test_jev_decision_provider.py` (new),
`tests/plugins/test_jev_live.py` (new).

Gate half: `src/functualize/_types/decision.py`, `src/functualize/_types/workflow.py`,
`src/functualize/_gate/_strategy.py`, `src/functualize/_gate/_context.py`,
`src/functualize/_gate/_registry.py`, `src/functualize/_gate/decision_strategy.py`
(new), `src/functualize/_engine/gate_service.py`,
`plugins/domains/functualize-jev/src/functualize_jev/{_plugin.py,__init__.py}`,
`plugins/domains/functualize-jev/pyproject.toml`, tests as listed per task,
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
| S-3 | **Speculative generality** (mild) | `DecisionProvider` Protocol with one implementation; `DecisionResult.distribution` / `.confidence` optional while Phase 1's only producer always fills both | provider neutrality is a track constraint, not a guess; `noul` (A3) has neither field, and Phase 3's LLM and deterministic baselines report no distribution — making them required now forces a breaking change next phase | **yes** — put to the member with D-1…D-3 |
| S-4 | **Inappropriate intimacy** | `functualize_jev._plugin` imports `functualize._gate.decision_strategy` and `functualize._types.decision` at runtime | precedent: bundled plugins already import `functualize._types.*` at runtime (`functualize-mcp/_tools.py:24`, `functualize-substrate-sqlite/substrate.py:49`); a public export is deferred as ADR-029 deferred its own | **yes** — the alternative is a public `functualize.plugin` export, which is a public-API decision |

No entry is on *Forbidden Patterns*.

## Decisions awaiting the member

Three, each in full in the Multica issue comment that delivered this package.
Summary:

- **D-1. Where the Jev adapter lives.** Recommended: a new Tier-3 workspace
  package `plugins/domains/functualize-jev`. Alternatives: a module in
  `functualize-ai`; a module in core.
- **D-2. Where the workflow declares the decision rule.** Recommended:
  `Gate(decide=ChoiceDecision(...))`. Alternative: registered at boot, keyed by
  the awaits model (A-2).
- **D-3. Reachability for the provider half before #68 lands.** Recommended:
  provider-half tasks close on their own gates with `# TRANSITIONAL(decision-provider-seam/T9)`
  markers, and checkpoint T12 proves every production call path by sabotage
  before the branch merges. Alternative: hold every provider-half task open
  until the Gate half lands.

## Open questions (not blocking Phase 1)

- **Q-1.** Should a decision gate with an `effecting=True` step reachable
  without another gate be refused at declaration? Phase 1's workflow has none;
  FUN-6 (Phase 2) owns the policy for `human_review` and side effects.
- **Q-2.** Should the accepted rung's payload carry the distribution and
  provenance as structured evidence? Deferred to Phase 2, which owns the run
  record's decision fields.
