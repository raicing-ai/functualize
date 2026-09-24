# FUN-17 — Tasks

Refined 2026-09-23 against `1f3b760`. Sixteen tasks, eleven waves, **26 counting gates** (T16 and two T14 gates added 2026-09-24)
(20 as refined; T12 gained four with the install-moment decision, TD-1, 2026-09-24).

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
**24**. That is a disclosed transitional state for the life of the wave, not a regression —
do not "fix" it by loosening the assertion.

Running count as tasks are ticked: T1 `1` · T2 `2` · T3 `4` · T4 `6` · T5 `7` · T6 `8` ·
T7 `9` · T8 `10` · T9 `11` · T10 `12` · T11 `14` · T12 `20` · T13 `21` · T14 `24` ·
T16 `25` · T15 `26`.

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
actually do — `cross_aggregate_atomicity=False`, `fencing="cross-process"`,
`multi_process=False`, `multi_machine=False`, `durable_outbox=False`,
`versioned_migrations=False`, `interactive_transaction=True`, `remote=False`,
`max_document_bytes=None`, `offline_capable=True`.

Nine of those are the filesystem column of
`contributor/reference/substrate-capability-matrix.md` (`:79-88`), read row by row. **One
is not, and the divergence is the point of this task**: the matrix measures a *substrate*,
this profile describes three *stores* on one, and where they disagree the code wins.

- `fencing` is `"cross-process"` (matrix `:80`). Both of this store's refusal grounds are
  sourced from disk: `check_generation` compares against the lease read out of the loaded
  envelope (`scope_store.py:278-285`), and the write is
  `write(..., expect=revision)` regardless of any hold (`:294-305`) — "Compare-and-swap
  backs up the advisory lock" (`:271`). A stale lease holder in any process is refused.
- `multi_process` is `False` even though the matrix reads `yes · real` (`:81`). **This is
  the one field where the matrix is not the authority.** It measured `JsonFileSubstrate`;
  this profile also covers `RunStore`, which does **not** compare-and-swap — `_mutate`
  ends in `write(self._key, stamp_runs(envelope))` with no `expect=`
  (`run_store.py:189-192`, and `batch` at `:204-208`). Its only guard against a second
  process is the advisory lock, so a run record can be lost — accepted by design, because
  a run record "is history, not an in-flight run" (`:162-164`). One value covers three
  stores and takes the weakest.

Not an apology, and not the research's pre-measurement draft: that draft had **both**
fields weak, on grounds that FUN-24's repair and FUN-25's measurement have since answered.
Do not "restore" `fencing` to `"process-local"`.

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

### [x] T8 — a spanning transaction is refused, never applied in parts

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

### [x] T9 — `run_recorder.py`

*Files:* `src/functualize/_engine/recording/run_recorder.py`

Translates two lifecycle moments into `StartAttempt` / `FinishAttempt`. Thin: no decisions
of its own. A separate module, not twenty more methods on `JobExecutionEngine`, which is
already ~2580 lines against a ~500 threshold.

```bash
rg -c '^    def (started|finished)\(' src/functualize/_engine/recording/run_recorder.py
```
now: `0` · after: `2`

### [x] T10 — `workflow_recorder.py`

*Files:* `src/functualize/_engine/recording/workflow_recorder.py`

Translates four walk moments into `ClaimWorkflow` / `CompleteStep` / `SuspendAtGate` /
`ResumeWorkflow`.

```bash
rg -c '^    def (claimed|step_completed|suspended|resumed)\(' src/functualize/_engine/recording/workflow_recorder.py
```
now: `0` · after: `4`

---

## Wave 6 — the construction move

### [x] T11 — construct in `_app` after config resolves

*Files:* `src/functualize/_app/boot.py`, `src/functualize/_engine/executor.py`, `src/functualize/app/core.py`, `src/functualize/_primitives/document_store.py`, `tests/types/fixtures/runtime_store_conformance.py`, `tests/types/test_runtime_store_port.py`

Step 6.5: select and prepare one `RuntimeStore`, then build the engine with it. Both boot
paths move — `boot_static` at `:403` and `boot_standard` at `:622`. `prepare()` is allowed
to raise and nothing catches it; that is the whole of the B2 fix, and it does not change
what an `APP_READY` hook means.

`build_engine` takes **two** keyword-only arguments, `runtime_store` and `substrate`. The
second is not redundant: deleting the lazy property (T12) removes the engine's only source
for the `StoreSubstrate` that `FreshStore` (`executor.py:1544`) and `ScopeStore`
(`executor.py:1565`) still need, and D-9 keeps `StoreSubstrate` alive for exactly those.
Update the comment at `app/core.py:286`, which names the old signature.

The annotation half of those files is T11's because it is the same statement in the other
direction: T11 makes `boot.py:248` return a `DocumentRuntimeStore` where `RuntimeStore` is
declared, so the store has to *be* one — annotated against the port rather than the port
bent to it (`_types/persistence.py` is settled). `tests/types/test_runtime_store_port.py`
pins that in the shape of `tests/types/test_plugin_host_port.py`: runtime presence, mypy
signatures, and the port's members.

```bash
rg -c 'build_engine\(app\)$' src/functualize/_app/boot.py
```
now: `2` · after: `0`

```bash
rg -c 'runtime_store=store' src/functualize/_app/boot.py
```
now: `0` · after: `2`

## Wave 7 — delete the discovery

### [x] T12 — delete the discovery path, and prove it is gone

*Files:* `src/functualize/_engine/executor.py`, `tests/engine/test_engine_receives_its_store.py`;
widened by the install-moment decision (TD-1) to `src/functualize/_types/host.py`,
`src/functualize/app/core.py`, `src/functualize/_app/impl.py`, `src/functualize/_app/boot.py`,
`src/functualize/_plugins/loader.py`, `src/functualize/_primitives/substrate.py`,
`plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_plugin.py`,
`tests/conftest.py`, the four re-pointed tests (`tests/types/test_plugin_host_port.py`,
`tests/primitives/test_one_substrate_choice.py`,
`tests/plugins/test_substrate_choice_is_not_hook_order.py` ×2), a fifth re-point the
leader authorised on 2026-09-24 as D5's mechanical consequence
(`plugins/substrates/functualize-substrate-sqlite/tests/test_sqlite_substrate.py`: its two
registration tests asserted the `on_ready` handler D5 deletes, and now assert the offer —
same claims, no assertion weakened), and the new
`tests/plugins/test_substrate_offer.py` and `tests/primitives/test_substrate_root_is_lazy.py`.
The plugin's window is T12's because T12 is what closed the old one: deleting the engine's
lazy resolution moved the choice to step 6.5, which put `APP_READY` after it and left a
config-driven substrate plugin no moment that is both post-config and pre-selection.
`offer_substrate` is that moment (`contracts.md` §2.1, §5).

Acceptance criterion 4. Delete the `substrate` property at `executor.py:1509-1528`, the
`self._substrate` slot at `:242`, and the local `substrate_for_project` import. The engine
must have no path to a store it was not given.

*As landed (2026-09-24):* the property is deleted; the `_substrate` slot T11 re-purposed to
hold the *handed-in* substrate is not deleted but renamed to the plain attribute
`substrate`, because `app.substrate` (`app/core.py`) and three test files read
`engine.substrate` — one of them an AC-3 regression test that must stay unedited. The
import went with T11.

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

The install moment (TD-1). The port gains the offer door; the entry-point loader re-raises a
storage refusal by name; the shipped plugin stops installing from `APP_READY`; and the test
fixture that turned a location *query* into a `mkdir` stops doing so.

```bash
rg -c 'def offer_substrate' src/functualize/_types/host.py
```
now: `0` · after: `1`

```bash
rg -c 'except SubstrateInstallError' src/functualize/_plugins/loader.py
```
now: `0` · after: `1`

```bash
rg -c 'on_ready' plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_plugin.py
```
now: `1` · after: `0`

```bash
rg -c 'sandbox.mkdir' tests/conftest.py
```
now: `1` · after: `0`

---

## Wave 8 — refuse, never degrade

### [x] T13 — the capability check at selection time

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

### [x] T14 — the walk claims through the port

*Files:* `src/functualize/_engine/frontier.py`, `src/functualize/_engine/workflow_walker.py`, `src/functualize/_engine/workflow_runner.py`, `src/functualize/_engine/workflow_orchestrator.py`, `tests/engine/test_walk_claims_through_the_port.py`, and every test that constructs `FrontierWalk(`, `WorkflowWalker(` or `WorkflowRunner(` — the hit set of `rg -l 'FrontierWalk\(|WorkflowWalker\(|WorkflowRunner\(' tests/ plugins/` (16 files at `45eca37`; 22 / 89 / 26 call sites)

**Re-scoped 2026-09-24** (design ruling R-14.1, `plan.md` → *T14 rulings*). The first
version listed two files and was unexecutable: the port's only holder is
`executor.py:264`, and the walk is built four frames down from a bare `ScopeStore`
(`workflow_orchestrator.py:186` → `workflow_runner.py:196` → `workflow_walker.py:301`),
none of which were in scope. Acceptance criterion 6, walk half.

- **Route.** `FrontierWalk`, `WorkflowWalker` and `WorkflowRunner` each gain a
  **required keyword-only** `runtime_store: RuntimeStore`. No default: a defaulted
  storage argument is exactly what T12's tripwire exists to refuse. The orchestrator
  passes `runtime_store=self._engine._runtime_store`; each layer hands it down unchanged.
  The walk keeps its `ScopeStore` for every other write — only the claim moves.
- **`FrontierWalk.claim()`** builds its command with `WorkflowRecorder().claimed(...)`
  and issues it as a single-command transaction —
  `with runtime_store.transaction() as tx: outcome = tx.workflows.claim(cmd)` — and
  returns `Claimed | Conflict`. On `Claimed` it **must** call
  `self._store.hold(scope_id, outcome.generation)` and set `self._generation` before
  returning: the hold is per `ScopeStore` object (`scope_store.py:307-324`), the port
  claims through its own object, and a walk that skipped this would write with
  `held is None` — the generation fence silently off.
- **`WorkflowWalker.run()`** branches on the result **before** its `try`: on `Conflict`
  it returns `WalkReport(WalkOutcome.HELD, scope_id, error=…)` naming the holder and the
  held generation, and does **not** call `release()` — it never held the scope. `HELD` is
  a new `WalkOutcome` member (R-14.2), not `SUPERSEDED`.
- Test churn is mechanical and belongs here, not in a later task: a required argument
  that is not threaded through the tests is a red suite at tick. Build each test's port
  as `DocumentRuntimeStore(substrate)` over the **same substrate** as its `ScopeStore`,
  via one shared helper, so the lease the port writes is the lease the walk reads.

**The test that proves the fence survives the new arrival** —
`tests/engine/test_walk_claims_through_the_port.py`:

1. *Claimed keeps the fence on.* Walk claims through the port; a second runner
   force-reclaims on disk; the walk's next write raises `StaleGenerationError` and
   `run()` returns `SUPERSEDED`. **Sabotage:** delete the `hold(...)` call — the write
   must then land and this case must go red. That is the `self._generation is None`
   hazard at `workflow_walker.py:329`, made to fail loudly.
2. *Conflict never starts.* A live holder exists; `run()` returns `HELD` with the
   holder's name in `error`, executes no node, and leaves the holder's lease untouched.
3. *Reachability.* Break `runtime_store=` at `workflow_orchestrator.py` and an
   end-to-end workflow test goes red — the production call path, not "a test calls it".

```bash
rg -c 'LeaseHeldError' src/functualize/_engine/frontier.py
```
now: `1` · after: `0`

```bash
rg -c 'claim_scope\(' src/functualize/_engine/frontier.py
```
now: `1` · after: `0`

```bash
rg -c 'runtime_store=self\._engine\._runtime_store' src/functualize/_engine/workflow_orchestrator.py
```
now: `0` · after: `1`

### [x] T16 — the cancel stops proceeding unclaimed

*Files:* `src/functualize/app/_workflow_control.py`, `tests/workflow/test_cancel_wins_the_race.py`

**Split out of T14 2026-09-24** (design ruling R-14.3). Acceptance criterion 6, cancel
half — and it does **not** route through the port.

The cancel's claim is `force=True` (`_workflow_control.py:430-432`, and `reclaim_scope` at `:504`), and a forced claim
**cannot lose**: `lease.claim` refuses only `if … not force` (`lease.py:222-226`). So
no `Conflict` is reachable here, and an explicit `Conflict` branch would be dead code.
What the bare `except Exception:` actually swallows is a claim that *failed* — an
unreadable store, or eight CAS rounds lost to a live writer — after which the cancel
writes its status **unfenced**, and the running walk's `COMPLETED` stamp overwrites it.
That is the proceed-unclaimed behaviour the research names; it loses.

Delete the `try`/`except` so a failed forced claim propagates and the cancel is refused
loudly. Keep `store.claim_scope(..., force=True)` and the `hold`/restore dance as they
are. Its comment's "a store without leases still cancels" has no production subject:
the only caller is `_cli/builtins.py:1774`, whose `_workflow_store(ctx)` is a
`ScopeStore` on the app's own substrate — so the lease it takes is on the same disk the
app's `RuntimeStore` reads, and **no wrapping is needed for correctness**. Before
ticking, run `rg -n 'cancel_scope\(' tests/` (10 sites) and confirm none passes a
lease-less fake store expecting the old silence; add a case where the forced claim
raises and assert the scope's status is **not** `cancelled`.

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
now: `13` · after: `16`

```bash
uv run pytest tests/spec/test_task_gates_still_hold.py -q --no-header
```
expects: green, with 26 gates parsed — comfortably past the suite's threshold of 12.

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
    { "id": 9,  "tasks": ["T14", "T16"] },
    { "id": 10, "tasks": ["T15"] }
  ]
}
```
