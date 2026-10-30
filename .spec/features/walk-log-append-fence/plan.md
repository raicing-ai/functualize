# Plan: scope-targeted walk-log append

## Alignment

The approved Shape Intent [SD/23560193 v2](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/23560193) selects “the append is scope-targeted and fenced” (D-1 = B) and “generation 0 fences nothing” (D-2 = (a)). In scope, in the page's terms: “the port parameters, both stores' implementations, the walker's `generation` datum, the subscriber, one conformance row, a SQLite race test, and the docs that describe the walk log.” The library API gains `scope_id` and `generation`; the bus payload gains `generation`; late scope-log lines disappear. Out of scope: “Removing the inferred routing”, “Recording late events anywhere else”, “What a superseded walker does outside the store”, and changes to `workflow watch` flags, columns, or JSON shape.

## Architecture gate

The codemaps place `_types` and `_primitives` at the foundation, `_events` above them, `_engine` as a peer, and `_app` as the composition root. `WorkflowRunner` creates the walker; the application installs `WalkLogSubscriber` on the bus. The graph's `WalkLogSubscriber` node calls its callback and is reached through `install_walk_log`; the current direct `EventWriter.append` references include conformance and legacy import. Serena found the walker's five `_say` calls inside `run` and `_run_walk`. The existing ADR-033 says the walk log goes through `EventWriter.append`; the persistence reference says it reads through `WorkflowReader`.

BEFORE (arrows show call/data direction; parenthesized labels are layer and audience):

```text
src/functualize/_engine/workflow_walker.py (_engine, internal)
  -- workflow.*(scope_id) --> src/functualize/_events/walk_log.py (_events, internal)
  -- subscriber -> write_state(StateBatch(scope, 0)) + events.append(no scope)
  -- port --> src/functualize/_types/persistence.py EventWriter (_types, internal; plugin public re-export)
  -- implementation --> src/functualize/_primitives/document_store.py (_primitives, internal)
                   \--> plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_run_sql.py (plugin)
```

AFTER:

```text
src/functualize/_engine/workflow_walker.py (_engine, internal)
  -- workflow.*(scope_id, generation) --> src/functualize/_events/walk_log.py (_events, internal)
  -- events.append(scope_id, generation) --> src/functualize/_types/persistence.py EventWriter (_types, internal; plugin public re-export)
  -- implementation --> src/functualize/_primitives/document_store.py (_primitives, internal): _held around append
                   \--> plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_run_sql.py (plugin): INSERT WHERE fence
```

The only new boundary data is the generation on the bus and the two port arguments. No new import arrow crosses peer layers; the existing seven import-linter contracts remain applicable. Both stores already own their fence mechanisms. The subscriber's empty state routing is a **middle man** in the BEFORE: it asks the state writer to choose a log. The AFTER removes that detour. The store-specific fence implementations remain separate because the stores apply writes differently. The checked-in `python-design-patterns` skill and the `design-patterns-refactoring` catalogue were consulted; the simple port extension follows their single-responsibility and remove-middle-man guidance.

## Surviving smells

None introduced or retained in the changed path: the routing middle man is removed, and each store applies the fence where it already applies other scoped writes. Existing large transaction classes are outside this bounded change; the new fields do not add a new responsibility to them. No maintainer review flag arises from this plan.

## Approach and risks

W1 changes the port and both stores, then proves stale/current behavior with a conformance row and the SQLite commit race. W2 adds the walker's held generation to bus events, changes the subscriber to append directly to the scope without a state write, and updates the three docs and changelog. The SQLite predicate is on the INSERT itself because a pre-check loses the race. The document store applies under `_held`, whose scope mutation checks the hold at commit. Risks: out-of-tree store implementations need the two defaulted parameters; generation omitted is intentionally unfenced; the stores differ in refusal form at commit. The conformance gate checks the shared outcome rather than exception shape.
