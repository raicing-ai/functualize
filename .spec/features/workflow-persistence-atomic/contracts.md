# workflow-persistence-atomic — Contracts

The port surface moves, so this file exists. An interface that changes without appearing here is
the defect it prevents.

## 1. Port vocabulary — `src/functualize/_types/persistence.py`

All new names are frozen dataclasses of plain values and `Protocol` methods (zero logic, stdlib
only — the module's own rule and the "Types import nothing internal" contract). Every scope
mutation carries the held `generation`, so fencing stays in the store's predicate (I-3).

### 1.1 New commands

```python
@dataclass(frozen=True)
class StartWalk:            # ensure the scope, stamp it running, settle its position
    scope_id: str
    generation: int
    workflow: str
    entry: str | None       # used only when the scope has no position yet
    graph_digest: str       # recorded when the scope has none; never overwritten here
    now: datetime

@dataclass(frozen=True)
class RenewLease:           # extend the held lease; the generation does not move
    scope_id: str
    generation: int
    owner: str
    now: datetime
    lease_seconds: float

@dataclass(frozen=True)
class ReleaseLease:         # expire the lease in place; generation kept (lease.release semantics)
    scope_id: str
    generation: int
    now: datetime

@dataclass(frozen=True)
class RecordStep:           # a step record that moves neither position nor status
    scope_id: str           #   (timed_out on takeover; failed-then-routed; the epilogue)
    generation: int
    step_key: str
    now: datetime
    iteration: int = 0
    status: str = "success"
    result: Any = None
    reusable: bool = False
    result_kind: str | None = None
    result_type: str | None = None
    inputs: Mapping[str, Any] | None = None
    effecting: bool = False

@dataclass(frozen=True)
class RecordBranch:         # an immutable decision: conditional choice, failure route, notify marker
    scope_id: str
    generation: int
    decision_key: str
    chosen_target: str
    now: datetime

@dataclass(frozen=True)
class MoveScope:            # status and position with no step: nested-gate block, END reached
    scope_id: str
    generation: int
    status: str             # checked against FUN-18's SCOPE table on commit
    position: str | None
    now: datetime
```

`CompleteStep` gains, with defaults so existing callers compile: `reusable: bool = False`,
`result_kind: str | None = None`, `result_type: str | None = None`,
`inputs: Mapping[str, Any] | None = None`, `effecting: bool = False`. These are the fields
`FrontierWalk.complete` already writes into its step record (`frontier.py:410-430`); today they
exist only in the legacy document.

`EPILOGUE_STEP_KEY: Final = "__epilogue__"` — the workflow body's return value is a `RecordStep`
under this key (replacing `ScopeStore.record_epilogue` / `get_epilogue`, `workflow_runner.py:226-245`).

### 1.2 Writer and reader methods

```python
class WorkflowWriter(Protocol):       # existing: claim, complete_step, suspend, resume, cancel, write_state
    def start(self, cmd: StartWalk) -> None: ...
    def renew(self, cmd: RenewLease) -> None: ...
    def release(self, cmd: ReleaseLease) -> None: ...
    def record_step(self, cmd: RecordStep) -> None: ...
    def record_branch(self, cmd: RecordBranch) -> None: ...
    def move(self, cmd: MoveScope) -> None: ...

@dataclass(frozen=True)
class StepView:
    scope_id: str
    step_key: str
    iteration: int
    status: str
    result: Any = None
    reusable: bool = False
    result_kind: str | None = None
    result_type: str | None = None
    inputs: Mapping[str, Any] | None = None
    effecting: bool = False
    completed_at: datetime | None = None

class WorkflowReader(Protocol):       # existing: workflow, resumable, events_after
    def step(self, scope_id: str, step_key: str, iteration: int = 0) -> StepView | None: ...
    def steps(self, scope_id: str) -> Sequence[StepView]: ...
    def branch(self, scope_id: str, decision_key: str) -> str | None: ...
    def state(self, scope_id: str) -> Mapping[str, Any]: ...

class InputReader(Protocol):          # existing: open_for, awaiting, request, candidates_for
    def for_gate(self, scope_id: str, gate_name: str) -> InputRequest | None: ...   # newest
```

`WorkflowView` gains `graph_digest: str | None = None`.

**Refusal semantics, uniform across the new writers:** a command whose `generation` is not the
scope's current one lands nothing. On commit the store raises its fence refusal (the same type its
existing fenced writers raise — `StaleGenerationError` on both stores today); `renew` and
`release` callers keep their best-effort `except` (`frontier.py:324,337`), exactly as now. A
`MoveScope`/`StartWalk` status the SCOPE machine does not allow raises `IllegalTransition`.
`RecordBranch` on an existing `(scope_id, decision_key)` with a **different** target raises; with
the same target it is a no-op (replay).

### 1.3 Public exports — `functualize.plugin.__all__`

Every name above is exported (the D-2 = a rule of the first feature: a store implements what
`functualize.plugin` exports). `tests/test_public_api_surface.py` lists them.

## 2. Store implementations

| Store | How the new commands land |
|---|---|
| `DocumentRuntimeStore` (`_primitives/document_store.py`) | over the same `ScopeStore` methods the walk calls today — `ensure_scope`/`set_scope_status`/`set_position`/`set_graph_digest`, `renew_scope`, `release_scope`, `record_step`, `record_branch`, `record_epilogue` via the reserved key — applied in its buffered transaction with the generation as the hold. Readers read the same scope document. **No behaviour change** (W-AC-4). Its marker comment is updated: it is now the walk's only path to those methods |
| `SqliteRuntimeStore` (plugin) | `StartWalk` → upsert `workflow_scopes` (status, position, graph_digest when NULL); `RenewLease`/`ReleaseLease` → one conditional `UPDATE … WHERE lease_generation = :held AND lease_owner = :owner` (release clears owner and sets `lease_expires_at = now`, keeps generation); `RecordStep`/`CompleteStep` → `workflow_steps` upsert on `(scope_id, step_key, iteration)`; `RecordBranch` → `workflow_branches` insert (unique `(scope_id, decision_key)`); `MoveScope` → `workflow_scopes` status/position/terminal_at; `state()` → `scope_state`; `step(s)`/`branch` → their tables. Every statement carries `fence_sql` |

## 3. Schema — revision `0002_step_record_metadata.sql` (plugin)

```sql
ALTER TABLE workflow_steps ADD COLUMN result_kind TEXT;
ALTER TABLE workflow_steps ADD COLUMN result_type TEXT;
ALTER TABLE workflow_steps ADD COLUMN effecting INTEGER NOT NULL DEFAULT 0 CHECK (effecting IN (0, 1));
```

Forward-only and additive; `0001` is not edited (its checksum is frozen). The importer writes the
three columns when a legacy step record carries them (`return_value_kind`, `return_value_type`,
`effecting`), else NULL / 0. `MigrationHarness.historical` gains `"version-1"`.

## 4. Engine-internal seams (not public)

- `FrontierWalk(graph, scope_id, *, runtime_store)` — the positional `store: ScopeStore` argument
  is **removed**; so is `ScopeStore.hold` from the walk (the generation lives in `FrontierWalk` and
  rides in every command).
- `WorkflowWalker` and `WorkflowRunner` lose their `ScopeStore` argument the same way;
  `WorkflowOrchestrator` stops passing `self._engine._scope_store()` (`workflow_orchestrator.py:186`).
- `WorkflowScope` gains `generation: int | None`; the `State` capability built for a step inside a
  walk writes `StateBatch(scope_id, generation, …)` and reads `WorkflowReader.state`. A `State`
  with no walk generation keeps today's `ScopeBackedStateStore` (out of scope, spec §3).
- `_events/walk_log.py` appends through `tx.events.append(type, payload, run_id)` on the selected
  store instead of `ScopeStore.append_event`.
- `DependencyRunner` (`dependency_runner.py:82-88`) reads `WorkflowReader.steps`.

## 5. Backward compatibility

| Who | Before | After |
|---|---|---|
| nothing configured | documents | documents, same files, same content (W-AC-4) |
| `sqlite:` | claim in `workflow_scopes`, everything else in `documents` | everything the walk reads and writes in the relational tables; `documents` holds only `fresh`, `shell-history`, the run log, and non-walk state |
| a `sqlite:` file at schema version 1 | — | migrated to 2 at boot |
| code constructing `FrontierWalk(graph, store, scope_id, runtime_store=…)` | worked | `TypeError`; engine-internal, no public caller (`rg -n "FrontierWalk\(" src plugins` lists only `workflow_walker.py`) |
| operator surfaces on `sqlite:` | read `documents` | D-W1 |
