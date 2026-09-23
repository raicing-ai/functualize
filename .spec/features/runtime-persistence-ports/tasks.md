# FUN-17 — Tasks

Refined 2026-09-23 against `1f3b760`. Fifteen tasks, eleven waves, **20 counting gates**.

Each task is 1–3 files and completable in one context window. Wave ordering is binding:
never start a task in wave N+1 while wave N has unchecked tasks.

## How to read a gate

Every task carries at least one fenced `bash` block whose command is a **count**, followed
immediately by the value it returns today and the value the task must make it return.
Both numbers below were produced by **running the command on this branch** at authoring
time; none is estimated.

A gate is only re-run by `tests/spec/test_task_gates_still_hold.py` once its task is
ticked, and it is then re-run against HEAD for the rest of the wave. **Every gate here was
chosen to stay true to the end of the wave**, not only at its own task. If you must weaken
one, say so in writing and mark it, per `.spec/CONSTITUTION.md` → *Transitional Changes*.

## Why this suite is red until T15

`tests/spec/test_task_gates_still_hold.py::test_the_parser_actually_found_gates` asserts
that **at least 12** gates parse, and only gates belonging to `[x]` tasks parse at all.
`.spec/features/` on this branch holds one feature, so no other feature's gates back-stop
the count. It therefore reads `0` today, reaches 12 when T10 is ticked, and finishes at
**20**. That is a disclosed transitional state for the life of the wave, not a regression —
do not "fix" it by loosening the assertion.

Running count as tasks are ticked: T1 `1` · T2 `2` · T3 `4` · T4 `6` · T5 `7` · T6 `8` ·
T7 `9` · T8 `10` · T9 `11` · T10 `12` · T11 `14` · T12 `16` · T13 `17` · T14 `19` ·
T15 `20`.

---

## Wave 0 — the vocabulary

### [x] T1 — `StoreProfile`, all ten measured fields

*Files:* `src/functualize/_types/persistence.py`

New module, stdlib imports only. Frozen dataclass with two labels (`name`, `description`)
and the ten fields in the order `contributor/reference/substrate-capability-matrix.md`
uses. `fencing` takes the matrix's own three values; `max_document_bytes` is `int | None`
where `None` means "nothing refused what was attempted". Do not re-derive any value from
vendor documentation — the matrix is the authority.

```bash
rg -c '^    (cross_aggregate_atomicity|fencing|multi_process|multi_machine|durable_outbox|versioned_migrations|interactive_transaction|remote|max_document_bytes|offline_capable): ' src/functualize/_types/persistence.py
```
now: `0` · after: `10`

The pattern anchors on a four-space indent and a type annotation, so a field mentioned in
the docstring does not count. A `StoreProfile` that ships nine fields fails this.

### [x] T2 — the eight commands

*Files:* `src/functualize/_types/persistence.py`

`ClaimWorkflow`, `CompleteStep`, `SuspendAtGate`, `ResumeWorkflow`, `CancelWorkflow`,
`StateBatch`, `StartAttempt`, `FinishAttempt`. Frozen dataclasses, values only. Every
command that mutates a scope carries the held generation.

```bash
rg -c '^class (ClaimWorkflow|CompleteStep|SuspendAtGate|ResumeWorkflow|CancelWorkflow|StateBatch|StartAttempt|FinishAttempt)\b' src/functualize/_types/persistence.py
```
now: `0` · after: `8`

### [x] T3 — the six outcomes and the six views

*Files:* `src/functualize/_types/persistence.py`

Outcomes: `Claimed`, `Conflict`, `Resumed`, `CancelResult`, `Attempt`, `InputRequest`.
`Conflict` names the holder and the held generation. Views and queries: `RunView`,
`WorkflowView`, `EventView`, `RunTree`, `RunQuery`, `WorkflowQuery`.

```bash
rg -c '^class (Claimed|Conflict|Resumed|CancelResult|Attempt|InputRequest)\b' src/functualize/_types/persistence.py
```
now: `0` · after: `6`

```bash
rg -c '^class (RunView|WorkflowView|EventView|RunTree|RunQuery|WorkflowQuery)\b' src/functualize/_types/persistence.py
```
now: `0` · after: `6`

---

## Wave 1 — the writer and reader ports

### [x] T4 — five writer protocols, and `claim` as an outcome

*Files:* `src/functualize/_types/persistence.py`

`RunWriter`, `WorkflowWriter`, `InputWriter`, `EventWriter`, `EffectWriter` — all
`@runtime_checkable Protocol`, no ABC. Writers take commands and return `None`, with one
exception: `WorkflowWriter.claim` returns `Claimed | Conflict`, because it is specified as
a single-command transaction that commits on the spot. That is acceptance criterion 6 at
the port; T14 makes it reachable.

```bash
rg -c '^class (RunWriter|WorkflowWriter|InputWriter|EventWriter|EffectWriter)\(Protocol\):' src/functualize/_types/persistence.py
```
now: `0` · after: `5`

```bash
rg -c ' -> Claimed \| Conflict:' src/functualize/_types/persistence.py
```
now: `0` · after: `1`

The second gate counts the **annotation**, in signature position. Keep that exact spelling
out of prose in this file or the count moves.

### [x] T5 — three reader protocols

*Files:* `src/functualize/_types/persistence.py`

`RunReader` (`run`, `recent`, `tree`), `WorkflowReader` (`workflow`, `resumable`,
`events_after`), `InputReader`. Named for questions, never `get`/`list`/`find`: a backend
may answer `resumable()` from an index, and a caller must never discover that by
`hasattr`.

```bash
rg -c '^class (RunReader|WorkflowReader|InputReader)\(Protocol\):' src/functualize/_types/persistence.py
```
now: `0` · after: `3`

---

## Wave 2 — the store and its buffering transaction

### [x] T6 — `RuntimeStore` and `RuntimeTransaction`

*Files:* `src/functualize/_types/persistence.py`

`RuntimeStore` exposes `profile`, the three readers, `transaction()` and `close()`.
`close()` is new and is the fix for `SQLiteSubstrate` caching a connection per thread with
nothing to close them.

`RuntimeTransaction` **accumulates**. A writer call appends a command and issues nothing;
`__exit__` applies the batch as one unit on a clean exit and discards it otherwise. This is
acceptance criterion 1, and it is a requirement rather than an implementation choice:
Cloudflare D1 has no interactive transaction (`substrate-capability-matrix.md`,
`interactive_transaction` row, `no · real`), so a streaming port is not implementable
there at all. Say so in the module docstring.

```bash
rg -c '^class (RuntimeStore|RuntimeTransaction)\(Protocol\):' src/functualize/_types/persistence.py
```
now: `0` · after: `2`

---

## Wave 3 — the document adapter

### [x] T7 — `DocumentRuntimeStore` and an honest profile

*Files:* `src/functualize/_primitives/document_store.py`

Wraps today's `ScopeStore`, `RunStore` and `ScopeStateStore` and declares what they
actually do — `cross_aggregate_atomicity=False`, `fencing="process-local"`,
`multi_process=False`, `multi_machine=False`, `durable_outbox=False`,
`versioned_migrations=False`, `interactive_transaction=True`, `remote=False`,
`max_document_bytes=None`, `offline_capable=True`. Those are the filesystem column of the
matrix, not an apology.

It lives in `_primitives` because that is where the three stores it wraps live; putting it
in `_engine` would place storage adaptation in the layer that owns lifecycle meaning.
Mark the class `# TRANSITIONAL(FUN-17/T7)`: it is a declared *middle man* that FUN-19's
`SqliteRuntimeStore` removes.

```bash
rg -c '^    (cross_aggregate_atomicity|fencing|multi_process|multi_machine|durable_outbox|versioned_migrations|interactive_transaction|remote|max_document_bytes|offline_capable)=' src/functualize/_primitives/document_store.py
```
now: `0` · after: `10`

---

## Wave 4 — the refusal

### [ ] T8 — a spanning transaction is refused, never applied in parts

*Files:* `src/functualize/_types/errors.py`, `src/functualize/_primitives/document_store.py`, `tests/primitives/test_document_runtime_store.py`

Acceptance criterion 2. A store declaring `cross_aggregate_atomicity=False` raises
`CrossAggregateRefusedError` **on commit**, naming both aggregates, having applied
neither. Applying it in parts is defect B3 with a new name, so the test must assert the
second aggregate is untouched — not merely that an exception was raised.

```bash
rg -c '^class CrossAggregateRefusedError' src/functualize/_types/errors.py
```
now: `0` · after: `1`

```bash
uv run pytest tests/primitives/test_document_runtime_store.py -q --no-header
```
expects: green, with a case that reads both aggregates back and finds neither written.

---

## Wave 5 — the recorders

### [ ] T9 — `run_recorder.py`

*Files:* `src/functualize/_engine/recording/run_recorder.py`

Translates two lifecycle moments into `StartAttempt` / `FinishAttempt`. Thin: no decisions
of its own. A separate module, not twenty more methods on `JobExecutionEngine`, which is
already ~2580 lines against a ~500 threshold.

```bash
rg -c '^    def (started|finished)\(' src/functualize/_engine/recording/run_recorder.py
```
now: `0` · after: `2`

### [ ] T10 — `workflow_recorder.py`

*Files:* `src/functualize/_engine/recording/workflow_recorder.py`

Translates four walk moments into `ClaimWorkflow` / `CompleteStep` / `SuspendAtGate` /
`ResumeWorkflow`.

```bash
rg -c '^    def (claimed|step_completed|suspended|resumed)\(' src/functualize/_engine/recording/workflow_recorder.py
```
now: `0` · after: `4`

---

## Wave 6 — the construction move

### [ ] T11 — construct in `_app` after config resolves

*Files:* `src/functualize/_app/boot.py`, `src/functualize/_engine/executor.py`, `src/functualize/app/core.py`

Step 6.5: select and prepare one `RuntimeStore`, then build the engine with it. Both boot
paths move — `boot_static` at `:403` and `boot_standard` at `:622`. `prepare()` is allowed
to raise and nothing catches it; that is the whole of the B2 fix, and it does not change
what an `APP_READY` hook means.

`build_engine` takes **two** keyword-only arguments, `runtime_store` and `substrate`. The
second is not redundant: deleting the lazy property (T12) removes the engine's only source
for the `StoreSubstrate` that `FreshStore` (`executor.py:1544`) and `ScopeStore`
(`executor.py:1565`) still need, and D-9 keeps `StoreSubstrate` alive for exactly those.
Update the comment at `app/core.py:286`, which names the old signature.

```bash
rg -c 'build_engine\(app\)$' src/functualize/_app/boot.py
```
now: `2` · after: `0`

```bash
rg -c 'runtime_store=store' src/functualize/_app/boot.py
```
now: `0` · after: `2`

## Wave 7 — delete the discovery

### [ ] T12 — delete the discovery path, and prove it is gone

*Files:* `src/functualize/_engine/executor.py`, `tests/engine/test_engine_receives_its_store.py`

Acceptance criterion 4. Delete the `substrate` property at `executor.py:1509-1528`, the
`self._substrate` slot at `:242`, and the local `substrate_for_project` import. The engine
must have no path to a store it was not given.

**Reachability precedes `[x]`**, and for a deletion the proof runs the other way: the
tripwire test must fail if construction without a store becomes possible again. Commit
first, then sabotage — re-add a defaulted `runtime_store=None` and watch the tripwire go
red — then restore. `git checkout -- <file>` reverts everything uncommitted in that file.

Also pin the behaviour change `contracts.md` §5 names: a plugin installing a substrate at
`APP_READY` now does so after the engine is wired.

```bash
rg -c 'substrate_for_project' src/functualize/_engine/executor.py
```
now: `3` · after: `0`

```bash
rg -c 'substrate_override' src/functualize/_engine/executor.py
```
now: `2` · after: `0`

---

## Wave 8 — refuse, never degrade

### [ ] T13 — the capability check at selection time

*Files:* `src/functualize/_types/errors.py`, `src/functualize/_app/boot.py`, `tests/core/test_store_capability_refusal.py`

Acceptance criterion 3, second half. `check_required_capabilities(store.profile, config)`
runs at step 6.5 and raises `RuntimeStoreCapabilityError` naming the **store**, the
**field** and the **config key**. It never falls back to a weaker store — a silent
downgrade is the failure mode `StoreProfile` exists to make impossible.

```bash
rg -c '^class RuntimeStoreCapabilityError' src/functualize/_types/errors.py
```
now: `0` · after: `1`

---

## Wave 9 — losing a claim becomes a value

### [ ] T14 — the outcome reaches production code

*Files:* `src/functualize/_engine/frontier.py`, `src/functualize/app/_workflow_control.py`

Acceptance criterion 6, completed. T4 declared `Claimed | Conflict`; a declared port that
nothing calls is a built-but-unwired capability, which the constitution's reachability rule
exists to catch. Both call sites route through `WorkflowWriter.claim` and branch on the
result:

- `frontier.py:183` — `claim()` stops documenting `LeaseHeldError` and stops propagating
  it; it returns the outcome.
- `app/_workflow_control.py:430-439` — the bare `except Exception:` around the cancel's
  borrowed claim is replaced by an explicit `Conflict` branch. That catch is a recorded
  hazard in this very file (`:420-424` explains a defensive lookup that hid a real break);
  do not leave a second one behind.

Name the production call path for each, and verify by breaking the call and watching a test
fail. "A test calls it" is not a call path.

```bash
rg -c 'LeaseHeldError' src/functualize/_engine/frontier.py
```
now: `1` · after: `0`

```bash
rg -c 'except Exception:' src/functualize/app/_workflow_control.py
```
now: `1` · after: `0`

---

## Wave 10 — close the wave

### [ ] T15 — the layer proof, and the gate count

*Files:* `tests/types/test_persistence_port_imports.py`, `.spec/features/runtime-persistence-ports/tasks.md`

Acceptance criterion 5. Run `uv run lint-imports` — seven contracts, zero violations. That
is necessary and **not sufficient**: `exclude_type_checking_imports = true` means a
deferred `_types → _app` import still reports "7 kept, 0 broken"
(`contributor/architecture/codemaps/dependencies.md:37`, measured by adding one). Add an
import-line test over `_types/persistence.py` in the shape of
`tests/types/test_plugin_host_port.py`, which already guards that blind spot.

Then tick this task and confirm the gate suite has crossed its threshold.

```bash
rg -c '^### \[x\] T' .spec/features/runtime-persistence-ports/tasks.md
```
now: `0` · after: `15`

```bash
uv run pytest tests/spec/test_task_gates_still_hold.py -q --no-header
```
expects: green, with 20 gates parsed — comfortably past the suite's threshold of 12.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0,  "tasks": ["T1", "T2", "T3"] },
    { "id": 1,  "tasks": ["T4", "T5"] },
    { "id": 2,  "tasks": ["T6"] },
    { "id": 3,  "tasks": ["T7"] },
    { "id": 4,  "tasks": ["T8"] },
    { "id": 5,  "tasks": ["T9", "T10"] },
    { "id": 6,  "tasks": ["T11"] },
    { "id": 7,  "tasks": ["T12"] },
    { "id": 8,  "tasks": ["T13"] },
    { "id": 9,  "tasks": ["T14"] },
    { "id": 10, "tasks": ["T15"] }
  ]
}
```
