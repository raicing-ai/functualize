# Target architecture

## Architectural style

The target is a synchronous hexagonal boundary around a semantic runtime model.
The engine speaks typed ports. A selected provider supplies a compatible family
of repository implementations. `_app` remains the only composition root.

Patterns are used only where they remove a measured smell:

| Pattern | Use here | Smell removed |
|---|---|---|
| Abstract Factory | one provider creates a matched UoW/repository family | split backends and incompatible repository instances |
| Strategy | select a provider factory once from explicit config/URI | backend conditionals scattered through stores |
| Unit of Work | commit one short runtime transition atomically | partial scope/state/run/event/effect updates |
| Repository / Query Object | semantic writes and purpose-built reads | generic CRUD/KV and `hasattr` query discovery |
| Adapter | expose current document stores through new ports during migration | flag-day rewrite and indefinite dual write |
| Facade | public app query/command/admin surface | CLI/MCP/private-store reach-through |
| Transactional Outbox | persist external-effect intent with state transition | commit-then-crash loss and subscriber-as-record |

Bridge was considered but adds no useful role beyond the ports plus provider
family. Inheritance-based backend hierarchies are rejected; protocols and
composition match the repository's extension rules.

## Port family

Names below are architectural contracts, not pre-approved public API spellings.
FUN-17 owns the ADR and exact names.

```python
@dataclass(frozen=True)
class PersistenceCapabilities:
    multi_process: bool
    multi_machine: bool
    fencing: bool
    transactional_outbox: bool
    online_migrations: bool
    notifications: bool

@runtime_checkable
class RuntimePersistenceProvider(Protocol):
    name: str
    capabilities: PersistenceCapabilities

    def migrate(self) -> MigrationReport: ...
    def health(self) -> PersistenceHealth: ...
    def unit_of_work(self, namespace: RuntimeNamespace) -> RuntimeUnitOfWork: ...
    def queries(self, namespace: RuntimeNamespace) -> RuntimeQueries: ...
    def admin(self, namespace: RuntimeNamespace) -> RuntimePersistenceAdmin: ...
    def close(self) -> None: ...

@runtime_checkable
class RuntimeUnitOfWork(Protocol):
    runs: RunRepository
    workflows: WorkflowRepository
    interactions: InteractionRepository
    outbox: OutboxRepository

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def __enter__(self) -> RuntimeUnitOfWork: ...
    def __exit__(self, ...) -> None: ...
```

`WorkflowRepository` owns scope, step, branch, state, and lease invariants
because those values participate in the same fenced transition. It may be split
internally, but callers do not assemble repositories from unrelated providers.
`InteractionRepository` owns gates, candidates, evaluations, and tool/evidence
links. `RunRepository` owns runs and run events. `OutboxRepository` is available
only inside the same UoW.

Read-side methods are named for questions rather than tables:

```python
class RuntimeQueries(Protocol):
    def run(self, run_id: str) -> RunView | None: ...
    def recent_runs(self, query: RunQuery) -> Sequence[RunView]: ...
    def run_tree(self, root_run_id: str) -> RunTree: ...
    def workflow(self, scope_id: str) -> WorkflowView | None: ...
    def resumable_workflows(self, query: WorkflowQuery) -> Sequence[WorkflowView]: ...
    def scope_events_after(self, scope_id: str, seq: int) -> Sequence[EventView]: ...
    def pending_interactions(self, query: InteractionQuery) -> Sequence[InteractionView]: ...
```

This is deliberately not `get/set/delete/list(table)`. A backend can optimize a
question without callers discovering optional methods at runtime.

## Provider registration and selection

1. Core creates a bind-once `RuntimePersistenceHandle` and injects that stable
   port into the engine during core infrastructure setup.
2. Plugins register **factories** and URI schemes during plugin loading. They do
   not instantiate a database and do not wait for APP_READY.
3. Config resolution produces one `PersistenceSelection`.
4. A new `runtime_persistence` boot phase resolves the factory, constructs the
   provider, validates required capabilities, runs migrations, performs a
   health check, and binds the handle once.
5. Rebinding is refused. Explicit selection failure aborts boot with an
   actionable diagnostic. Absence of selection chooses the document
   compatibility provider.
6. Engine execution and public queries begin only after binding.

The handle removes the current temporal race without forcing engine creation to
move after every plugin. It is explicit constructor injection, not a service
locator: it exposes one typed capability and accepts one bind.

Suggested program surface:

```python
FunctualizeApp(
    "release",
    persistence_sources=PersistenceSources(
        url="sqlite:///project/.functualize/runtime.db",
    ),
)
```

`func` may derive the same value from project config, while an embedded app may
provide it in code. This is about the program, so both bootstrap strategies
must converge on the same `PersistenceSelection`. It is not a job input and
does not enter the job-schema renderer.

## Module placement

The implementation requires an ADR because it adds a layer and public plugin
surface.

```text
src/functualize/
├── _types/persistence.py       # stdlib-only DTOs and protocols
├── _persistence/               # new independent peer layer
│   ├── handle.py               # bind-once runtime capability
│   ├── registry.py             # scheme -> provider factory
│   ├── document_adapter.py     # legacy stores behind semantic ports
│   ├── transitions.py          # backend-neutral short UoW operations
│   └── contract.py             # provider conformance helpers (if runtime-needed)
├── _engine/                    # consumes _types ports only
├── _app/                       # selects and wires provider
├── app/                        # query/command/admin facade for surfaces
└── plugin/                     # public re-export for provider authors

plugins/functualize-state-sqlite/
└── ...                         # imports public plugin API only
```

`_persistence` joins `_discovery`, `_config`, `_gate`, `_engine`, and `_plugins`
as an independent peer. It may import `_types`, `_primitives`, and `_events`; it
must not import the engine or config. `_app` supplies resolved configuration.
The engine imports protocols from `_types` and never the concrete layer.

## Write model and transaction boundaries

A UoW surrounds a **transition**, never a job body:

- start: claim/ensure scope + insert run + append start event, then commit;
- during body: each `State` batch is a short fenced UoW;
- step completion: step + scope position/status + events + outbox intent, commit;
- run completion: outcome + final events + terminal scope changes, commit;
- lease renewal: conditional generation/owner update, commit.

User code, agent execution, prompts, notifications, and other network calls run
outside a database transaction. A transition carries the current fencing
generation and the repository refuses stale writes.

## Event and effect ownership

The current `run_log` and `walk_log` subscribers turn EventBus observations into
durable records after the fact. Target behavior reverses that authority:

```text
transition service
  -> commit domain row(s) + event row(s) + outbox intent
  -> emit EventBus notification after commit
  -> dispatcher claims outbox intent and invokes external provider
```

EventBus remains synchronous, ordered, and best effort for live UI/plugins. A
subscriber failure cannot rewrite the committed outcome. Durable evidence is
written by the transition that knows its meaning.

There is no generic “exactly once” promise for external effects. The outbox is
at-least-once when a provider accepts an idempotency key. Providers that cannot
deduplicate must declare an explicit at-most-once policy; the effect record
exposes which policy was used.

## Public surface

The app exposes stable, intent-named methods/facades used by every delivery:

- `app.runtime_queries` — history, workflow status, event watch, pending inputs;
- `app.workflow_control` — claim/resume/cancel/deposit candidate;
- `app.persistence_admin` — health, schema version, describe, migrate/import,
  clear/purge with explicit record/cache distinctions.

The CLI dogfoods these public surfaces. MCP, HTTP, and Lambda do the same.
No surface constructs an internal repository or reads `execution_engine` to
find storage.

## Capability policy

Capabilities are a frozen record with documented semantics. Boot checks them
against deployment requirements:

| Capability | Document adapter | SQLite | Network SQL |
|---|---:|---:|---:|
| transactional runtime family | emulated/limited | yes | yes |
| multiple processes, same host | filesystem-dependent | yes (WAL/busy timeout) | yes |
| multiple machines | no | no | yes |
| fencing | yes | yes | yes |
| transactional outbox | emulated/limited | yes | yes |
| online migrations | no | limited | provider-specific |
| change notifications | polling | polling | provider-specific |

Feature code requests capabilities by typed requirement and refuses at boot or
declaration time if unavailable. It never changes semantics silently.
