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
    completed_at: datetime | None   # REQUIRED, no default — ruling R-2 (§1.5)
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
    # TRANSITIONAL(FUN-21): removed when FUN-21 retires the legacy deposit path — ruling R-1 (§1.4)
    def deposited_answer(self, scope_id: str, gate_name: str) -> Any | None: ...
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

### 1.4 Ruling R-1 — the legacy gate-record payload (2026-10-11, amends §1.2)

**The gap.** `FrontierWalk.gate_payload` (`_engine/frontier.py:490-504`) reads the accepted
candidate's payload, and otherwise falls back to `recorded_answer(self._store, …)`
(`_primitives/gate_requests.py:114-126`). That fallback reads `scope["gates"][gate]["payload"]`
off the legacy `ScopeStore` record, and the comment marks it `TRANSITIONAL(FUN-21)`. Nothing on
the port could answer the same question: `InputRequest` has no payload, and `InputReader` had only
`open_for`/`awaiting`/`request`/`candidates_for`. So W7 ("`FrontierWalk` speaks only the port")
and the fallback could not both hold. The production path is `_engine/gate_service.py:103` →
`_recorded_payload` → `walk.gate_payload`. Its only witness is
`tests/workflow/test_gate_resolution_model.py:282`
(`test_legacy_gate_record_resumes_with_zero_candidates`).

**Reading of S-9.** `recorded_answer` reads the walk's **own** scope: the gate record on the scope
it holds. S-9's *"its scope reads and writes … go through the runtime store port"* covers it, so it
moves to the port. It does not stay on `ScopeStore` as an exception.

**Ruling.** A reader on `InputReader`:

```python
def deposited_answer(self, scope_id: str, gate_name: str) -> Any | None:
    """The answer this store holds on the gate that no candidate records, or None.

    Only a store with a legacy deposit path can hold one: a gate record written before
    requests existed, or by the legacy deposit helper, keeps its answer as a bare payload.
    Read-only, never re-validated, fed to replay as it was. TRANSITIONAL(FUN-21).
    """
```

| Store | Answer |
|---|---|
| `DocumentRuntimeStore` | `gate_requests.recorded_answer(self.scope_store, scope_id, gate_name)`, the exact function the walk calls today, so behaviour is unchanged (W-AC-4) |
| `SqliteRuntimeStore` | always `None`. Nothing writes a bare payload to it: its importer turns a legacy deposit into the one accepted candidate it was, `"{request_id}#legacy"` (`_legacy_source.py:302-319`), and that candidate is what replay then reads. Returning `None` here is a fact about this store, not a degradation |
| a third-party store | `None` unless it carries its own legacy deposit path |

The engine changes in one place: `gate_payload`'s fallback becomes
`self._runtime_store.inputs.deposited_answer(self._scope_id, gate_name)`. `gate_service` keeps
calling `walk.gate_payload`, and the precedence stays: an accepted candidate first, then the
deposited answer.

**Why not the alternatives:**
- *A `payload` field on `InputRequest`* would put a document-store legacy into every request view,
  every reader, and every store's contract, for a field only one store can fill.
- *The document store synthesising an accepted candidate from the payload* would change what its
  reader reports. The witness asserts `projected["candidates"] == []` and, after the run, still
  `== []` (`test_gate_resolution_model.py:307,310`), so that is a W-AC-4 break.
- *An explicit exception on `ScopeStore`* would leave W-AC-1 false for the one read S-9 covers.

**What this does not do.** It does not retire the legacy deposit path or its helper; FUN-21 owns
that, and removes `deposited_answer` with it. It writes nothing.

**Gates.**
- `test_gate_resolution_model.py:282` passes unchanged on the document store.
- BASELINE (W13) adds: for a gate answered by an accepted candidate, `deposited_answer` is `None`
  on both stores.
- A SQLite test: a legacy file whose gate had a bare payload, once imported, resumes from the
  `#legacy` candidate, and `deposited_answer` is `None` there.

### 1.5 Ruling R-2 — a step record that never completed (2026-10-11, amends §1.1)

**The gap.** `FrontierWalk._record_timed_out` (`_engine/frontier.py:290-298`) writes
`{"status": "timed_out", …, "completed_at": ""}`: the runner that overran never finished, so the
record has no completion time. `RecordStep` as first written carried no completion time, and the
document store stamps one from `now` (`_primitives/document_store.py:351`). The timed-out record
would quietly gain a timestamp.

**Why it matters (it is not cosmetic).** `completed_at` is read in two places:
- `app/_workflow_view.py:383` shows it as the step's completion time;
- `app/_workflow_control.py:611-625` `_newest_timestamp` uses the newest one as a scope's age for
  `purge --older-than-days`. A `""` fails `fromisoformat` and is skipped; a stamp would make a
  scope taken over by a new runner look recent and survive a purge it should not.

So reading W-AC-4 as "only the fields that carry meaning" does not help: this field carries
meaning.

**Ruling.** `RecordStep.completed_at: datetime | None` is a required field with no default, so
every caller decides and none inherits a stamp by accident:

| Caller | Passes |
|---|---|
| `_record_timed_out` (`frontier.py:290`) | `None` |
| failed-then-routed (`workflow_walker.py:596-604`, today `_now()`) | `now` |
| epilogue (`workflow_runner.py:238-245`, today `datetime.now(UTC)`) | `now` |

| Store | `completed_at=None` becomes |
|---|---|
| document store | `"completed_at": ""`, byte-identical to today |
| SQLite | `workflow_steps.completed_at` NULL (the column is nullable in `0001`) |
| reader | `StepView.completed_at = None` on both |

`CompleteStep` keeps stamping from `now`. Its one caller (`workflow_walker.py:859-865`) always
passes `completed_at=_now()`, so the `""` default of `FrontierWalk.complete` never reaches it.
Already-written W5/W6 code (`86588af5`) adds the field in the W7–W9 pass. BASELINE (W13) adds: a
`RecordStep` with `completed_at=None` reads back as `None` on both stores.

### 1.6 Ruling R-3 — the walk's reads that lived outside the walk files (2026-10-11)

**The gap.** W-AC-1 and W9's gate looked at three files, and W8's file list named four. Two reads
of the walk's own scope live elsewhere:
- `_engine/loop_state.py:72`: `current_iteration` calls `store.get_step(...)`, with its only caller
  at `workflow_walker.py:690`. A looped walk counts its iterations from the legacy store.
- `_engine/executor.py:2162`: `_from_job_value` reads `store.scopes.get_scope(scope_id)` for a
  `FromJob` reference inside a walk.

On SQLite both would go blind, so S-9 would be false for a looped walk and for `FromJob` inside a
walk. This one was found by this run's own sweep: `rg -ln` over `_engine/` for the
`ScopeStore`-only method names.

**Reading.** Both are reads of the walk's own scope, so they are in S-9. Neither is the "engine-side
workflow state … outside the walk's scope reads and writes" that the narrowed FUN-20 non-goal
keeps out.

**Ruling.**
- W8 takes both files (`tasks.md`), with the signatures in §4.
- W-AC-1's gate becomes an `ast` test over **all of `_engine/`**, refusing the `ScopeStore` import,
  `_scope_store(`, `.scopes.` and the `ScopeStore`-only method names.
- The test carries a named allowlist of exactly the out-of-scope sites, each with its reason:
  `executor._scope_store`, `executor._scope_for`, `executor._close_scope`, and
  `capabilities/state.py`.

A future walk read added anywhere in the engine then fails the gate, whatever file it lands in.

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
- `loop_state.current_iteration(reader: WorkflowReader, scope_id, name, bound)` replaces its
  `store: Any` parameter (`loop_state.py:59-75`). It asks `reader.step(scope_id,
  iteration_step_key(name, i))`; the key scheme is unchanged. Its caller is
  `workflow_walker.py:690` (ruling R-3).
- `executor._from_job_value` (`executor.py:2145-2170`), for a `FromJob` reference **inside a walk**
  (`scope_id is not None`), reads `runtime_store.workflows.steps(scope_id)` instead of
  `store.scopes.get_scope(scope_id)`. `reusable_return_value` is handed the step as the record shape
  it reads (status, return value, reusable flag and kind), built from the `StepView`. The
  fingerprint branch, outside a walk, is unchanged (ruling R-3).

## 5. Backward compatibility

| Who | Before | After |
|---|---|---|
| nothing configured | documents | documents, same files, same content (W-AC-4) |
| `sqlite:` | claim in `workflow_scopes`, everything else in `documents` | everything the walk reads and writes in the relational tables; `documents` holds only `fresh`, `shell-history`, the run log, and non-walk state |
| a `sqlite:` file at schema version 1 | — | migrated to 2 at boot |
| code constructing `FrontierWalk(graph, store, scope_id, runtime_store=…)` | worked | `TypeError`; engine-internal, no public caller (`rg -n "FrontierWalk\(" src plugins` lists only `workflow_walker.py`) |
| operator surfaces on `sqlite:` | read `documents` | D-W1 |
