# Plan — Scope record lifecycle

## A · Architecture: BEFORE

Every durable fact about a run lives in **one project-wide file**, and every
operation on any of those facts rewrites the whole thing.

```
                        .functualize/
                        ├── state.json      (fingerprints, HISTORY_LIMIT=200)
                        ├── runs.json       (run log,      RUNS_LIMIT=500)
                        └── scopes.json     ← no cap at all
                             │
        ┌────────────────────┴────────────────────┐
        │  {"scopes": {                           │
        │     "<scope-a>": {steps, gates, branches,
        │                   position, epilogue,   │
        │                   tool_calls, state},   │  ← job state lives HERE
        │     "<scope-b>": {...},                 │
        │     ... 2,188 of these ...              │
        │  }}                                     │
        └─────────────────────────────────────────┘
                             ▲
                             │ one fcntl.flock sidecar for the whole file
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   run A's state        run B's state      workflow C's
   rc.state.set()       rc.state.set()     step records
```

`ScopeBackedStateStore.set` (`_engine/capabilities/state.py`) →
`ScopeStore.set_state` (`_primitives/scope_store.py:248`) → `_mutate` (`:158`)
→ `update_scopes` → **lock, parse the entire envelope, mutate one key, serialize
the entire envelope, `os.replace`**.

Three consequences, each independently a defect:

| | mechanism | evidence |
|---|---|---|
| **Cost is O(project age)** | one key's write parses and rewrites every record the project ever made | 58.16 ms/set on 1,019 KB vs 0.28 ms empty — `.spec/reviews/omp-after-review.md` F1 |
| **Nothing bounds the file** | `scope_format` has no limit; its two siblings do | `HISTORY_LIMIT=200` (`state_format`), `RUNS_LIMIT=500` (`run_format:69`), `scope_format` — none |
| **Unrelated runs serialize** | one file means one lock, so two jobs sharing nothing contend | `scopes_lock(self._path)` — the path is per project, not per scope |

And the file cannot be drained: a non-workflow scope is written with
`status: "running"` and nothing ever marks it terminal, so `purge_scopes`
refuses it (`app/_workflow_control.py:442`), the age filter refuses it for
having no timestamps (`:424-426`), and `list_scopes` hides it. The growth is
invisible to the person it is happening to.

### Existing smells in the BEFORE

- **Divergent siblings.** Three stores with the same shape, two capped and one
  not. The cap is a property of the *pattern*, implemented per file.
- **Primitive obsession on the envelope.** Every accessor is
  `_read()["scopes"][sid][section]`; the record has no type, so "does this
  section exist" is re-answered at 20 call sites.
- **Temporal coupling, unenforced.** `set_scope_status` must happen before
  `purge` can ever remove the record, and nothing makes that ordering real.

## B · Architecture: AFTER

**Job state stops being a section of the shared record and becomes its own
per-scope file.** The scope record keeps what it was always for — the walk's
control data — and gains a cap.

```
                        .functualize/
                        ├── state.json      (fingerprints)
                        ├── runs.json       (run log)
                        ├── scopes.json     ← control data only, now capped
                        │    {"scopes": {"<id>": {steps, gates, branches,
                        │                         position, epilogue,
                        │                         tool_calls, status}}}
                        └── scope-state/
                             ├── <scope-a>.json   ← one run's state, one lock
                             ├── <scope-b>.json
                             └── ...
                                  ▲
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
   run A's state            run B's state            workflow C's steps
   → scope-a.json only      → scope-b.json only      → scopes.json
   (never contends with B)  (never contends with A)
```

What each acceptance criterion is paid by:

| AC | paid by | why this and not the alternative |
|---|---|---|
| **AC-1** cost independent of project age | per-scope state file | A cap alone cannot satisfy it *as written* — AC-1 measures against 2,000 accumulated records, and a cap makes that state unreachable, which makes the criterion untestable rather than met. |
| **AC-2** a bound that never evicts a live scope | `SCOPES_LIMIT`, eviction restricted to terminal records | Needs AC-3 first: eviction can only be safe once a finished scope is distinguishable from a blocked one. |
| **AC-3** non-workflow scopes reach terminal | `engine.run`'s existing `try/finally` | The run-record close already lives there (`executor.py:817-821`); the scope close is the same moment and the same guarantee. |
| **AC-4** growth is visible | `state show` reports both files | The defect's real cost was invisibility, not milliseconds. |
| **AC-5** purge finished, keep in-flight | AC-3 makes the existing `purge_scopes` work | No new purge logic — it already refuses non-terminal records correctly. |
| **AC-6** `scope_id` means one thing | null for a plain job, or documented | Decided in T6 against what the run log actually writes. |

### Surviving smells

Recorded because the architecture gate requires it, not because they are
acceptable everywhere:

1. **Two files now describe one run.** A scope's control data and its state are
   separate files, so a crash between the two writes can leave a record with no
   state file or a state file with no record. Mitigated by making the state file
   *derivable-as-empty* (a missing file reads as "no state", exactly as a missing
   `scopes.json` reads as "no scopes") and by deleting state **after** the
   record, never before. It is not eliminated. A single-file store with an index
   — `store-substrate`'s port — is what removes it properly, and this feature is
   deliberately not waiting for that.

2. **The cap is still per-file rather than a property of the pattern.** This
   adds a third hand-written limit beside `HISTORY_LIMIT` and `RUNS_LIMIT`
   instead of lifting the concept. Lifting it means touching all three stores,
   which belongs with `store-substrate`. Flagged rather than fixed.

3. **Two locks, and a caller can take them in either order.** Found by external
   review after implementation (`.spec/reviews/scope-state-review.md` Q2.3), and
   the strongest finding in it:

   ```
   T1: with state.batch():        # holds STATE lock
           rc.track_phase(...)    # -> record write -> wants SCOPES lock
   T2: with store.batch():        # holds SCOPES lock
           store.set_state(...)   # -> wants STATE lock
   ```

   Both are reachable from user code, and neither lock can be dropped without
   losing what it exists for. A global ordering cannot be imposed from inside
   the store, because the *caller* chooses which batch to open first. Mitigated
   rather than fixed: the record is ensured **before** the state lock is taken,
   so the inversion needs a record write *inside* a state batch; and both locks
   time out at 10 s and log audibly (`capability-duality`/T9), so this stalls
   and says so rather than hanging. The real fix is one store with one lock,
   which is smell #1's conclusion reached from a different direction.

4. **A batch held across `invoke_parallel` deadlocks.** The lock is held for the
   whole block, so every worker's `set` blocks on the holder while the holder
   waits on the workers. Pre-existing — the record batch had the same shape —
   but T3 moved which lock it is. Documented on `State.batch`, not prevented.

5. **`WorkflowScope.close()` remains the only terminal marker for a workflow**,
   and workflows reach it through the walk while plain jobs reach it through
   `engine.run`'s `finally`. Two paths to one state. Acceptable because both are
   `finally`-guaranteed and both call the same method, but it is two places to
   get wrong.

## C · Files to change

| file | change |
|---|---|
| `_primitives/scope_state_store.py` | **new** — per-scope state file, same lock discipline |
| `_primitives/scope_format.py` | `SCOPES_LIMIT`, terminal-only eviction, state-dir path |
| `_primitives/scope_store.py` | `*_state` methods delegate to the per-scope file |
| `_engine/capabilities/workflow_scope.py` | `close()` marks terminal |
| `_engine/executor.py` | `finally` closes a non-workflow scope (AC-3) |
| `_cli/builtins.py` | `state show` reports scope file size + count (AC-4) |
| `app/_workflow_control.py` | purge deletes the state file with the record |

## D · Risks

- **The one that matters: eviction must never touch a blocked workflow.** AC-2
  says so and it is the whole reason durable state exists. The cap is
  terminal-only, and a test asserts a blocked scope survives `SCOPES_LIMIT × 2`
  unrelated finished runs.
- **Migration.** Existing `scopes.json` files carry a `state` section. Read it
  if present (so an in-flight run resumes), write to the new location, and do
  not write the old section back. Pre-alpha, so no shim beyond that one read.
- **`_batch` is thread-local** (`scope_store.py:115-121`) and the new store must
  match, or a batch opened on one thread leaks into another.
