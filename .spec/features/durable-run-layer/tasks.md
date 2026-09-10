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

**Gate — the existing two are untouched**
```bash
rg -c 'STATE_VERSION = 1' src/functualize/_primitives/state_format.py; rg -c 'SCOPES_VERSION = 1' src/functualize/_primitives/scope_format.py
```
now: `1`, `1` · after: `1`, `1`

---

## Wave 1 — the record opens where every door passes

### [ ] T2 · `engine.run()` opens and closes a run record

**Files:** `src/functualize/_engine/executor.py`, `tests/engine/test_run_record.py`

Spec AC-1, AC-2, AC-3. Includes nested and parallel runs — the ones history excludes.

**Gate — history is untouched**
```bash
rg -n 'if invoke_depth == 0:' src/functualize/_engine/executor.py | head -1
```
now: `705` · after: `705`, unchanged — the record is **not** the history ring

**Test:** a nested `rc.invoke` child gets a run record with `parent_run_id` set, and does
**not** appear in `func builtin history`.
**Test:** the record carries `surface`, and it differs between a `func` run and an MCP run of
the same job (AC-2).

---

## Wave 2 — reading runs

### [ ] T3 · The projection and the read verbs

**Files:** `src/functualize/app/_run_view.py`, `src/functualize/app/utils.py`,
`src/functualize/_cli/builtins.py`,
`plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`

One projection, thin callers — the shape 0.3.0 established. `func builtin run list|show`, and
MCP verb for verb (decision **A3**), pinned by the parity test **A7** already in the suite.

**Gate**
```bash
uv run pytest tests/workflow/test_workflow_surface_parity.py -q
```
now: `passing` · after: `passing`, with the four new verbs enumerated

---

## Wave 3 — the event log

### [ ] T4 · A subscriber persists events per run

**Files:** `src/functualize/_events/run_log.py`, `src/functualize/_app/boot.py`,
`tests/events/test_run_log.py`

Spec AC-4, AC-5, AC-6. Per-run ring cap (risk R-c).

**Gate — the bus is still pure**
```bash
rg -c 'open\(|json.dump|write' src/functualize/_events/bus.py
```
now: `0` · after: `0`

**Test:** a run with no subscriber registered costs no additional write (AC-6).

---

## Wave 4 — the fencing token

### [ ] T5 · `claim` / `renew` / `release`, with a monotonic generation

**Files:** `src/functualize/_primitives/lease.py`,
`src/functualize/_primitives/scope_store.py`, `tests/primitives/test_lease_fencing.py`

Spec AC-7. The lease lives **inside the scope record** (schema §4) — additive, no
`SCOPES_VERSION` bump, the same judgement 0.3.0 made for `draft`.

**Gate — there is nothing like this today (narrowed; see header)**
```bash
rg -n 'owner_id|locked_by|claimed_by|worker_id|runner_id|acquired_by|fencing|fence_token|heartbeat|expires_at' \
  src/functualize/ plugins/*/src/ | wc -l
```
now: `3` *(all `plugins/functualize-aws/.../_session.py` — AWS credential expiry, unrelated)* ·
after: `3` + the new lease module's own hits

**Test — the one that matters (risk R-a):** run the fencing check with locking **disabled
entirely**; a stale generation must still be refused. **The lock is not the mechanism** —
`state_lock` proceeds unlocked after its timeout (`state_format.py:277`) and is a no-op on
platforms with neither `fcntl` nor `msvcrt`.

---

## Wave 5 — every scope write is fenced

### [ ] T6 · Writes carry a generation; stale writes are refused

**Files:** `src/functualize/_primitives/scope_store.py`, `src/functualize/_engine/frontier.py`,
`src/functualize/_types/errors.py`

Spec AC-8. `StaleGenerationError` names the current holder — **a count, never content**.

**Gate**
```bash
rg -c 'generation' src/functualize/_engine/frontier.py
```
now: `0` · after: `≥1`

**Sabotage:** drop the generation check from one write path; T7's concurrent-resume test must
fail. **Commit before sabotaging.**

---

## Wave 6 — the two symptoms of one bug

### [ ] T7 · The walk holds a lease; cancel wins; a second resume is refused

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
overwritten by the walk's subsequent `COMPLETED` stamp (`workflow_walker.py:347`).
**Test (AC-9):** two concurrent `resume` invocations on one scope — one advances, the other is
refused with the holder named. *This is the limitation 0.3.0 shipped knowingly.*

---

## Wave 7 — a dead runner is visible

### [ ] T8 · `abandoned`, and an explicit `reclaim`

**Files:** `src/functualize/app/_workflow_view.py`, `src/functualize/app/_workflow_control.py`,
`src/functualize/_cli/builtins.py`

Spec AC-11. Derived, not stored (decision **K4**, inherited **C2**).

**Gate**
```bash
rg -c 'abandoned' src/functualize/app/_workflow_view.py
```
now: `0` · after: `≥1`

> **Ordering is load-bearing** (schema §6): `abandoned` is tested **before** `running`, or a
> dead runner's scope reports as live — which is the bug. The existing docstring already warns
> about this for the `completed`/`stalled` pair; extend the same test shape.

**Test:** nothing reclaims automatically and nothing deletes. `purge` stays the only
destructive verb.

---

## Wave 8 — exactly once

### [ ] T9 · `Step.effecting` and the outbox

**Files:** `src/functualize/workflow/__init__.py`, `src/functualize/_engine/frontier.py`,
`tests/integration/test_crash_and_resume.py`

Spec AC-14, AC-15. The completion and the record commit in one `scope_batch` — the helper
already guarantees all-or-nothing (`scope_store.py:129-150`); this declares which steps need it.

**Test — parity test 2, and it must be a real crash (risk R-f):** `kill -9` a runner
mid-workflow; a new runner resumes from the last committed node; an **effecting** step's file
has one line, not two. A unit test can fake this property; a real signal cannot.

---

## Wave 9 — a timeout that does not lie

### [ ] T10 · Step timeout = lease expiry

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
rg -c 'signal.alarm|SIGALRM|asyncio.wait_for' src/functualize/_engine/
```
now: `0` · after: `0`

**Test:** an expired lease makes the scope claimable; the record reports the original work as
possibly still running; nothing is killed.

---

## Wave 10 — resume refuses the right edits

### [ ] T11 · Source identity from the graph projection

**Files:** `src/functualize/_engine/workflow_validation.py`,
`src/functualize/_primitives/scope_store.py`, `tests/workflow/test_source_identity.py`

Spec AC-16, AC-17. Decision **K3**: the digest is of `workflow_shape_of` → `to_dict()`, **not**
the file (risk R-g).

**Test — parity test 3, both halves:** editing the workflow **graph** refuses a resume; editing
an **unrelated job in the same file** succeeds. The second half is the test that fails if the
digest is over the file.

---

## Wave 11 — the depth guard

### [ ] T12 · `max_workflow_depth`

**Files:** `src/functualize/_engine/workflow_validation.py`, `src/functualize/_types/errors.py`

Spec AC-18, inherited **C9**. `WorkflowDepthExceededError` maps to an exit code through F2's
outcome module — **no new exit code, no second vocabulary.**

---

## Wave 12 — checkpoint

### [ ] T13 · Feature gate

- `uv run ruff check src/ tests/ plugins/`, `ruff format --check`
- `uv run mypy src/`
- `uv run lint-imports`
- `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto`
- `uv run pytest examples/`
- pi-workflows parity tests **2** (crash/resume) and **3** (source identity) pass
- AC-1…AC-18 each named to a test
- orphan scan over every added symbol
- the sabotages at T6, and T5's locking-disabled fencing test, **committing before each**

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
    {"id": 2, "tasks": ["T3"]},
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
