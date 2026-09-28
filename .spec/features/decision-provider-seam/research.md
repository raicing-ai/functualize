# decision-provider-seam — research

Findings that changed the shape of the feature, with the command behind each.
Run from this worktree's root at `4cd37f7` unless a line says `d5747f85`, in
which case it ran against the commit object in the registered clone
(`git grep … d5747f85 -- <paths>`), because that branch's worktree has another
writer and is read-only to this feature.

## F-1. The walked gate path gives strategies an empty context

```
git show d5747f85:src/functualize/_engine/gate_service.py   # lines 104-106
    outcome = registry.evaluate(
        node.awaits, gate_strategy=strategies, gate_name=node.name
    )
```

`GateRegistry.evaluate` defaults `workflow_context` to `{}`
(`_gate/_registry.py:133-134` at `d5747f85`). The only callers of
`GateRegistry.evaluate` are `_engine/gate_service.py:104` and
`GateRegistry.resolve_gate` itself (`_gate/_registry.py:289`) —
`git grep -n -E "\.evaluate\(" d5747f85 -- src plugins tests`, filtered to the
registry. **Shape change:** a decision strategy cannot find the text to decide
about unless the walk passes it, so `spec.md` B-13 names the source step
(`FromStep`) and C-7 makes the walk pass `ledger.results`
(`_engine/workflow_walker.py:540` records `ledger.results[name] = run.value`).

## F-2. The set of declarable strategies is closed, and pinned by a test

```
rg -n "_VALID_GATE_STRATEGIES" src tests
src/functualize/_types/workflow.py:276   frozenset({"resolve", "prompt", "ai_inbound", "ai_outbound"})
src/functualize/_types/workflow.py:317   (the __post_init__ check)
tests/gate/test_provider_tables.py:251   assert set(STRATEGY_PROVIDERS) == set(_VALID_GATE_STRATEGIES)
```

`docs/guides/ai.md` §*`Gate(strategy=...)` accepts only the four bare strategy
names* records that the closed set is deliberate (a `Gate` is validated at
import time, before any plugin registers). **Shape change:** the new strategy
name has to join that set and the provider table in one task (T6).

## F-3. Prior art that decided the layer and the vocabulary

- ADR-026 — new ports and vocabulary go in `_types/`, not a new layer.
- ADR-029 (on #68) — a candidate's evaluation is recorded at submission and
  never recomputed; this is what makes "the provider is not called again on
  resume" (B-19) free rather than new work.
- `_types/from_job.py:246` `FromStep` — "a read of *this walk's* recorded result
  for one step", already used for gate tool bindings. Reused for the decision's
  state source instead of a bare step-name string.
- `plugins/PUBLISHING.md` — Tier 3 needs an implementation and a package that
  installs; nothing more.

## F-4. Plugin tests run from `tests/`, not from the plugin

```
rg -n "domains|functualize-ai" .github/workflows/*.yml     # 0 hits
rg -n "testpaths" pyproject.toml                           # testpaths = ["tests"]
ls tests/plugins | rg -c "ai_|mcp_"                        # 26: the ai/mcp plugin tests live here
```

CI names `functualize-mcp`'s and `functualize-substrate-sqlite`'s own test
directories explicitly and no domain plugin's. **Shape change:** the Jev tests
go under `tests/plugins/` and `tests/integration/`, not
`plugins/domains/functualize-decision-jev/tests/`, or CI would never run them.

## F-5. Bundled plugins already import `functualize._types` at runtime

```
rg -n "^from functualize\._|^import functualize\._" plugins/*/*/src
plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/substrate.py:49-50
plugins/adapters/functualize-mcp/src/functualize_mcp/_server.py:17
plugins/adapters/functualize-mcp/src/functualize_mcp/_tools.py:24-25
plugins/adapters/functualize-inline/src/functualize_inline/plugin.py:14
```

Precedent for `functualize_decision_jev` importing `functualize._types.decision` and
`functualize._gate.decision_strategy` without a public export — recorded as
surviving smell S-4, for the member.

## F-6. Counts the plan quotes

| claim | command | value |
|---|---|---|
| no seam symbol exists yet | `rg -n 'DecisionResult\|DecisionProvider\|ChoiceDecision\|DecisionGateResolver' src plugins tests` | 1 (prose, `tests/jev_probe/__init__.py:6`) |
| no core file names Jev | `rg -c -i 'jev' src/functualize` | 0 |
| plugin packages today | `ls -d plugins/*/*/ \| wc -l` | 12 |
| `GateContext(` constructions in tests (must keep constructing after a defaulted field) | `git grep -c "GateContext(" d5747f85 -- tests`, summed | 50, across 7 files |
| `gate_service` tests at the seam | `git show d5747f85:tests/engine/test_gate_service.py \| rg -c "def test_"` | 4 |
| graphify's graph age | `git rev-list --count <built_at_commit>..HEAD` | 27 commits |
