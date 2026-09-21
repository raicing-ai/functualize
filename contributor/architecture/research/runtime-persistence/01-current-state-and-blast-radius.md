# Current state and blast radius

## Baseline

PR #39 introduced a six-method `StoreSubstrate`, retired the old
`functualize-state` domain, consolidated execution through `RunRequest`, and
made the engine own one lazily resolved substrate. This was the correct move for
0.3.0: it closed the split brain between workflow scopes and per-scope state and
gave JSON and SQLite the same durability contract.

The Northstar requirements now satisfy ADR-022's own reopen condition: the
backend's value is in queries, retention, multi-aggregate transactions, and
distributed coordination that a document port cannot express.

## Current production topology

```text
EngineHost.substrate (set by a plugin at APP_READY)
                │
                ▼
JobExecutionEngine.substrate (lazy, cached once)
                │
   ┌────────────┼──────────────┬──────────────┐
   ▼            ▼              ▼              ▼
FreshStore   ScopeStore     RunStore    ShellHistoryStore
                 │
                 └── ScopeStateStore(scope_id)

JsonFileSubstrate                 SQLiteSubstrate
.functualize/*.json               documents(key,payload,revision)
```

`functualize-tasks-local` independently wraps the same substrate in
`TaskDocument`. CLI, public workflow controls, and MCP tools instantiate
`ScopeStore`/`RunStore` directly from `app.execution_engine.substrate`.

## Store inventory and correct future ownership

| Current document/store | Current semantics | Target owner | Reason |
|---|---|---|---|
| `fresh` / `FreshStore` | derived fingerprints and session preconditions; discardable | local/derived document service | not runtime truth; recomputable and latency-sensitive |
| `scopes` / `ScopeStore` | workflow position, steps, decisions, gates, leases, tool calls, events | runtime persistence family | authoritative, relational, high-contention, queryable |
| `scope-state/<id>` / `ScopeStateStore` | durable `rc.state` | runtime persistence family | must commit consistently with scope fencing and transitions |
| `runs` / `RunStore` | run tree, status, origin, events | runtime persistence family | authoritative history and query surface |
| `shell-history` / `ShellHistoryStore` | TUI command recall | delivery-local document service | convenience data, not portable runtime truth |
| `tasks` / `TaskDocument` | local tasks plugin data | plugin-owned repository/compatibility adapter | domain data must not be coupled to an engine private field |

The target therefore narrows “one backend” to the coherent **runtime truth
family**. Keeping shell history local is not split brain; putting workflow state
and its fencing generation in different providers would be.

## Measured coupling

Graphify reports:

| Node | Degree | Material incoming consumers |
|---|---:|---|
| `StoreSubstrate` | 33 | all five core stores, `TaskDocument`, filesystem implementation, SQLite implementation |
| `ScopeStore` | 91 | engine, walker, frontier, workflow runner, state capability, event walk log, CLI, public workflow controls, MCP |
| `RunStore` | 35 | engine run open/close, run-log subscriber, app projections, MCP history/workflow tools |
| `JobExecutionEngine` | 108 | app facade, boot, adapters, Invoke, dependency runner, workflow orchestration |

`ScopeStore` is 924 lines with 55 public/private methods. It currently owns
scope creation, graph identity, status, step records, events, state delegation,
branches, gate payload/drafts, lease fencing, position, epilogue, tool calls,
retention, and operator clearing. That is both a Large Class and Divergent
Change: unrelated requirements modify the same class and whole-document format.

## Blast-radius map

| Area | Current dependency | Required target change |
|---|---|---|
| `_types/protocols.py` | `EngineHost.substrate`, `StoreSubstrate`, `Stored` | add typed runtime-persistence vocabulary; retain document port only for compatibility/local data |
| `_primitives/substrate.py` | default project discovery and JSON I/O | stop being the runtime domain boundary; remain a document adapter |
| `_primitives/scope_store.py` | workflow aggregate and five adjacent concerns | split semantic repositories/transition service; legacy adapter delegates during migration |
| `_primitives/scope_state_store.py` | per-scope JSON state | move state keys into the runtime UoW and fence writes |
| `_primitives/run_store.py` | whole-file run log | replace with run repository and indexed query port |
| `_engine/executor.py` | lazy concrete stores; best-effort run records | inject runtime persistence; make authoritative transitions fail closed |
| `_engine/workflow_*`, `frontier.py` | concrete `ScopeStore` verbs | consume workflow/interaction ports through engine-owned services |
| `_engine/capabilities/state.py` | scope-backed concrete store | consume a state capability bound to current scope and fence |
| `_events/run_log.py`, `walk_log.py` | subscribers write durable truth after emission | persistence moves into transition UoWs; EventBus observes after commit |
| `_app/boot.py` | subscribers resolve engine substrate; plugins install at APP_READY | register factories during plugin load, select/migrate/bind after config |
| `app/_run_view.py`, `_workflow_view.py` | projections over concrete stores | use public query facade, preserving one answer for CLI/MCP |
| `app/_workflow_control.py`, adapter flags | construct `ScopeStore` | use workflow command/query facade |
| `_cli/builtins.py` | direct store construction for data/workflow commands | use public admin/query facade; keep `_cli` public-only |
| `functualize-mcp` | private store imports and substrate reach-through | use public app queries/commands only |
| `functualize-state-sqlite` | one opaque `documents` table and global writer lock | normalized provider, migrations, UoW, capability declaration |
| `functualize-tasks-local` | private `_types` import and engine substrate chain | plugin-owned public persistence contract or legacy document injection |
| tests/examples/docs | concrete store fixtures and filesystem assumptions | backend contract suite, migration fixtures, cold/warm and cross-process capability tests |

## Code smells that drive the redesign

1. **Large Class / Divergent Change:** `ScopeStore` changes for workflow,
   interaction, lease, state, observability, and retention concerns.
2. **Shotgun Surgery:** a new runtime field propagates through JSON formats,
   stores, engine call sites, projections, CLI, MCP, tests, and SQLite payloads.
3. **Primitive Obsession:** untyped nested dictionaries and string keys carry
   domain identity, lifecycle, and revision rules.
4. **Feature Envy / Inappropriate Intimacy:** plugins and public surfaces reach
   through `app.execution_engine.substrate` and import private framework types.
5. **Message Chains:** `app → execution_engine → substrate → concrete store`
   exposes wiring that should be behind an app facade.
6. **Speculative Generality at the wrong level:** `StoreSubstrate` preserves a
   least-common-denominator document API even where the use case requires
   relational queries and transactions.
7. **Silent failure:** the SQLite plugin catches every installation error and
   falls back to files even when SQLite was explicitly selected.
8. **Temporal coupling:** correctness depends on APP_READY installing a backend
   before the engine happens to resolve its lazy property.

## Correctness gaps to close

- A run record is currently best-effort: `_open_run_record` swallows every
  exception. That is suitable for optional observation, not Northstar evidence.
- Workflow steps, state, run outcome, events, and effect intent do not share one
  transaction.
- The SQLite “schema” is a single `documents` table, so query and retention work
  still occurs by loading and rewriting complete JSON payloads.
- `BEGIN IMMEDIATE` serializes every writer in the database; unrelated scopes
  contend despite normalized SQL being able to isolate rows.
- No versioned migration protocol exists for the plugin's data model.
- Backend selection is not a first-class program surface and the
  `functualize.state_providers` entry-point group has no surviving domain SDK
  that activates it automatically.
- SQLite is a shared-file, multi-process backend on one host; it is not a
  multi-machine backend. Current prose suggesting otherwise must not survive.

## Production paths every implementation ticket must name

At minimum, acceptance coverage must traverse:

```text
func cold boot ─┐
func warm boot ─┼─> app/adapter request -> engine.run -> runtime persistence
embedded app ───┤
HTTP/Lambda/MCP ┤
Invoke child ───┘

workflow start -> block -> candidate/input -> claim -> resume -> terminal
run open -> events/state -> outcome -> outbox -> query projection
```

The test matrix must include JSON-compatibility, normalized SQLite, and—once
FUN-22 lands—a network SQL provider. Cached discovery does not alter persistence
selection, but it is still a separate production path and must be exercised.
