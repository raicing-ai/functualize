# Tasks — durable-run-layer

Every gate was **run at authoring time** against `e57f0c9`; `now:` is what it returned then.
Run gates from the worktree root.

The lease gate below was narrowed during authoring: a broad
`lease|owner|heartbeat` search returns 23 files, almost all matching **`release`** (terminal
handoff, plugin release, version release). Narrowed to identity-and-token spellings, it returns
**3 hits — all AWS credential expiry in an unrelated plugin**.

---

## Wave 0 — storage

### [x] T1 · `runs.json` and `RunStore`

**Files:** `src/functualize/_primitives/run_format.py`,
`src/functualize/_primitives/run_store.py`, `tests/primitives/test_run_store.py`

`RUNS_VERSION = 1`, a **discard**-on-mismatch policy (schema §1), reusing `atomic_write_json`
and the lock helpers. Nothing writes to it yet.

**Gate**
```bash
rg -c 'RUNS_VERSION' src/functualize/_primitives/run_format.py
```
now: `file absent` · after: `≥1` — **`5`**

**Test:** `tests/primitives/test_run_store.py`, **27 passed**. The one that earns its place is
`TestTheReadRuleIsTheOppositeOfScopes`, which pins the discard against the refusal *in the same
class*: four unusable inputs read as empty here, and the same shape makes `load_scopes` raise.
A future refactor that merges the two files fails there with the reason attached — that putting
run records under `scopes.json` forces the **strictest** policy onto the **most voluminous**
data, and one corrupt run log then blocks every workflow in the project.

**Two defects found by writing the tests, both in code written minutes earlier:**

1. **Two rules that contradicted each other.** `_trim` deleted events for any run id not in
   `runs`; `append_event`'s docstring promised an event for an unopened run is kept — which it
   must be, because the subscriber and the record-opener are deliberately uncoordinated (the
   bus does no file I/O, AC-5). The distinction the first draft missed: a run this file
   **evicted** is not a run it has **never seen**. Evicted runs take their events; orphans are
   kept and bounded as a group. Two tests now hold the two rules apart so neither can be
   restated as the other.
2. **The ULID was not monotonic.** Five runs opened in one millisecond share a timestamp
   prefix, and a freshly drawn random tail then ordered them arbitrarily —
   `test_recent_runs_are_newest_first` caught it. `rc.invoke_parallel` opens a batch in a few
   microseconds, so a millisecond collision is the **common** case here, not the exotic one,
   and "the most recent five runs, shuffled" is a bug a reader would blame on the store. The
   tail now increments within a millisecond (the spec's monotonic variant) and a backwards
   clock keeps minting under the last millisecond seen, so a new run can never sort into the
   middle of the log.

**Gate — `state.json`'s version is untouched**
```bash
rg -c 'STATE_VERSION = 1' src/functualize/_primitives/state_format.py
```
now: `1` · after: `1` *(**invariant** — the third file exists so the other two keep their own
version numbers; a bump here would mean this feature had reached into a neighbour's format)*

**Gate — `scopes.json`'s version is untouched**
```bash
rg -c 'SCOPES_VERSION = 1' src/functualize/_primitives/scope_format.py
```
now: `1` · after: `1` *(**invariant** — same reason. The lease T5 adds is **additive inside the
scope record**, which is why it needs no bump; see schema §4.)*

> **Both gates were one fence when this task was authored**, holding two `rg`
> commands separated by `;` and recording a single `1`. That is two defects at once, and
> `tests/spec/test_task_gates_still_hold.py` found both on the first re-run: the combined
> output is `1\n1`, so the recorded `after: 1` is simply wrong, and an unmarked `now == after`
> is a gate that cannot fail. Split, valued separately, and marked.

---

## Wave 1 — the record opens where every door passes

### [x] T2 · `engine.run()` opens and closes a run record

**Files:** `src/functualize/_engine/executor.py`, `src/functualize/_engine/context.py`,
`src/functualize/_types/run_request.py`,
`src/functualize/_engine/capabilities/{runcontext,invoke}.py`,
`src/functualize/_engine/{workflow_orchestrator,dependency_runner}.py`,
`tests/engine/test_run_record.py`

Spec AC-1, AC-2, AC-3. Includes nested and parallel runs — the ones history excludes.

**Gate — history is untouched**
```bash
rg -n 'if invoke_depth == 0:' src/functualize/_engine/executor.py | head -1
```
now: `705` · after: **`1311`** — the *line number* moved (`engine-sealed-construction` T6/T7
extracted ~300 lines from this file); the **line** is unchanged, which is what the gate is
about. The ring's rule, its 200 cap and its depth gate are untouched, and
`test_the_child_is_absent_from_history` asserts that behaviourally rather than by line number.

**Test:** a nested `rc.invoke` child gets a run record with `parent_run_id` set, and does
**not** appear in `func builtin history`. ✓ — both halves, in one class, because they are one
claim: two logs answering two questions.
**Test:** the record carries `surface`, and it differs between a `func` run and an MCP run of
the same job (AC-2). ✓

**9 tests, and the parentage mechanism is the part worth reading.** `parent_run_id` rides on
the **`RunRequest`**, not in a `ContextVar`: `rc.invoke_parallel` hands its items to a
`ThreadPoolExecutor`, and a fresh thread starts with an *empty* context — so a context variable
would report every batch item as a top-level run, and batch items are exactly the children
whose parentage the log most needs. `TestParallelItemsKeepTheirParent` is that assertion.
`nested_request` deliberately does **not** propagate the field: a child's parent is whoever
built its request, and inheriting would make a grandchild claim its grandparent.

**A bug found by the probe, in a place a test would have missed.** There are **two**
`RunContext` construction sites in `executor.py`: one at the DI binding (`binding.source ==
"runcontext"`) and a fallback for a context DI did not fill. Only the fallback was given the
run identity at first — so a job declaring `rc: RunContext` produced children with
`parent_run_id=None` while the path a test could most easily exercise looked correct. `Invoke`
turned out to have a **third** door, its own capability factory, which needed the same hop.
Three sites, one fact.

**Three defects in the tests themselves, each of the same species:**

1. `parent()` took `invoke: Invoke` with `Invoke` imported **inside the test method**. A nested
   function's `__globals__` is the module's, so the annotation did not resolve and the job
   failed with "missing 1 required positional argument". The test then read the run log and
   found one record — and would have reported that as a *product* defect.
2. Neither child test asserted the run **succeeded** before reading the log. That is what let
   (1) look like a recording bug. Every test here now asserts the status first: a test that
   reads a log without checking the run worked is measuring the wrong thing.
3. The dependency test declared `@job(deps=Deps("upstream"))` and registered the entry without
   `dependencies=`. The job **graph** is built from `RegisteredJob.dependencies`, which
   discovery fills from the declaration — so a hand-registered entry must say it twice, and
   saying it once produced a green run with no dependency at all.

**Best-effort, deliberately.** Both halves are wrapped and log at debug:
`test_a_run_survives_a_store_that_cannot_be_written` monkeypatches the store to raise and
asserts the job still succeeds. Without it this file would be asserting the log works *and*
quietly making the engine fragile — an observation is never worth a run.

---

## Wave 2 — reading runs

### [x] T3 · The projection and the read verbs

**Files:** `src/functualize/app/_run_view.py`, `src/functualize/app/utils.py`,
`src/functualize/_cli/builtins.py`,
`plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`

One projection, thin callers — the shape 0.3.0 established. `func builtin run list|show`, and
MCP verb for verb (decision **A3**), pinned by the parity test **A7** already in the suite.

**Gate**
```bash
uv run pytest tests/workflow/test_workflow_surface_parity.py -q
```
now: `23 passed` · after: `23 passed`, spanning **both** CLI groups

**Three tools, not four.** `contracts.md` §6 lists `list_runs`, `get_run`,
`get_run_events` and `reclaim_workflow`; the fourth belongs to **T8**
(`abandoned`, and an explicit `reclaim`) and is not a read verb. Landed here:

| CLI | MCP |
|---|---|
| `builtin run list [--job --surface --state --scope --limit]` | `list_runs` |
| `builtin run show <id> [--tree]` | `get_run(run_id, tree=)` |
| `builtin run show <id> --events` | `get_run_events` |

`--events` folds into `show` rather than being its own verb, recorded in
`RUN_TOOL_IS_A_CLI_OPTION` for the reason `get_gate_draft` is: a terminal wants
one command that can show more, an agent wants a tool whose name says what it
returns.

**The parity test had to grow a second axis.** It derived CLI verbs from
`builtin workflow` alone while reading tools from the whole provider — so a run
tool would have passed by having no CLI group to be missing from. It now spans
both groups, which is the gap that widens exactly when a surface is added.

**Two things found while building it, both recorded rather than quietly fixed:**

1. `RUN_STATES` was first written as a hand-made tuple of six values. There are
   ten. A surface enumerating it would have rejected `cancelled`, `skipped`,
   `timeout` and `unknown` as illegal filters. It is now derived from
   `RunStatus` — the sixth-copy failure `pitfalls.md` §6 names, committed in a
   comment that cited §6.
2. `_derive_state` reports `abandoned` for a run with no end whose runner is
   not this process. That **over-reports**: a live job on another machine reads
   as abandoned. Kept because of what each error costs — a misleading row a
   human re-checks, versus a dead run hidden for ever — and the docstring says
   so plainly. T5's lease replaces the inference with a fact.

---

### [x] T3b · Derive `history` from the run log, then rename `state.json`

**Files:** `src/functualize/_primitives/state_format.py`,
`src/functualize/_primitives/state_store.py`,
`src/functualize/_engine/executor.py`, `src/functualize/_cli/builtins.py`,
`src/functualize/app/_run_view.py`, and the `state_root` call sites
(19 refs) plus the docs naming `state.json` (25 refs)

**Added 2026-09-11 from `capability-duality`. Held for this task deliberately:
the rename is only correct *after* the history question is decided, and this is
where it gets decided.**

#### Why the name is now wrong

The word "state" means three different things, and `capability-duality` made
that worse by moving job-written state into `scopes.json`:

| to a job author | `rc.state.set(...)` | → `scopes.json` |
| to the file | fingerprints, history, session preconditions | → `state.json` |
| to the CLI | `func builtin state` | → **both** |

The live trap: a user who writes `rc.state.set(...)` and then runs
`func builtin state clear` clears fingerprints and history — **not their
data**. Their data needs `state clear --scopes`. One word, two files, opposite
outcomes.

#### Why the rename waits on the history decision

`state.json` holds three things. Two are freshness verdicts — fingerprints, and
session precondition results — and one is not: `history`, a 200-entry ring of
what the user launched.

`runs.json` (T1/T2) already records **every** run with parentage, of which
`history` is a strict subset carrying less information. `_records_history`
keeps only `invoke_depth == 0` plus top-level parallel items; the run log keeps
those *and* the nested ones, *and* who invoked them.

> **BLOCKED 2026-09-12 — the premise above is only half true.**
>
> The history ring holds **two namespaces**, and only one of them is a subset
> of the run log:
>
> | namespace | written by | shape | in the run log? |
> |---|---|---|---|
> | `job` | `executor._record_history` | `job`, `args_hash`, `status`, `duration_ms`, `at` | **yes** — a strict subset |
> | `shell` | `_cli/tui/shell_mode.py:308` | `command`, `argv`, `exit_code` | **no** — a shell command is not a job run |
>
> `func builtin history --namespace shell` is a documented flag
> (`builtins.py:1794-1796`, *"Show only one namespace (e.g. job, shell)"*), so
> this is a shipped surface, not an accident.
>
> **Deleting the ring as written would silently lose shell history**, and
> `runs.json` has nowhere to put a command that was never a run. Which means
> step 2 — the rename — cannot happen either: a `history` key would still be
> sitting inside a file called `fresh.json`, the exact worse-lie this task was
> written to avoid.
>
> **The fork, and it needs the maintainer.** Three ways out, and they differ in
> what the user sees, not just internally:
>
> 1. **Shell history gets its own file** (`.functualize/shell-history.json`).
>    `state.json` then holds only freshness verdicts and `fresh.json` becomes
>    honest. Costs a fourth file in `.functualize/` and a small store to own it.
> 2. **Shell commands become run records** with their own surface value. One
>    log for "things that happened", but it puts non-runs in the run log and
>    every run consumer then has to filter them out.
> 3. **Keep the ring, drop the rename.** Cheapest; leaves the three-way "state"
>    collision this task exists to fix.
>
> Measured blast radius if the rename does go ahead: **19** `state_root` refs,
> **34** `resolve_state_location` / `beside_state` / `resolve_state_path` refs
> in `src/`, and **9** doc files naming `state.json`.
>
> Held rather than guessed: picking wrong means ~60 references moved twice.
>
> **ANSWERED 2026-09-12 — option 1: shell history gets its own file.**
>
> `.functualize/shell-history.json`, owned by a small store of its own.
> `state.json` then holds only freshness verdicts, which is what makes
> `fresh.json` a definition rather than an approximation.
>
> The maintainer's reasoning for the fourth file over folding shell commands
> into the run log: a filter every consumer must remember is a rule that gets
> forgotten once and then ships. `func builtin history` reads two sources and
> keeps its `--namespace` flag; nothing changes for the user.
>
> **Executed in two commits, because they fail differently.** The history move
> is behavioural and its mistakes are visible in a test. The rename is ~60
> mechanical references whose mistakes are import errors. Mixing them would
> make a bisect useless.

So the order is:

1. **Derive** `history` from `runs.json` in this task's projection, and delete
   the ring from `state_format`. `func builtin history` becomes a view over the
   run log rather than a second record — which is this feature's own thesis
   (one projection, thin callers) applied to the one place it was not.
2. **Then** rename. With `history` gone the file holds only freshness verdicts,
   and `fresh.json` stops being an approximation and becomes the definition.

Renaming first would leave a `history` key inside a file called `fresh.json` —
a worse lie than the one being fixed.

#### Names considered

- **`fresh.json`** — chosen, *after* step 1. Names the meaning, and after the
  history move it covers the whole file.
- `hash.json` — rejected. Names the mechanism rather than the meaning, and only
  fingerprints are hashes; precondition results are not.
- `state.json` — rejected. Its only argument is incumbency, and it is the
  source of the three-way collision above.

#### The command group becomes `func builtin data` (decided 2026-09-12)

Asked as "keep `state`, rename to `fresh`, or split"; the maintainer rejected
all three and named a fourth that is better than any of them:

> *Why not use `func builtin data`, then either use a flag option or
> sub-groups to split the fresh.json vs scope.json vs run.json etc.*

It is the honest name. The group was never about one file — it reports and
clears **five**: `fresh.json`, `scopes.json`, `scope-state/`, `runs.json` and
`shell-history.json`. Naming it after any single one of them (`state` after the
old file, `fresh` after the new) trades one inaccuracy for another, and `data`
is what the group actually covers.

It also removes the `--scopes` awkwardness properly. That flag exists because
the command was named for one file and had to bolt on a second; with the group
named for the whole directory, each file is a target rather than an exception.

```
func builtin data show                      # every file: path, count, size, mode
func builtin data clear                     # derived only, as `state clear` was
func builtin data clear --scopes            # also move scopes.json aside
func builtin data clear --runs              # also drop the run log
func builtin data clear --all               # everything
```

`clear`'s default is unchanged, so the careful asymmetry it already had is
kept: **derived data is deleted, records are moved aside.** `scopes.json`
holds gate payloads a human deposited, so `--scopes` renames the file rather
than removing it and says where it went — and that is also the escape hatch
from a scope file that cannot be parsed, which is why it never reads it first.

`func builtin state` is **deleted, not aliased** (Pre-Release Stance).

#### Carry with it

`state_root` → `fresh_root`, `resolve_state_location`, `beside_state`, and the
`func builtin state` group. The `--scopes` flag disappears with the rename: the
scope file gets its own verb rather than being a flag on someone else's.

**Migration:** `state.json` is a user-visible path in a released version, so
this needs a read-both / write-new pass or an explicit "delete it" note in the
changelog. Pre-release stance permits the latter; say which, in the commit.

**Gate**
```bash
rg -c "state\.json" src/functualize/ | awk -F: '{s+=$2} END {print s+0}'
```
now: `29` (measured at `6a37e79`, the part-1 commit) · after: **`0`**

```bash
rg -c '"history"' src/functualize/_primitives/fresh_format.py || echo 0
```
now: `2` · after: **`0`** — satisfied by part 1, verified `0` at `6a37e79`

```bash
rg -c "^class StateStore\b" src/ plugins/ | awk -F: '{s+=$2} END {print s+0}'
```
now: `2` · after: **`0`** — which also closes `capability-duality`/T8, deferred
precisely because it could not rename this class until this task decided the
file's name.

**Done in two commits**, because they fail differently: the history move is
behavioural and its mistakes show up in a test, while the rename is ~110
mechanical references whose mistakes are import errors. Mixing them would make
a bisect useless.

---

## Wave 3 — the event log

### [x] T4 · A subscriber persists events per run

**Files:** `src/functualize/_events/run_log.py`, `src/functualize/_app/boot.py`,
`tests/events/test_run_log.py`

Spec AC-4, AC-5, AC-6. Per-run ring cap (risk R-c).

**Gate — the bus is still pure**
```bash
rg -c 'open\(|json.dump|write' src/functualize/_events/bus.py
```
now: `0` · after: **`0`** — invariant, and asserted from a test as well as here,
so it cannot go green by the write merely moving somewhere equally wrong.

**Test:** a run with no subscriber registered costs no additional write (AC-6).

## The attribution problem, and why the answer is a thread-local

An event carries `trace_id` and `span_id`, not a run id. The run id is known by
`engine.run()`, and a job body emits from inside it — so the event belongs to
**the innermost run active on the emitting thread**.

Held in a thread-local stack that `engine.run()` pushes and pops. That looks
backwards, since a `ContextVar` is the usual tool, and it is the wrong one here
for the reason `RunContext._run_id` already records: `invoke_parallel` runs batch
items on worker threads, and a `ContextVar` set in the parent is **not**
inherited by a thread it did not create — the item would read an empty context
and its events would be filed under nothing.

The stack is correct for exactly the reason it is usually not: the push happens
*on the thread that runs the job*, because `engine.run()` is what pushes and
`invoke_parallel` calls it on the worker.

Verified rather than argued: a fan-out of two items, each asserting its own
event reached its own run's log.

## Buffered, so no write lands on the emit path

`RunStore.append_event` is a locked read-modify-write of the whole log; one per
`emit` would put a file lock in the middle of every event a job raises. Events
are buffered in memory and flushed once, in the same `finally` that closes the
run record. Asserted as *store writes*, not as elapsed time — 50 events produce
exactly one batched write, and zero before the run ends.

The per-run cap (risk R-c) is applied **in memory**, so an over-long run costs
nothing extra on disk either; it is not a trim applied after the fact. Its
default is `EVENTS_PER_RUN_LIMIT`, read from the store rather than written twice
— a buffer larger than the store's ring would write events the store discards
on arrival.

Events emitted outside any run — boot, discovery, CLI parsing — are dropped.
They belong to the process, not a run, and inventing one would make the log
claim something false.

---

## Wave 4 — the fencing token

### [x] T5 · `claim` / `renew` / `release`, with a monotonic generation

**Files:** `src/functualize/_primitives/lease.py`,
`src/functualize/_primitives/scope_store.py`, `tests/primitives/test_lease_fencing.py`

Spec AC-7. The lease lives **inside the scope record** (schema §4) — additive, no
`SCOPES_VERSION` bump, the same judgement 0.3.0 made for `draft`.

**Gate — there is nothing like this today (narrowed; see header)**
**Rewritten to a stable form.** The gate as authored counted every hit of a
broad pattern across `src/`, which is a *snapshot*, not a property: T6 added
fencing call sites and the count moved from 32 to 39, so the recorded `after:`
went stale within a day and `tests/spec/test_task_gates_still_hold.py` caught
it — which is that test working exactly as intended.

What the gate meant is "there was nothing like this, and now there is, and the
one pre-existing match is unrelated". That is expressible as a number which does
not move when this feature grows:

```bash
rg -c 'def check_generation' src/functualize/_primitives/lease.py
```
now: `0` — the file did not exist · after: `1`

The fencing check itself, named once. It does not move as the feature grows
(T6 added call *sites*, not a second definition), and it is not satisfied
before the work — the two properties the broad count had neither of.

For the record, since the original gate's point was that nothing like this
existed: the only pre-existing matches for its pattern are **3** in
`plugins/functualize-aws/.../_session.py`, AWS credential expiry, unrelated and
untouched.

The baseline moved under the task: `runner_identity` arrived with T1/T2, and
the pattern's `runner_id` matches it. Re-measured rather than trusted —
`plugins/functualize-aws/.../_session.py` still has exactly the 3 unrelated
hits (AWS credential expiry); the other 5 are the run log's `runner` field.
After: 24 new hits, 22 of them the lease module itself.

## Two design errors, both caught by a test rather than by review

**Releasing must expire the lease, not delete it.** The first implementation
deleted, which looks tidier and hands out the fence it exists to raise: with the
record gone the generation resets to 0, so the next claim is generation 1 again
— and the releasing runner's own in-flight writes, carrying generation 1, would
be accepted under a *different* holder's claim. Release now writes the same
generation with an expiry of `now`: immediately claimable, and the next claim
increments past it. `get_lease` also still answers "who held it last", which is
the question asked right after something goes wrong.

**Two racing claims produce one winner, not two generations.** The first test
asserted both would succeed with generations 2 and 3. That was wrong about the
guarantee: the read-modify-write happens inside the lock, so the loser sees the
winner's *live* lease and is refused — a stronger outcome, and the one that
actually closes 0.3.0's concurrent-`resume` limitation.

## Risk R-a — the lock is not the mechanism

`TestFencingHoldsWithoutLocking` replaces `file_lock` with a no-op and asserts
every fencing property still holds. This is the test class that can tell a
fencing design from an owner-plus-expiry one: with locking working the two
behave identically, so any test that leaves it on is blind to the difference.

It carries its own guard (`test_the_no_op_lock_is_really_in_effect`), because a
patch that silently missed would leave three tests passing for the wrong reason
— a green suite asserting the opposite of what it claims.

Sabotage-verified twice, and each failed the right tests: making a reclaim reuse
the generation failed 11 including all four no-locking tests; making release
delete failed exactly the two that name it.

**Test — the one that matters (risk R-a):** run the fencing check with locking **disabled
entirely**; a stale generation must still be refused. **The lock is not the mechanism** —
`state_lock` proceeds unlocked after its timeout (`state_format.py:277`) and is a no-op on
platforms with neither `fcntl` nor `msvcrt`.

---

## Wave 5 — every scope write is fenced

### [x] T6 · Writes carry a generation; stale writes are refused

**Files:** `src/functualize/_primitives/scope_store.py`, `src/functualize/_engine/frontier.py`,
`src/functualize/_types/errors.py`

Spec AC-8. `StaleGenerationError` names the current holder — **a count, never content**.

**Gate — the recorded one counted a word, and the word drifted twice**
```bash
rg -c 'generation' src/functualize/_engine/frontier.py
```
recorded `now: 0 · after: 13`, and is **superseded** by the one below. It counts
the *word* `generation` anywhere in the file, prose included, so every sentence
explaining the fence satisfied it and every edit near it moved it:

- **14 → 13 (2026-09-12, a rename).** `store-substrate`/T3 deleted `FreshStore`'s
  33 forwarders, two of them the *renamed* ones: `hold_scope_generation` and
  `scope_generation` existed because on a store that also held fingerprints a
  bare `hold` or `generation_for` would not have said what it held. On
  `ScopeStore` they are `hold` and `generation_for`, and the word left one line
  of `frontier.py` with them.
- **13 → 15 (2026-09-12, prose).** `workflow-graph-semantics`/T4 added
  `_step_that_went_silent` and `_record_timed_out`, whose docstrings mention the
  generation twice. Nothing about the fence changed. The gate moved because
  someone explained it — *a description of a thing is not the thing*, arriving
  from the other direction.

Replaced with a count of the mechanism, which no docstring can reach:
```bash
rg -c 'self\._generation|generation=' src/functualize/_engine/frontier.py
```
now: `0` · after: `7`. Measured at `057e802~1` (before T6) and at HEAD. These
are the two things the fence *is* — the generation this walk holds, and the
generation every write carries — so deleting the check turns it red, and
writing about it does not.

The generation check itself is untouched by either drift, and its own gate —
the one that counts `scope_id=` arguments to `_mutate` — is unchanged.

**Sabotage:** drop the generation check from one write path. Done, and it failed
**7** tests including the enumeration one written for exactly this
(`test_every_scope_write_passes_its_scope_id_to_mutate`).

## The check is in `_mutate`, not on the write methods

Eleven methods write to a scope record. Putting the check on each fences them
all today and misses the twelfth, added next month by someone who has not read
this file — the failure mode the capability tripwire exists for, one layer
down. One check in `_mutate` means a write path added tomorrow is fenced the
day it is written.

It runs **inside the lock**, against the envelope the write is about to modify.
Checking beforehand leaves open exactly the window that matters: the walk reads,
decides, and writes, and a claim landing between the read and the write would
pass a check made at decision time.

Three methods stay unfenced, each with its reason in the test's `UNFENCED` map:
the lease verbs, because claiming is how a runner *obtains* a generation.
`TestEveryWritePathIsFenced` enumerates the store rather than listing methods,
so the exemptions are visible and a new writer is covered automatically.

## A process failure worth recording

The first sabotage run reported **0 failures**, and the conclusion I drew from
it — "the tests do not catch this" — was wrong. The sabotage had not applied:
the script located the end of `record_step` with `s.index("    def ", i)`, which
matched the **nested** `def _apply(` and sliced away the very line it meant to
edit.

*A description of a thing is not the thing*, applied to sabotage itself. A
sabotage run must assert the sabotage exists before its result means anything;
the redone version does (`assert old in s` plus an explicit print), and then
failed the 7 tests above.

---

## Wave 6 — the two symptoms of one bug

### [x] T7 · The walk holds a lease; cancel wins; a second resume is refused

**Files:** `src/functualize/_engine/workflow_walker.py`,
`src/functualize/_engine/workflow_runner.py`, `src/functualize/app/_workflow_control.py`,
`tests/workflow/test_cancel_wins_the_race.py`

Spec AC-9, AC-10.

**Gate — the walker currently never reads scope status**
```bash
rg -c 'scope\["status"\]|get_scope_status' src/functualize/_engine/workflow_walker.py
```
now: `0` · after: `≥1`, **or** the equivalent generation check on every write

**Test (AC-10):** cancel a scope **while its walk is running**; the cancel stands and is not
overwritten by the walk's subsequent `COMPLETED` stamp.
**Test (AC-9):** two concurrent `resume` invocations on one scope — one advances, the other is
refused with the holder named. *This is the limitation 0.3.0 shipped knowingly.*

## Fencing alone does not make cancel win

The finding that shaped this task. A cancel writes `status: cancelled`; the walk
then reaches END and writes `status: completed` — and **that write is legal**,
because the walk holds the current generation. Nothing is stale about it. T6's
fence does not help, and a test that only asserted "the fence exists" would have
passed while cancel silently lost.

So `cancel_scope` **takes the lease** (`force=True`, the second of the two verbs
allowed to). The walk's next write is then refused, it stops where it is, and
what the record says is what the person who cancelled meant.

The walk gains a third outcome for this, `SUPERSEDED`, distinct from `FAILED`:
nothing about the work went wrong, and reporting a failure would send someone
looking for a bug in their job.

## A bug in the cancel itself, found by its own test

`cancel_scope` fenced **itself** out. Claiming moved the generation, and its own
`set_scope_status` still carried what the store held before — now stale. The
cancel took the lease and was then refused its own write.

Surfaced because the AC-10 test deliberately uses one store object for both the
CLI and the walker. Fixed by holding the generation just taken, and restoring
the caller's previous hold in a `finally`: cancel *borrows* the lease to make
its write land, and does not leave the caller's store fenced to a generation the
caller never claimed.

## The walk releases in a `finally`

A crashed walk that kept its lease would hold the scope until expiry — turning
one traceback into a five-minute wait for everyone else, on a scope owned by a
process that is gone.

**Gate**
```bash
rg -c 'StaleGenerationError|SUPERSEDED' src/functualize/_engine/workflow_walker.py
```
now: `0` · after: `4`

---

## Wave 7 — a dead runner is visible

### [x] T8 · `abandoned`, and an explicit `reclaim`

**Files:** `src/functualize/app/_workflow_view.py`, `src/functualize/app/_workflow_control.py`,
`src/functualize/_cli/builtins.py`

Spec AC-11. Derived, not stored (decision **K4**, inherited **C2**).

**Gate — the recorded one counted a word, and prose moved it**
```bash
rg -c 'abandoned' src/functualize/app/_workflow_view.py
```
recorded `now: 0 · after: 4`, and is **superseded** by the one below. It counts
the *word* anywhere in the file. `workflow-graph-semantics`/T5 added
`walk_is_live`, whose docstring has to say how it differs from this — an absent
lease is "not abandoned" here and "nobody is walking it" there — and the gate
went to `5` for a sentence. The same shape as T6's above, and the second time
prose has moved a gate on this branch.

Replaced with a count of the derivation itself:
```bash
rg -c 'return "abandoned"|def _lease_has_lapsed|_lease_has_lapsed\(' src/functualize/app/_workflow_view.py
```
now: `0` · after: `3`. Measured at `d4bf896~1` (before T8) and at HEAD. The
helper, its one call, and the branch it feeds — delete any of them and this goes
red; explain them and it does not move.

> **Ordering is load-bearing** (schema §6): `abandoned` is tested **before** `running`, or a
> dead runner's scope reports as live — which is the bug. The existing docstring already warns
> about this for the `completed`/`stalled` pair; extend the same test shape.

**Test:** nothing reclaims automatically and nothing deletes. `purge` stays the only
destructive verb.

## What "abandoned" can and cannot mean

An expired lease means *nothing has heard from that runner* — **not** *that
runner is dead*. A long step on a machine with a slow clock looks identical. So:

* derived on read, **never repaired on read**. A read that quietly took the
  scope would make a slow step on a distant machine lose its work to whoever
  happened to look at a list.
* `reclaim` is a verb a person runs, having looked.
* an abandoned scope is **not purgeable** — it is not finished, and collecting
  it would delete the evidence of the crash that produced it. The path out is
  `cancel`, where a human says what happened, and then `purge`.

**A scope with no lease is not abandoned.** Most have none — written by a plain
job, or before leases existed — and calling those dead would make `abandoned`
the answer for most of the file. Absence of evidence is not evidence, and here
absence is the ordinary case rather than the suspicious one. That is the
opposite of the call `_run_view._derive_state` makes for runs, and deliberately:
there, a record with no end and a foreign runner is *unusual*, so
over-reporting is the safer error.

**`blocked` is not abandoned either.** A workflow parked at a gate is waiting on
a human and has no runner to renew anything; reporting every gate as a failure
would be worse than the bug this fixes.

`reclaim` is **not destructive** — every step record, gate payload and position
survives; only the generation moves, which is what stops the previous holder
writing. It refuses a scope whose lease is still live, because that is not
abandoned but in use: `cancel` is the verb for taking a scope from a runner that
is working, and collapsing the two would remove the reason `cancel` announces
itself.

Three surfaces, verb for verb: `func builtin workflow reclaim`,
`reclaim_workflow`, and the parity test extended to both.

Sabotage: testing `abandoned` after `running` — the exact inversion schema §6
warns about — failed 3 tests including the one named for the ordering.

---

## Wave 8 — exactly once

### [x] T9 · `Step.effecting` and the outbox

**Files:** `src/functualize/workflow/__init__.py`, `src/functualize/_engine/frontier.py`,
`tests/integration/test_crash_and_resume.py`

Spec AC-14, AC-15. The completion and the record commit in one `scope_batch` — the helper
already guarantees all-or-nothing (`scope_store.py:129-150`); this declares which steps need it.

**Test — parity test 2, and it must be a real crash (risk R-f):** `kill -9` a runner
mid-workflow; a new runner resumes from the last committed node; an **effecting** step's file
has one line, not two. A unit test can fake this property; a real signal cannot.

Done: `tests/integration/test_crash_and_resume.py` spawns a real subprocess,
waits for it to announce the effect is done, and `SIGKILL`s it. A guard class
asserts the exit code really was `-SIGKILL` — a `terminate()` would let a
handler flush and the whole file would prove nothing.

## `effecting` defaults to False, and that is the honest default

The framework cannot tell an effecting step from a pure one by looking, and
guessing wrong in this direction re-runs a refund. A step that says nothing is
replayed — the behaviour every workflow has had until now (AC-15), asserted
separately because the easy over-correction is to make *every* step run once.

Recorded **on the step**, not looked up from the declaration at resume time: a
resume may run in another process against a declaration that has since changed,
and what matters is what the step was when it ran. The record is the only
witness to that.

## A real defect in `reclaim`, found only by using the scope afterwards

`reclaim_scope` claimed the lease **and kept it**. So the scope was unavailable
for the full lease period to the very runner meant to pick it up — the resuming
process could not claim, and the workflow never advanced.

Every unit test for `reclaim` passed. They checked what the record said and
stopped there; this is the only test that goes on to *use* the scope. Reclaim
now claims and immediately releases: the generation moves so the dead holder
stays fenced, and the lease expires in place so the scope is claimable at once.

## What the test fakes, and what it must not

The crash is real. The **waiting** is not: a killed runner's lease is still live
for its full duration, because nothing can distinguish "crashed" from "slow" —
that is the design, and it means a real recovery either waits or cancels.
Waiting 300 s in a test is absurd, and the expiry path itself is covered by
`test_abandoned_and_reclaim.py`, so the lease is aged and the crash is not.

Sabotage: recording `effecting: False` for every step failed the record test.

---

## Wave 9 — a timeout that does not lie

### [x] T10 · Step timeout = lease expiry

**Files:** `src/functualize/_engine/workflow_walker.py`,
`tests/engine/test_timeout_is_lease_expiry.py`

Spec AC-12, AC-13.

> **The roadmap says "per-step timeouts"; `exec_policy.py:7-22` already refused the obvious
> implementation, and it was right.** A thread-based timeout reports `TIMEOUT` while the work
> continues — *"a caller that believes the job stopped may release a lock or delete a file the
> still-live job is using"*. A timeout here means the runner stops renewing; the work is **not**
> stopped, and the record says so in those words.

**Gate — the rejected mechanisms stay rejected**
```bash
rg -c 'signal\.alarm\(|asyncio\.wait_for\(' src/functualize/_engine/
```
now: `0` · after: `0` — **invariant**, and narrowed to a *call* (trailing `(`).
The gate as written matched `exec_policy`'s docstring, which names SIGALRM to
explain why it is refused; the test enforcing this parses the AST instead.

**Test:** an expired lease makes the scope claimable; the record reports the original work as
possibly still running; nothing is killed.

## The gap was renewal, not expiry

Expiry already worked — a walk claimed once and the lease ran out. That is also
why it was wrong: with nothing renewing, the lease was a **step time limit**. A
step slower than `DEFAULT_LEASE_SECONDS` would watch its own scope go claimable
while it was still working, and another runner could take it.

`FrontierWalk.renew()` at each node boundary says "still here", so the lease
measures **silence** rather than duration. Between nodes rather than during one,
because that is where the walk sits between two committed states — and because
nothing could interrupt a step anyway.

Renewal deliberately does **not** move the generation: it would fence this
walk's own in-flight writes, so every heartbeat would invalidate the work it
exists to protect. It is also best-effort — a failed renewal means the scope was
taken, and the next *write* reports that with the holder named, rather than
raising in the middle of a step that is running perfectly well.

## What the reclaim says it did not do

A lapsed lease means that runner stopped *renewing*; **nothing stopped the
runner**. `reclaim` now returns `work_not_stopped` and names the previous owner,
because "something may still be running" is not actionable and a name is. The
message says the old runner cannot corrupt this scope and can still touch
anything outside it — which is the true and useful statement.

## Two test failures of my own, both instructive

**A gate that matched its own explanation.** `test_the_engine_uses_none_of_them`
grepped `_engine/` for `SIGALRM` and failed — on `exec_policy`'s docstring,
which exists to explain *why* SIGALRM is rejected. The same for `kill` in
`lease.py`'s prose. Both now parse the AST and look for **calls**, with a guard
asserting the walk finds any calls at all. This design is documented by
describing the mechanisms it refuses, so text matching was never going to work.

**A sabotage that changed nothing, correctly.** Deleting the walker's
`self._walk.renew()` failed **zero** tests, because every test called
`walk.renew()` directly. The method was correct and never exercised through the
walk — the shape `wiring-discipline.md` exists for, and the lease would have
expired under every long workflow with the unit tests green.
`TestTheWalkActuallyRenews` closes it, and the same sabotage now fails.

**And one process failure:** restoring that sabotage with `git checkout --
frontier.py` deleted `renew()` itself, which was uncommitted. That is the exact
hazard `wiring-discipline.md` §3 documents and the second time this branch has
paid for it. Restore from the scratchpad copy with `install -m644`; never
`git checkout` a file holding uncommitted work.

---

## Wave 10 — resume refuses the right edits

### [x] T11 · Source identity from the graph projection

**Files:** `src/functualize/_engine/workflow_validation.py`,
`src/functualize/_primitives/scope_store.py`, `tests/workflow/test_source_identity.py`

Spec AC-16, AC-17. Decision **K3**: the digest is of `workflow_shape_of` → `to_dict()`, **not**
the file (risk R-g).

**Test — parity test 3, both halves:** editing the workflow **graph** refuses a resume; editing
an **unrelated job in the same file** succeeds. The second half is the test that fails if the
digest is over the file.

Both done. The second half is written so it *cannot* be satisfied by a file
digest: every declaration under test lives in the test module itself, alongside
all its fixtures and imports, so a file digest would change on any edit at all.

## What the digest is over, and why not the file

`WorkflowShape.to_dict()`, serialised with sorted keys so dict ordering cannot
change the answer. A **file** digest refuses a resume when a docstring changes,
a module is reformatted, an import is added, or an unrelated job in the same
file is edited — and that last one is the edit people actually make while a
workflow is parked, because it is usually the bug that made them park it. That
is not a safety property; it is a permanent annoyance that teaches people to
bypass the check (risk R-g).

What genuinely invalidates a parked walk is the **graph**: its nodes, its edges,
where it starts. A test covers the re-routed case specifically — same nodes,
different edges — because a node-name comparison would pass it.

The refusal **destroys nothing**: the step records stay, the scope stays
readable, and only *advancing* stops. A safety check more destructive than the
unsafe operation it prevents is not one.

AC-17's legacy path: an unrecorded digest resumes and is recorded. Refusing
there would strand every walk that was already parked when this check landed.

## A sabotage that was inert twice, and what it showed

Sabotaging `setdefault` → `=` in `set_graph_digest` failed **nothing**. So did
moving the record *before* the comparison. Neither is a flaw in the tests:
**the two defences cover each other.** `setdefault` makes the ordering
irrelevant, and the ordering makes `setdefault` irrelevant, so breaking either
alone leaves the property held by the other.

Breaking **both at once** fails 4 tests, which is the evidence that the property
is real rather than accidental. Recorded because "the sabotage did not fail
anything" is otherwise indistinguishable from a test that proves nothing — and
the first sabotage on this branch that reported zero failures had simply not
applied.

**Gate**
```bash
rg -c 'graph_digest' src/functualize/_engine/workflow_validation.py
```
now: `0` · after: `1` — the function's own definition. Measured, not guessed:
the first value written here was `3`, and the gate-honesty test caught it
before the commit did.

---

## Wave 11 — the depth guard

### [x] T12 · `max_workflow_depth`

**Files:** `src/functualize/_engine/workflow_validation.py`, `src/functualize/_types/errors.py`

Spec AC-18, inherited **C9**. `WorkflowDepthExceededError` maps to an exit code through F2's
outcome module — **no new exit code, no second vocabulary.**

## A separate limit from `max_invoke_depth`, because they bound different things

`max_invoke_depth` counts *any* nested call. This counts **workflows inside
workflows**, and each of those costs a scope, a set of step records, an epilogue
slot and a lease. A run can invoke deeply without nesting a single workflow, so
one limit cannot serve both.

Not hypothetical: a workflow that names itself as a step type-checks, boots, and
produces one scope per level until the disk or the recursion limit gives out —
and every one of those scopes is a record somebody has to clean up.

## The depth is read from the scope id

A nested workflow's scope is `f"{parent}::{step}"` (`workflow_orchestrator`), so
the separators **are** the depth. Reading it there rather than threading a
counter through the walk means the two cannot disagree — and a resumed walk in a
fresh process has the id and nothing else.

The check runs **before the graph check and before any work**, because the cost
it bounds is the scope itself: a guard that writes a step record before refusing
has bounded nothing. A test asserts no step ran and no record was written.

The limit is a **ceiling, not an exclusive bound** — `max_workflow_depth=2`
allows two levels. Asserted, because an off-by-one here is something a reader
would otherwise have to discover from behaviour.

**Gate**
```bash
rg -c 'workflow_depth' src/functualize/_engine/workflow_validation.py
```
now: `0` · after: `3`

---

## Wave 12 — checkpoint

### [x] T13 · Feature gate

- [x] `uv run ruff check src/ tests/ plugins/`, `ruff format --check` — clean, 0 to reformat
- [x] `uv run mypy src/` — 352 files, no issues
- [x] `uv run lint-imports` — **7 kept, 0 broken.** See below: this found a real break
- [x] `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n 8` — 12,002 passed / 155 skipped
- [x] `uv run pytest examples/` — 201 passed
- [x] all 13 plugin suites, one package at a time — green
- [x] parity test **2** (crash/resume) — `tests/integration/test_crash_and_resume.py`,
      a real `SIGKILL` with a guard asserting the exit code really was one
- [x] parity test **3** (source identity) — `tests/workflow/test_source_identity.py`,
      both halves, the second written so a file digest cannot satisfy it
- [x] AC-1…AC-18 each named to a test — every one appears in `tests/`, lowest count 3 (AC-8)
- [x] orphan scan over all 27 added symbols — every one has a production caller
- [x] sabotages: T6's (dropping the check from one write path), T5's
      locking-disabled fencing, and eleven more across T4–T12. Committed before
      each

## The gate found a real break, nine commits late

`lint-imports` reported **`_cli uses public API only` BROKEN**: nine imports
where `_cli` reached straight into `_primitives` for `RunStore`,
`ShellHistoryStore` and `scope_state_dir`. Introduced in T3b/T3/T4 and unnoticed
since, because the per-task loop was ruff + mypy + pytest and that set silently
excluded a gate the repository maintains.

The contract exists for the reason this whole roadmap exists: the CLI is a
*surface*, and a surface importing internals becomes a second reader of a
question the public API already answers. Fixed by exporting the three through
`app/utils.py` and rewiring all nine sites.

**The process lesson is not "remember lint-imports".** A check that only runs at
a feature boundary will always find things late. It belongs in the per-task
loop, where the diff is small enough that the cause is obvious.

---

---

## Wave Audit

Read `.spec/AUDIT.md` first — it says what this section is for and how to run it. In short:
an agent that did **not** execute this feature works down the table below, per wave, and
tries to show each claim is false. Running the task's own gate and stopping is not an audit:
the gate was written by whoever wrote the code.

For every wave, do all five:

| # | Check | How |
|---|---|---|
| 1 | **The claim is true** | Run the falsifier in the row. The row says what output means the claim is false. |
| 2 | **The gate can fail** | Make the smallest edit that should break it, confirm the gate turns red, restore. A gate that stays green under that edit is **Blocking**. |
| 3 | **The tests are wired** | Apply the wave's sabotage, confirm the named test fails, restore. **Commit before sabotaging** — `git checkout --` reverts everything uncommitted in the file. |
| 4 | **Scope held** | `git show --stat <commit>` against the wave's `**Files:**` lines. Anything extra must be named in the commit message with a reason. |
| 5 | **The answers** | A wave claiming to be behaviour-free must have changed none. A wave that changes one must name it, and a test must assert the *new* answer with the reason beside it. |

Known hazards on this branch, all observed at least once — check for them specifically:

- **A gate matching its own explanation.** `rg` for a removed literal also matches the comment
  saying why it is gone. Three gates here needed rewording or narrowing for this reason.
- **A gate whose `after:` is unreachable.** One counted docstrings that state the rule the
  task enforces; another counted the authority module the task creates.
- **A test that pins the defect.** Check that a changed assertion moved *toward* the spec, not
  toward whatever the code now does.
- **Scope widened into tests no task owns.** The wave graph guarantees source disjointness
  only; the tests pinned to those sources belong to nobody.

### Per-wave

| Wave | The claim | Falsify it | Sabotage |
|---|---|---|---|
| 0 | *(fill from the wave's task headings: T1)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 1 | *(fill from the wave's task headings: T2)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 2 | *(fill from the wave's task headings: T3)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 3 | *(fill from the wave's task headings: T4)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 4 | *(fill from the wave's task headings: T5)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 5 | *(fill from the wave's task headings: T6)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 6 | *(fill from the wave's task headings: T7)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 7 | *(fill from the wave's task headings: T8)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 8 | *(fill from the wave's task headings: T9)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 9 | *(fill from the wave's task headings: T10)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 10 | *(fill from the wave's task headings: T11)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 11 | *(fill from the wave's task headings: T12)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 12 | *(fill from the wave's task headings: T13)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |

> The middle column is deliberately not pre-filled with the task's own gate. Derive the
> falsifier from the **claim**, then check whether the task's gate asks the same question. If
> it asks a narrower one, that difference is the finding.


## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1"]},
    {"id": 1, "tasks": ["T2"]},
    {"id": 2, "tasks": ["T3", "T3b"]},
    {"id": 3, "tasks": ["T4"]},
    {"id": 4, "tasks": ["T5"]},
    {"id": 5, "tasks": ["T6"]},
    {"id": 6, "tasks": ["T7"]},
    {"id": 7, "tasks": ["T8"]},
    {"id": 8, "tasks": ["T9"]},
    {"id": 9, "tasks": ["T10"]},
    {"id": 10, "tasks": ["T11"]},
    {"id": 11, "tasks": ["T12"]},
    {"id": 12, "tasks": ["T13"]}
  ]
}
```

**Why these boundaries**

Thirteen single-task waves, and that is the honest shape of this feature: it is a spine, not a
fan. Each task produces the substrate the next consumes.

- **W0–W3 are separable value.** Records, a projection and an event log are useful with no
  lease, and can ship as a release on their own — which matters for a feature the roadmap sizes
  as *multi-release*.
- **W4 → W5 → W6 is the load-bearing sequence.** The token must exist (W4) before writes carry
  it (W5) before the walk can rely on it (W6). Reordering any pair produces a lease that does
  not fence.
- **W7 after W6** — `abandoned` is derived from a lease that must already be renewed by a walk,
  or every scope looks abandoned.
- **W8 and W9 both depend on W6** and are separated because both edit
  `_engine/workflow_walker.py`.
- **W10 and W11 are independent of the lease** and could run earlier; they are placed late
  because they are the smallest and the least likely to be interrupted.
- **W12 is a checkpoint** and checkpoints always get their own wave.

**File-disjointness** is trivial with single-task waves.
`_engine/frontier.py` is touched by T6 and T9 (waves 5 and 8);
`_engine/workflow_walker.py` by T7, T9 and T10 (waves 6, 8 and 9);
`app/_workflow_control.py` by T7 and T8 (waves 6 and 7);
`_primitives/scope_store.py` by T5, T6 and T11 (waves 4, 5 and 10). All separated.
