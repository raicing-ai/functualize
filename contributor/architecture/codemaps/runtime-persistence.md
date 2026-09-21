# Runtime Persistence Codemap

This codemap distinguishes the **current v0.3.0 graph** from the target design.
The target is canonical in
[`../research/runtime-persistence/`](../research/runtime-persistence/README.md)
and must not be described as shipped until its ticket gates pass.

## Current write path

```text
delivery/app/Invoke
  -> JobExecutionEngine.run(RunRequest)
     -> JobExecutionEngine.substrate (lazy, cached)
        -> EngineHost.substrate or substrate_for_project(fresh_root)
     -> FreshStore                 fingerprints/preconditions
     -> ScopeStore                 workflow aggregate, gates, leases, events
        -> ScopeStateStore         rc.state document per scope
     -> RunStore                   run records/events

EventBus
  -> run_log subscriber            buffered -> RunStore at run close
  -> walk_log subscriber           write-through -> ScopeStore
```

`JsonFileSubstrate` maps logical keys to files. `SQLiteSubstrate` maps every key
to one row in `documents(key, payload, revision)` and uses `BEGIN IMMEDIATE` as
a database-wide writer lock.

## Current read/control paths

```text
app/_run_view.py -------------------------> RunStore
app/_workflow_view.py / workflow control -> ScopeStore
_cli/builtins.py ------------------------> public app plus some direct stores
functualize-mcp history/workflow tools ---> RunStore / ScopeStore
functualize-tasks-local ------------------> TaskDocument -> StoreSubstrate
```

The direct construction sites are the main encapsulation blast radius. A public
surface that needs runtime data should ask an app query/control/admin facade,
not discover storage through the execution engine.

## Current ownership by file

| Concern | Primary files |
|---|---|
| Port and host selection | `_types/protocols.py` (`StoreSubstrate`, `EngineHost.substrate`) |
| Default backend | `_primitives/substrate.py` |
| Derived freshness | `_primitives/fresh_store.py`, `fresh_format.py` |
| Workflow aggregate | `_primitives/scope_store.py`, `scope_format.py`, `lease.py` |
| Per-scope state | `_primitives/scope_state_store.py` |
| Run history | `_primitives/run_store.py`, `run_format.py` |
| Shell recall | `_primitives/shell_history.py` |
| Engine wiring/writes | `_engine/executor.py`, `_engine/capabilities/state.py` |
| Durable event subscribers | `_events/run_log.py`, `_events/walk_log.py` |
| Composition | `_app/boot.py`, `_app/impl.py`, `app/core.py` |
| Relational-looking document backend | `plugins/functualize-state-sqlite/.../substrate.py` |

## Target graph

```text
plugins register provider factories
          │
config -> _app runtime_persistence phase
          -> select + migrate + health-check + bind once
                                   │
                                   ▼
engine -> RuntimeTransitionService -> RuntimePersistenceHandle
                                           │
                           short UnitOfWork / Abstract Factory
                           ├── WorkflowRepository
                           ├── RunRepository
                           ├── InteractionRepository
                           └── OutboxRepository

all delivery surfaces -> app runtime query/control/admin facades
workspace/artifact bytes -> separate WorkspaceProvider
freshness and shell recall -> local document services
```

## Layer impact

The target adds `_persistence` as an independent peer layer. It imports only
`_types`, `_primitives`, and `_events`; it never imports `_engine`, `_config`, or
other peers. The engine consumes `_types` protocols. `_app` resolves config and
wires the concrete provider. `plugin/` re-exports provider-author contracts so
external plugins never import private modules.

This requires an ADR and import-linter contract updates before implementation.

## Hotspots and tests

| Hotspot | Risk | Required proof |
|---|---|---|
| engine start/close paths | losing or duplicating authoritative runs | fault injection + every execution surface |
| scope/step/state writes | partial transition or stale runner commit | rollback and fencing tests |
| run/walk event subscribers | two authorities during migration | parity then removal sabotage |
| APP_READY substrate install | temporal coupling/silent fallback | bind-once boot tests, explicit failure |
| CLI/MCP direct stores | divergent read answers | one public query facade exercised twice (cold/warm) |
| legacy import | live workflow loss | historical fixtures, interrupted import, digest/count verification |
| SQLite concurrency | database-wide contention and busy failures | multiprocess claim/state/outbox tests |
| network provider | unsafe transaction retries | database-only callback tests; external effects excluded |
