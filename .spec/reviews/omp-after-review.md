# AFTER review — `capability-duality` and `durable-run-layer` T1/T2

**Reviewed revision: `d7a01c4`** (`feat(engine): rc[T] and `T in rc` consult the capability map first (T4)`).

> **The worktree moved while I reviewed it.** HEAD advanced twice during this
> session (`cfcfe20` → `a50a53e` → `d7a01c4`), and at review time six files were
> modified but uncommitted (`invoke.py`, `log.py`, `runcontext.py`, `spec.py`,
> `state.py`, `tests/integration/test_capability_duality.py`). Every line number
> and every "nothing does X" below is verified against **`d7a01c4`** (via
> `git show d7a01c4:<path>`), so it is reproducible. The uncommitted work appears
> to be T6 (a `shared_with_rc` exemption field on `CapabilitySpec` plus a
> `CAPABILITY_SPECS`-driven test) — I have **excluded it from judgement**; it is
> not part of the AFTER I am reviewing, and F4 below describes the committed
> state only.

---

## Verdict

The core decision is sound and the code mostly does what the prose says. `State`
really is one class behind both doors, it really is durable, and it really
survives a new process — I verified all three by running them. The parallel-
versus-sequential scope split is coherent, deliberate, and pinned by tests.

Three things are wrong, in order of how much they matter:

1. **Putting job state inside the scope record made every `rc.state` read and
   write O(project age).** Measured on this worktree's own `scopes.json`
   (1.0 MB, ~2,200 records): `set` 58 ms, `get` 11.7 ms, against 0.28 ms /
   0.10 ms on a fresh file. The file is uncapped, and the records inflating it
   cannot be purged. The handoff justifies the design with "0.557 ms per
   unbatched `set`" — a number measured on an empty store.
2. **`ScopeStore.batch()` is not thread-safe, and the objects it guards are now
   shared by up to 32 workers.** I reproduced a silently discarded write: a
   completing thread's `set_state` is folded into another thread's open batch
   and vanishes if that batch raises.
3. **The enforcement story is prose.** ADR-021 and AC-6 claim a test
   parametrized over `CAPABILITY_SPECS` with exemptions declared in the
   registry. At `d7a01c4` there is no `parametrize`, no `skip`, no
   `CAPABILITY_SPECS` import, and no exemption field. The prose is the suspect.

Nothing here argues for reverting the feature. Two of the three are fixable in a
focused change; the first needs its own.

---

## Findings

### F1 · HIGH · verified · **large** — job state rides an uncapped file, and every state op re-reads all of it

`src/functualize/_primitives/scope_store.py:60-84` (`_blank_scope` gains `"state": {}`),
`scope_store.py:236-262` (`get_state`/`set_state`), `src/functualize/_primitives/scope_format.py` (no cap).

T2 moved a run's state into the scope record. The scope file is the **only one of
the three with no ring cap**:

```
state_format.py:69   HISTORY_LIMIT = 200
run_format.py:65,69  EVENTS_PER_RUN_LIMIT = 200, RUNS_LIMIT = 500
scope_format.py      (nothing — rg "LIMIT|_trim|prune|evict" returns no match)
```

and every state operation is a whole-file read-modify-write — `get_state` calls
`get_scope` → `_read()` → `load_scopes`, a full parse. Measured, on a copy of the
real file and on an empty one:

```
real project scopes.json: 1019 KB, 2188 scope records
  on the real 1.0 MB file : unbatched set 58.16 ms | 100 in batch 55.58 ms | get 11.75 ms
  on a fresh/empty file   : unbatched set  0.28 ms | 100 in batch  0.81 ms | get  0.10 ms
```

That is ~200×, and the cost is proportional to how many runs the project has
accumulated — not to what the job stores. The handoff's defence of deleting the
in-memory double reads "measured, this store costs **0.557 ms** per unbatched
`set`" (`.spec/features/capability-duality/STATUS-HANDOFF.md:93`); that figure is
an empty-store figure and does not survive contact with a project that has run
2,000 jobs.

Worse, the records that inflate the file cannot be removed. A non-workflow scope
carries `status: "running"` (verified: a plain job calling `rc.state.set` leaves
`{'status': 'running', 'workflow': None, 'state': {'k': 1}}`), so:

- `derived_state` returns `"running"` (`src/functualize/app/_workflow_view.py:107-108`);
- `purge_scopes` skips it — `if current not in TERMINAL_STATES: continue`
  (`src/functualize/app/_workflow_control.py:439-441`), and the age filter skips
  it again for having no timestamps;
- `list_scopes` hides it (`_workflow_view.py:174`, commit `a7fb91d`), so the
  growth is invisible to the user it is happening to.

The one escape hatch is `func builtin state clear --scopes`, which moves the
whole file aside — it discards every in-flight run too.

*Note on the measurement:* this worktree's `scopes.json` is test residue (T10,
unfixed — F9), so 2,200 records is inflated. The **mechanism** is production
behaviour: one record per run that touches state, no cap, no purge path for the
non-workflow ones.

*Why it matters:* the feature's headline claim is that state is durable. Durable
state that costs 58 ms per write once a project is a few months old, and grows
without bound, is a different trade from the one the spec describes.
*Small or large:* **large.** Needs its own change — mark non-workflow scopes
terminal at run end, add a cap/compaction, or move job state out of the scope
file. `store-substrate` and the held T3b gesture at this but neither owns it, and
neither mentions the uncapped file.

---

### F2 · HIGH · verified (reproduced) · **small-ish** — `batch()`'s state is per-object, not per-thread, on an object shared by 32 workers

`src/functualize/_primitives/scope_store.py:131-153` (`_batch`, `batch()`), `:118-129` (`_read`/`_mutate`).

`ScopeStore.batch()` sets `self._batch` on the instance, and `_mutate` sends
*any* write on that instance into the open batch. The same object is now shared
across worker threads: `invoke.py:700` passes `parent_scope=self._workflow_scope`
to every parallel item, and `_scope_for` caches one `WorkflowScope` per scope id
(`executor.py:851-866`) — so all 32 items share one `WorkflowScope`, one
`ScopeBackedStateStore`, one `ScopeStore`, one `_batch`.

Reproduced, deterministically:

```
clean batch exit  : {'main': 1, 'sibling': 2}
batch raises      : {}
```

The sibling thread's `set_state` **returned successfully** and its value is gone.
No error, no warning — and per F1 this is the primitive the feature routes all
user state through. The same mechanism makes `_read()` return another thread's
uncommitted writes (phantom reads) and makes a second `with state.batch():` block
a silent no-op that rides the first.

*Why it matters:* a lost write is the exact failure class the durable-state
change exists to remove; this reintroduces it one layer down, only now it needs
concurrency and an exception.
*Small or large:* **small** in code (thread-local batch + a lock, or a per-batch
lock object), but it is a correctness fix in a primitive, so it wants its own
test.

### F3 · MEDIUM · verified (reproduced) · **small** — `engine.run()` cannot fail to close its run record

`src/functualize/_engine/executor.py:779-806` (`run`), `:869-923` (`_open_run_record`, `_close_run_record`).

Open and close are two unguarded statements around `_execute_lifecycle`. If the
lifecycle raises, the record stays `running` forever:

```
DEMO2 lifecycle raised out of engine.run: kaboom
{ "run_id": "run-01M27PBKN2D40ECMDYTQJ8DJB8", "status": "running",
  "ended_at": null, "scope_id": "job-a229ab0b", ... }
```

`_execute_lifecycle` does contain raising paths that `run()` does not catch —
`except MissingProviderError: raise` (`executor.py:1205-1206`), `raise
DIValidationError` (`:1125`). A job body raising is fine (caught by `except
BaseException` at `:2543` and turned into a FAILURE result); the uncaught paths
are the ones outside that try. Nothing reaps the result: the lease/abandoned
branch is T5, not built, and `derived_state` has no `abandoned` case.

*Why it matters:* US-1 is "I can see what a run is doing now". A record that says
`running` forever answers that question wrongly, and F1 shows how such records
accumulate.
*Small or large:* **small** — `try/finally` around the lifecycle, closing as
`failed` on the way out.

---

### F4 · MEDIUM · verified · **small** — the enforcement mechanism AC-6 and ADR-021 describe does not exist

`contributor/adr/021-capability-duality.md:106` ("is therefore parametrized over
`CAPABILITY_SPECS`"), `:116` ("the test skips it by that declaration"),
`.spec/features/capability-duality/spec.md:75` (AC-6), `tests/integration/test_capability_duality.py`.

At `d7a01c4`: `rg "CAPABILITY_SPECS|parametrize|skip"` over the duality test
returns **nothing**; the file is 8 hand-written classes and 23 test functions;
`CapabilitySpec` (`spec.py:120-134`) has `name`, `type`, `factory`,
`per_invocation`, `preflight_bind` and no exemption field. ADR-021's closing
argument — that the rule is enforced by a registry-driven test because "a third
prose rule would fail the same way" — rests on a test that is itself prose-shaped.

*Why it matters:* this is the ADR's central claim, not a detail. Read as
"the rule is now executable", which is how it reads, it is false; the coverage
is hand-maintained and can be forgotten exactly as `Perf` was.
*Small or large:* **small** as a change. (In-flight in the working tree, per the
header — not judged here.)

### F5 · MEDIUM · verified · **medium** — the "sealed on close" guarantee has no production caller, and two caches grow for process life

`src/functualize/_engine/capabilities/state.py:86-96` (`_close`, `_check_open`),
`src/functualize/_engine/capabilities/workflow_scope.py:135-151` (`close`),
`executor.py:242` (`_scopes`), `executor.py:1987` (`forget_live_step_values`).

`git grep "\.close()" d7a01c4 -- src/` finds no call on a scope anywhere in
production — the only hit for `WorkflowScope.close()` is a docstring reference
(`state.py:89`). So `ScopeBackedStateStore._check_open`'s promise, quoted from
the code, "once a scope is finished, a late write from a straggling thread must
fail loudly rather than mutate a record something already read as final"
(`state.py:90-92`), is a guarantee nothing in the shipped paths can reach. Tests
exercise it; production cannot.

Related: nothing removes from `engine._scopes` (assignments only, `:851-866`,
no `pop`/`clear`) or from `app._scope_registry`, and `forget_live_step_values`
(`executor.py:1987`) is defined and **never called** — so `_live_step_values`
accumulates one dict per scope id forever.

*Why it matters:* in a long-lived process (the MCP server, the TUI) both caches
grow with every run; and a documented safety property that cannot fire is worse
than one that does not exist, because a reviewer will assume it is holding.
*Small or large:* **small** for the dead method and the eviction; the missing
close needs a decision about where a run ends.

### F6 · MEDIUM · verified · **small** — the run record's `scope_id` is non-null for plain jobs, and often names nothing

`executor.py:832` (`_ensure_scope` mints a scope id for every run),
`executor.py:897` (`"scope_id": request.workflow_scope_id`), spec
`.spec/features/durable-run-layer/schema.md:39` (`"scope_id": "wf-01H…", // when
the run is a workflow, else null`).

Reproduced: a plain `app.execute` produced `"scope_id": "job-a229ab0b"`. And
because the scope *record* is written lazily — by `set_state`'s
`setdefault(scope_id, _blank_scope())` (`scope_store.py:252-260`) — the id
frequently refers to a scope that does not exist. A quiet job leaves one run
record and no scope record at all:

```
runs.json   : 2 run records
scopes.json : {'touchy-f453460d': {'status': 'running', 'workflow': None, 'state': {'k': 1}}}
```

The record also lacks schema §2's `generation` field (verified key list:
`args_hash, ended_at, force, group_option_values, invoke_depth, job,
parent_run_id, run_id, runner, scope_id, started_at, status, surface`).

*Why it matters:* `scope_id` is documented as the join between the run log and
the scope file. Today it is a per-run id that the scope file may never have
heard of, so the join is unsound for everything that is not a workflow — and the
one that *is* a workflow records it correctly, which is precisely the case that
will make the bug look fixed.
*Small or large:* **small** — write `null` for a non-workflow run, or write the
scope record at `_ensure_scope` and mark it as a non-workflow scope (see F1).

### F7 · MEDIUM · verified · **medium** — the run log is built, tested, reachable — and connected to nothing that reads it

`executor.py:869-923` (both halves), `src/functualize/_primitives/run_store.py` (the whole class),
`src/functualize/_primitives/run_format.py`.

`src/` contains exactly two `RunStore` call sites, both inside `_open_run_record`
/ `_close_run_record`. There is **no reader**: no caller of `get_run`,
`run_ids`, `recent_runs`, `children_of`, `events_for`; **no** caller of
`append_event` anywhere in `src/`; no `func builtin run` in `BUILTIN_COMMANDS`;
nothing in `_app/` or `_cli/` references `runs.json` or `RUNS_VERSION`.

This is deliberate — T3/T4 are unstarted (`durable-run-layer/tasks.md`) — and the
run *format* is thoughtful: independent version, discard-on-unusable
(`run_format.py:95-126`), caps on both rings, a monotonic ULID with a
backwards-clock rule (`run_store.py:56-95`), and a trim that distinguishes an
evicted run from a never-seen one. But the cost is on the job-launch path today,
for data nothing consumes. Measured at the 500-record cap (266 KB):

```
open_run 6.53 ms  close_run 6.25 ms  -> 12.78 ms of serialized full-file I/O per run
32-way batch therefore pays about 0.4 s of lock-serialized writes just to open+close records
```

Forward risk for T4: `append_event` is one more locked full-file rewrite *per
event*, up to `EVENTS_PER_RUN_LIMIT` (200) per run. `RunStore.batch()` exists for
exactly this and has no caller.

*Why it matters:* it is a fourth instance of the wiring-discipline shape — built,
tested (27 tests in `tests/primitives/test_run_store.py`), reachable, and
connected to nothing that reads it. That is legitimate *as a declared mid-
sequence state*; what it is not is free.
*Small or large:* the reader is T3 (its own work). The decision to record every
nested and parallel run at ~13 ms each is the thing to re-affirm before T4.

### F8 · LOW-MEDIUM · verified · **small** — two `rc` accessors sit outside the duality rule, undeclared

`src/functualize/_engine/capabilities/prompt_facade.py:58-66` and
`discovery_facade.py:47-48, 71-76` resolve through `self._rc._execution_engine.host`,
not through `_cap_or_none`. ADR-021's exemption table lists five classes and
`Prompt` is not among them, while its audit table records `Prompt` and `Sources`
as sharing "no".

I could not find **observable** divergence: the injected `Prompt` factory is
`Prompt()` (`prompt.py:157`) and it too resolves the collector from the surface
stack at call time, so both doors end at the same collector. So this is an
enforcement and documentation gap, not a live defect.
*Why it matters:* only because the tripwire AC-6 asks for must decide about these
two, and nothing currently records the decision.
*Small or large:* **small** — two rows in the exemption table, or two tests.

### F9 · LOW · verified · **small** — the ledger contradicts itself, and T10's cost is measurable in this worktree

`STATUS-HANDOFF.md:3` ("**GREEN as of 2026-09-11**"), `:34` (lists `T4 … not
started`, though `d7a01c4` implements T4), `:103` ("**T10 is real and unfixed**"),
`tasks.md` T6–T10.

Unmet at `d7a01c4`, each with the gate its own task named:

| task | evidence |
|---|---|
| T7 | `examples/standalone/composition_lab/jobs/pipeline.py:193` still says "That is the trap this job pins.", and the worker docstring still says "Its `State` is its own." |
| T8 | `_primitives/state_store.py:58` is still `class StateStore`; no `RuntimeStore` anywhere in `src/` |
| T9 | `state_format.py:277` is still the bare `return  # advisory: proceed rather than deadlock a build`; no warning in the module |
| T10 | `tests/conftest.py` has three autouse fixtures (`:214`, `:234`, `:254`); none redirects the state root |

T10's cost, measured in this worktree at review time: `scopes.json` 1,030,460 B /
2,158 records, `runs.json` 274,938 B / 500 runs, `state.json` 51,410 B / 200
history records — ~1.3 MB of residue, still growing while I read it. Gitignored,
so nothing was committed; it is also what makes F1's absolute numbers as large as
they are.
*Small or large:* **small** each; T10 is the one with a deadline, because until it
lands no measurement of this store is trustworthy (F1) and no flaky failure can
be attributed.

### F10 · LOW · verified · **medium** — `StateStore` is a 25-method middle man, and a fourth copy of the protocol's method list

`src/functualize/_primitives/state_store.py:130-260` (25 `return self._scopes.…`
bodies), `src/functualize/_engine/capabilities/workflow_scope.py:110-121`.

The class both owns a `ScopeStore` (`:71`) and forwards 25 methods to it
verbatim. That is a middle man and a divergent-change hotspot: any scope-record
change is two edits in lockstep, and the two classes share a file but not the
lock object. It is disclosed (`STATUS-HANDOFF.md:112`) and owned by
`store-substrate`. Separately, `replace_state_store` hard-codes the eight
required method names rather than deriving them from `StateStoreProtocol`
(`protocols.py:26-63`) — a fourth transcription of the same list
(`protocols.py`, the state facade, this check, and the plugin).
*Small or large:* **medium** — it is the substrate refactor, already planned.
The duplicated method list is **small**.

### F11 · LOW · verified · **small** — the namespace API the ADR decided not to build was built

`src/functualize/_engine/capabilities/state.py:141-147` (`get_job_state`,
`list_job_namespaces`), `protocols.py:50,63`.

ADR-021: "the `"fetch.count"` key convention is **documented rather than built**,
because a framework namespace is a second concept for something a string prefix
already does" (`021-capability-duality.md:119-121`; spec.md §B decision 1 says
the same). `get_job_state("fetch", "rows")` *is* a framework namespace accessor,
and `list_job_namespaces()` exists to enumerate the namespaces. Verified: neither
is called anywhere in `src/` or `examples/`; they are exercised only by
`tests/context/test_state_store_protocol.py`.
*Why it matters:* it is speculative generality carrying a doc contradiction, and
it is in `StateStoreProtocol`, so a plugin must implement two methods the design
says should not exist.
*Small or large:* **small** to delete, once the protocol decision is made (which
makes it a plugin-contract change, hence not purely local).

### F12 · LOW · **suspected** · **small** — a nested `scopes_lock` in one process self-deadlocks, then proceeds unlocked

`state_format.py:240-280` (`scopes_lock`/`_acquire_lock`), `:277` (the silent
give-up), `state_store.py:71` and `executor.py:862` / `impl.py:644`.

Each `scopes_lock` call opens a **new** fd on the sidecar, so a second
acquisition inside a held window blocks — for the 10 s timeout — and then
proceeds **without the lock** (`state_format.py:277`), after which its write is
based on a read that predates the outer batch, and the outer batch's
`save_scopes` then clobbers it. Two `ScopeStore` objects for one file *are* live
at once (`state_store.py:71` for the walker's `StateStore`, `executor.py:862` for
the engine's).

I traced all four `scope_batch` call sites — `frontier.py:101,141,195` and
`workflow_walker.py:535` — and every one is a record-only window; no job body
runs inside them, so I could not reach the nesting. Reported as a latent hazard
with the mechanism named, not as a live bug. It is the reason T9's "make the
timeout non-silent" is worth doing for *in-process* contention and not only
cross-process.
*Small or large:* **small** — a warning at `:277` (T9) would make it
self-diagnosing.

---

## What is genuinely fine

- **AC-2 holds, empirically.** `state is rc.state` is `True` in both parameter
  orders, and state set by a parent is visible to an `rc.invoke` child:
  `{'state_first': True, 'rc_first': True, 'rc_sees_it': 1, 'child_store': 7}`.
  (The committed test asserts `State in rc` and value carry-over but **no
  identity** — the claim is true, the pin is missing.)
- **AC-4b holds across processes.** Process 1 pinned a scope id and wrote;
  process 2 read it back: `AC-4b process 2 read: 500 keys: ['fetch.rows']`. This
  is the criterion the deleted in-memory store could never meet, and the reason
  for deleting it is exactly right.
- **AC-7 holds.** Two default-scoped runs share nothing:
  `{'sees_prior': None, 'rows': None}`.
- **The parallel split is the right call and is pinned.** The scope *id* is
  withheld (`nested_request` resets `workflow_scope_id`) while the *object*
  travels (`invoke.py:700`) — "independent scopes, one parent run" is a
  distinction the old code conflated, and both halves have tests
  (`test_items_still_have_independent_step_records`, plus the new
  `test_two_items_writing_one_key_race` that pins the *cost* rather than hiding
  it).
- **The run-log format decisions are good.** A third version number, discard-on-
  unusable against `scopes.json`'s refuse (`run_format.py:95-126`), with the
  asymmetry asserted in the same test class; caps on both rings; a genuinely
  monotonic ULID (I checked the same-millisecond and backwards-clock branches);
  and never an argument value. `new_run_id`'s "cannot sort into the middle of the
  log" property is correctly reasoned — `invoke_parallel` makes same-millisecond
  collisions the common case.
- **`_ensure_scope` swallowing every exception is right.** A scope the engine
  cannot build must not fail a run, and `StateUnavailableError` is the honest
  seam — an error at the first call rather than a store whose writes nothing
  reads. The `StateUnavailableError` docstring says precisely that.
- **The lock's timeout default is right.** "Proceed rather than deadlock a
  build" is the correct trade for a build tool; F12/T9 ask only that it stop
  being silent.
- **One sibling derivation for all three files.** `beside_state` on each store
  (`scope_store.py:102-110`, `run_store.py:146-154`, `state_store.py:71`) plus
  one upward walk in `state_format.resolve_state_location` means the three files
  cannot land in different directories or different modes — and `RunStore`'s
  extra `for_project` path reuses that walk rather than repeating it.
- **The docstrings are unusually honest for this codebase.** They name the
  defect each decision removes and the case that would break it. Where they
  over-claim (F5's seal, F7's "what happened in this project"), the over-claim is
  traceable to a symptom already on the ledger — which is the failure mode to
  watch, not a rewrite.
