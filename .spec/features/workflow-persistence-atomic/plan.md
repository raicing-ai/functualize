# workflow-persistence-atomic — Plan

**Status:** architecture gate satisfied 2026-10-11 at `0ede988b`. Waves 0–4 are executable now;
wave 5 waits on D-W1 (`spec.md` §6).

## Alignment

Shape: **SD/12583004** *"Shape Intent — Store Substrate and Relational SQLite Runtime Provider"*,
**version 3**, `Status: Approved`, `Authority: Approved`, `Last reviewed: 2026-10-11`, updated
2026-10-11 05:55:54 UTC (read live this run). MCH-149's `Shape intent` property points at it. The
page's amendment callout records the owner's instruction: comment `01a12981-2ae8-7b6f-853c-4329494623bc`,
*"Ok lets do option a"*.

**In scope, the page's row this feature delivers:**

| ID | Surface (page's name) | Page's behaviour sentence | Where |
|---|---|---|---|
| S-9 | Resuming a parked workflow on the selected store | "A workflow blocked at a gate on the selected store can be claimed, released and resumed by another process. Its scope reads and writes (claim, renew, release, status) go through the runtime store port, never the legacy `ScopeStore`." | waves 0–4 (W-AC-1…5); wave 5 if D-W1 = a |

S-1…S-8 were delivered by `sqlite-runtime-provider`. This feature must not regress them: S-6
(*"Core persisted entities can be inspected and queried with ordinary SQL"*) becomes true for the
walk's records here, and S-8 (*"Every store passes BASELINE"*) is extended to the new commands
(task W12).

**Out of scope — the page's non-goals, in its words, the ones this feature borders:**
*"The rest of FUN-20's suspension/resume rewiring, beyond S-9: engine-side workflow state and
lease fencing outside the walk's scope reads and writes"* (FUN-20); *"Gate interactions, evidence
persistence, the transactional outbox **dispatcher**"* (FUN-21); *"Indefinite dual write; shadow
reads beyond temporary validation"* (rejected) — which is why the walk's state and events move
with it (`spec.md` §3).

## Retrieval performed (gate step 1)

| Tool | Addressed as | What it answered |
|---|---|---|
| zvec-grep 0.2.2 | the worktree's absolute path; index refreshed this run (897/897 files) | the release path (`_primitives/scope_store.py:907-934`, `_primitives/lease.py:254-279`, `frontier.py:327-341`); the recorder seam (`_engine/recording/__init__.py`); ADR-029 |
| graphify 0.9.61 | `graphify extract . --code-only` rebuilt this run, `get_neighbors` with `project_path` = worktree; graph restored to the committed file afterwards | `FrontierWalk` ← `WorkflowWalker.__init__` only; `WorkflowRunner` ← `WorkflowOrchestrator.prelude`; both `uses ScopeStore` |
| serena | project activated by absolute path | `get_symbols_overview` of `frontier.py` (20 `FrontierWalk` methods). **`find_referencing_symbols` failed** with *"The language server manager is not initialized"* — not absent, unreachable this run; reference questions were answered with `rg` and graphify instead, and the implementer re-runs the reference query |
| rg | worktree | 46 `self._store.*` calls across `frontier.py`/`workflow_walker.py`/`workflow_runner.py` (per method: `set_scope_status` 7, `get_scope` 6, `set_position` 5, `record_step` 4, `get_step` 4, `get_branch` 4, `record_branch` 3, `batch` 3, `hold` 2, one each of `set_graph_digest`, `renew_scope`, `release_scope`, `record_epilogue`, `get_position`, `get_graph_digest`, `get_epilogue`, `ensure_scope`); 20 test files construct `FrontierWalk`/`WorkflowWalker`/`WorkflowRunner`; `FrontierWalk(` has one production caller |

Codemaps read: `contributor/architecture/codemaps/data-flow.md` and `modules.md` (updated by the
first feature to name step 6.5). Neither draws the walk's write path; task W17 adds it.

## BEFORE (at `0ede988b`)

```
 LAYER       MODULE                                        WRITES / READS SCOPE THROUGH
 ──────────  ────────────────────────────────────────────  ─────────────────────────────────────
 _engine/    workflow_orchestrator.py ── builds ──► WorkflowRunner(self._engine._scope_store(), …, runtime_store)
             workflow_runner.py   prelude / epilogue  ──► ScopeStore  (get_scope, *_epilogue)
             workflow_walker.py   graph digest, status, ──► ScopeStore  (19 calls)
                                  failure routes, notify ─┐
             frontier.py  FrontierWalk                    │
               claim ─────────────────────────────────────┼──► RuntimeStore.transaction().workflows.claim  ✔ port
                 └─ then ScopeStore.hold(generation)      │       (hand-carried fence)
               renew / release / start / complete /       ├──► ScopeStore  (24 calls)          ✘ legacy
               branches / reads                           │
               block / open_request / consume ────────────┼──► RuntimeStore (inputs)          ✔ port
             capabilities/state.py  ScopeBackedStateStore ┼──► ScopeStore → ScopeStateStore   ✘ legacy
             dependency_runner.py   replay check ─────────┤──► ScopeStore.get_scope           ✘ legacy
 _events/    walk_log.py  ────────────────────────────────┘──► ScopeStore.append_event        ✘ legacy
 _app/       boot.py  _scope_store_for_project ── ScopeStore(app.substrate)
 _primitives/ scope_store.py (1 040 lines) ── documents via StoreSubstrate
             document_store.py  DocumentRuntimeStore ── wraps ScopeStore (the port's document side)
 plugin      SqliteRuntimeStore ── relational tables; SQLiteSubstrate ── `documents` (same file)
```

On `sqlite:` one scope has **two authorities**: the claim in `workflow_scopes`, everything else
in `documents`. The release reads the second, sees generation 0 / `nobody`, and the walk ends
`SUPERSEDED`.

**Smells the BEFORE carries** (catalogue: `design-patterns-refactoring`):

| Smell | Where |
|---|---|
| **Divergent Change** | `FrontierWalk` changes for two reasons — the port (claim, inputs) and the legacy store (everything else) |
| **Inappropriate Intimacy** (a hand-carried fence) | `frontier.py:229` `self._store.hold(self._scope_id, outcome.generation)`: the port's generation is copied into another object's private hold, and the docstring warns that skipping it turns the fence off |
| **Shotgun Surgery** | a scope write today touches the walk *and* `ScopeStore` *and* (for SQLite) cannot reach the port |
| **Primitive Obsession** | step records are untyped `dict`s (`"status"`, `"return_value"`, `"return_value_reusable"` …) read back by key in three modules |

## AFTER

```
 LAYER       MODULE                                        WRITES / READS SCOPE THROUGH
 ──────────  ────────────────────────────────────────────  ─────────────────────────────────────
 _types/     persistence.py  + StartWalk, RenewLease, ReleaseLease, RecordStep, RecordBranch,
                               MoveScope, StepView, EPILOGUE_STEP_KEY; readers step/steps/branch/
                               state, InputReader.for_gate; WorkflowView.graph_digest
 _engine/    workflow_orchestrator.py ── builds ──► WorkflowRunner(…, runtime_store)   (no ScopeStore)
             workflow_runner.py  ─┐
             workflow_walker.py  ─┤
             frontier.py         ─┼──► RuntimeStore.transaction().workflows.{claim,start,renew,release,
               (holds generation) │        complete_step,record_step,record_branch,move,write_state}
                                  ├──► RuntimeStore.workflows.{workflow,step,steps,branch,state}
                                  └──► RuntimeStore.inputs / .events (unchanged / walk log)
             capabilities/state.py  walk scope → PortBackedState (StateBatch @ generation)
                                    non-walk   → ScopeBackedStateStore (unchanged, out of scope)
             dependency_runner.py ──► RuntimeStore.workflows.steps
 _events/    walk_log.py ──► RuntimeStore.transaction().events.append
 _primitives/ document_store.py  DocumentRuntimeStore implements the new commands over ScopeStore
             scope_store.py      unchanged; reached by the walk only through DocumentRuntimeStore
 plugin      SqliteRuntimeStore  implements them over workflow_* / scope_state / scope_events;
             _schema/0002_step_record_metadata.sql
 app/ _cli/  operator surfaces ── D-W1 (a: through RuntimeStore readers + CancelWorkflow)
```

**What crosses a boundary, and is it legal:** `_engine` → `_types` only for the new names (legal;
the engine already imports the port). `_engine` loses its `_primitives.scope_store` imports in
three modules. `_events/walk_log.py` receives the store by injection from `_app` (as it receives
`store_for` today), so `_events` imports nothing new. Plugin → framework through
`functualize.plugin`. Seven import-linter contracts unchanged; `uv run lint-imports` is a gate.

## Iteration log — candidates rejected

| Candidate | Why rejected | Smell it would introduce |
|---|---|---|
| **A. Bridge: keep `ScopeStore` in the walk and make `SqliteRuntimeStore` *also* write `documents`** | dual write, rejected by the shape (*"Indefinite dual write"*) | Shotgun Surgery, two authorities kept on purpose |
| **B. Make `ScopeStore` an adapter over the port** (walk unchanged) | `ScopeStore` is document-shaped (1 040 lines of envelope/`_mutate` logic); adapting it to SQL is the "widen `StoreSubstrate`" move the shape rejects, and the walk would still speak dicts | Middle Man; Primitive Obsession kept |
| **C. One generic `WriteScope(fields: dict)` command** instead of six | the store would interpret field names — transition meaning leaking into storage (ADR-025: *"a store implementation must never contain the word 'resume' in a conditional"*) | Primitive Obsession; Feature Envy in the store |
| **D. Move operator surfaces in the same waves** | they are D-W1's to decide, and the walk path is reachability-closed without them | — (deferred, not rejected) |
| **Settled: six narrow commands + four readers**, each a transition the walk already performs | maps 1-to-1 onto today's call sites, so each switch is reviewable against the line it replaces | checked below |

Smells the settled AFTER **introduces**: **Parallel Inheritance Hierarchies** grows (six more
commands implemented twice) — the same accepted smell as the first feature, with BASELINE as the
guard (W12). **A reserved key** (`EPILOGUE_STEP_KEY`) is a mild Primitive Obsession — accepted:
the epilogue *is* a step record by shape, and a seventh command for it would duplicate
`RecordStep`. No Middle Man: `FrontierWalk` keeps the walk's decisions; the commands carry values.

## Decisions taken within S-9's latitude

- **Job `State` and walk-log events of a walk scope move with the walk** (`spec.md` §3). Reason:
  S-9's "its scope reads and writes", and the shape's rejection of dual authorities.
- **Schema revision `0002`** for three step-metadata columns rather than JSON inside `result`
  (06 §3: these are read per row, not indexed — JSON would be legal, but it would change what the
  `result` column means). Additive; `0001` frozen.
- **Epilogue as a reserved step key**, not a new table.

## Approach (3b — blast radius)

- `FrontierWalk(` — one production caller (`workflow_walker.py:316`); 20 test files construct
  walk objects (list in `tasks.md` W8). They move to a shared fixture that builds the selected
  store — a mechanical change, gated by W-AC-4.
- `ScopeStore` public export (`functualize.app.utils`) stays: the document store and non-walk
  state still use it.
- `DocumentRuntimeStore` grows by six methods; it is a declared middle man (first feature's
  surviving smell 2) and stays one.

## Files expected to change

| File | Change |
|---|---|
| `src/functualize/_types/persistence.py` | +~150 (commands, view, readers) |
| `src/functualize/_primitives/document_store.py` | +~180 |
| `plugins/…/functualize_substrate_sqlite/_workflow_sql.py`, `_readers.py`, `_schema/0002_step_record_metadata.sql`, `_legacy_source.py` | +~250, +~60 |
| `src/functualize/_engine/frontier.py`, `workflow_walker.py`, `workflow_runner.py`, `workflow_orchestrator.py`, `dependency_runner.py` | call-site switch; net ≈ 0 |
| `src/functualize/_engine/capabilities/state.py`, `capabilities/workflow_scope.py`, `src/functualize/testing/builder.py` | walk-scoped state |
| `src/functualize/_events/walk_log.py`, `src/functualize/_app/boot.py` | walk log through the port |
| `src/functualize/plugin/__init__.py`, `tests/test_public_api_surface.py` | exports |
| `src/functualize/testing/conformance/baseline.py` | BASELINE for the new commands |
| `tests/integration/test_substrate_durability.py`, `tests/spec/test_the_walk_writes_only_through_the_port.py` (new), 20 walk-constructing tests | gates |

No class passes ~500 lines: `FrontierWalk` shrinks; `DocumentRuntimeStore`'s writer classes are
per-aggregate already.

## Surviving smells

1. **Parallel Inheritance Hierarchies** — six commands × two stores. Accepted; BASELINE holds the
   pair together. No maintainer review.
2. **Middle Man** — `DocumentRuntimeStore` over `ScopeStore`, now the walk's only path to it.
   Accepted (unchanged rationale from `sqlite-runtime-provider`). No review.
3. **Reserved key** (`EPILOGUE_STEP_KEY`) — accepted, above. No review.
4. **Two state paths** — walk-scoped `State` through the port, non-walk `State` through
   `ScopeBackedStateStore`. Not a catalogue smell but a real seam: **flagged** — it is the line the
   shape's FUN-20 non-goal draws, and it closes when FUN-20 moves the rest.

None is on the CONSTITUTION's forbidden list.

## Design skills consulted

- [x] `python-design-patterns` (in-repo): KISS, SRP — one command per transition.
- [x] `design-patterns-refactoring` (user-level, Refactoring.Guru catalogue): Divergent Change,
  Inappropriate Intimacy, Shotgun Surgery, Primitive Obsession, Middle Man, Feature Envy, Parallel
  Inheritance Hierarchies.
