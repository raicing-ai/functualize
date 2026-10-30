# Tasks: scope-targeted walk-log append

The W1 gate is all-or-nothing because the public port and two implementations must agree before conformance can pass. The W2 tasks use W1's completed contract. Each checkbox is checked only after its acceptance gate and production reachability check pass.

## W1 — store contract and race

- [x] T1 [F: `src/functualize/_types/persistence.py`, `src/functualize/_primitives/document_store.py`, `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_run_sql.py`, `src/functualize/testing/conformance/baseline.py`, `plugins/substrates/functualize-substrate-sqlite/tests/test_run_sql.py`] Extend the port; fence scope-targeted append at apply time in both stores; add the conformance row and SQLite commit-race test. Acceptance: the new conformance row fails against the base and passes on both stores; the new SQLite race test passes; inferred routing remains green. Reachability: application boot selects a store, walker bus subscriber writes `tx.events.append` through that store's `EventWriter`; sabotage this wire after committing and require the integration test to fail.

## W2 — walker, subscriber, and docs

- [ ] T2 [F: `src/functualize/_engine/workflow_walker.py`, `src/functualize/_events/walk_log.py`, `contributor/reference/runtime-persistence-data-model.md`, `contributor/adr/033-the-walks-scope-io-goes-through-the-selected-store.md`, `contributor/architecture/codemaps/data-flow.md`, `CHANGELOG.md`] Emit the held generation, pass it to the scope-targeted append, strip it from stored payload, delete the routing write, and describe the new contract in durable docs and changelog. Acceptance: supplied matrix and both generation-carrying repros pass; requested workflow and integration suites pass; docs accurately state the port and no-routing-write behavior; final lint, type, import and requested test gates pass. Reachability: `_app` installs the subscriber; `_engine` emits through the bus; sabotage the emit/subscriber wire after committing and require the integration test to fail.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 1, "tasks": ["T1"]},
    {"id": 2, "tasks": ["T2"]}
  ]
}
```
