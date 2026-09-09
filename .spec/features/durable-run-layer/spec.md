# Feature — durable-run-layer

Implements **F5** of `contributor/architecture/run-model/13-roadmap.md` — pi-workflows roadmap
**item 8**, sized by that roadmap as *"Multi-release"*.

**Depends on:** `run-request-entry` (F1), `engine-sealed-construction` (F3).
**Blocks:** `workflow-graph-semantics` (F7).

`RunRequest` is a run's identity on the way in. This feature gives it one on the way out.

---

## 1. The problem

### 1.1 A run in progress leaves no trace

A `@workflow` gets a persisted scope record. **A plain job gets nothing** until it ends, and
then only a 200-entry ring:

```python
{"namespace": "job", "job": …, "args_hash": …, "status": …, "duration_ms": …, "at": …}
```

with argument values deliberately excluded under a stated secrets policy
(`executor.py:714-720`).

And most runs are not recorded at all — `executor.py:705`:

```python
if invoke_depth == 0:
    self._record_history(job_name, kwargs, result)
```

Workflow steps, dependencies, `rc.invoke` children and parallel items are all excluded. The
rationale is sound (`executor.py:683-688`): a deep workflow would evict the ring in one run.
**That is exactly why a run record is a different object from a history entry, not a bigger
one.**

### 1.2 Events exist, are well-shaped, and evaporate

`EventBus` (`_events/bus.py:290`) is in-memory only — verified: **zero** file writes in the
module. Names are grammar-checked (`{domain}.{resource}.{action}`, `bus.py:33`), and the
framework already emits a useful set: `job.execute.start`, `job.execute.end` on four exit
paths, teardown, shell, the config chain, plugin load, `cli.parse.end`,
`lifecycle.registry.frozen`.

**Nothing persists any of it.** No subscriber in `src/` or `plugins/` writes an event to disk.

### 1.3 There is no lease, and the codebase says so

Narrowed search over `src/` and `plugins/` for
`owner_id|locked_by|claimed_by|worker_id|runner_id|acquired_by|fencing|fence_token|heartbeat|expires_at`
returns **3 hits, all AWS credential expiry in an unrelated plugin**. No lock carries a
held-since or an expires-at.

The one lease-shaped sentence in the codebase is a comment naming the gap
(`app/_workflow_view.py:97`):

> *"…the store knows rather than guessing; live-versus-parked needs a lease."*

### 1.4 Mutual exclusion is best-effort, by design

`state_lock` (`state_format.py:240-258`) is an advisory `flock` on a sidecar, and after its
timeout it **proceeds unlocked**:

```python
return  # advisory: proceed rather than deadlock a build     (state_format.py:277)
```

On a platform with neither `fcntl` nor `msvcrt` it is a no-op. That is a defensible choice for
a build tool — **and it is not a foundation a lease can sit on unchanged.**

What *is* solid: `atomic_write_json` (mkstemp → write → fsync → `os.replace`) and
`ScopeStore.batch()` / `StateStore.scope_batch()` (`scope_store.py:129`, `state_store.py:106`),
which hold the lock across many mutations and write once, all-or-nothing. **A half-written node
is not possible.** The gap is between processes, not within one.

### 1.5 Cancellation loses a race, and the race is in the code

0.3.0 added `WorkflowRunner.prelude`'s cancelled check — correct, and it closed the documented
defect. It is not sufficient.

Verified: the walker's run loop reads scope status **zero** times
(`rg -c 'scope\["status"\]|get_scope_status' src/functualize/_engine/workflow_walker.py` → 0).
Meanwhile the walk keeps writing status and position per node (`frontier.py:106`, `:163-167`,
`:196-197`) and stamps `COMPLETED` unconditionally at the end (`workflow_walker.py:347`).

> **A cancel issued mid-run is silently overwritten by the walk's own next write.**
> Last-writer-wins per locked write, no generation check, no fencing.

And the window is exactly when it matters: `cancel_scope` refuses anything not in
`LIVE_STATUSES = {"running", "blocked"}`, so a running scope is cancellable *precisely while it
is running* — which is precisely when the cancel loses.

This is the same defect as the unfenced concurrent `resume` 0.3.0 shipped knowingly. **One bug,
two symptoms, one fix.**

### 1.6 A crash leaves a scope `running` forever

Only `FrontierWalk.start` sets `RUNNING`, and only when no position exists
(`frontier.py:104-107`). A crashed walk leaves `status="running"` plus a position permanently,
and `derived_state` faithfully reports `running`. **There is no reaper.**

The in-flight step also has no record, so on resume it re-runs — correct for a pure step,
**wrong for an effecting one**, and there is no way to declare the difference.

### 1.7 Timeouts: the roadmap wants one, the codebase already refused it

Item 8 lists "per-step timeouts". There is no timeout on a job, a step or a walk, **by
research rather than omission** (`_engine/exec_policy.py:7-22`):

> *"A first version ran the body in a daemon thread and reported `TIMEOUT` on overrun — but
> Python cannot preempt a running function, so the work simply continued in the background.
> That is a worse failure than no timeout: **a caller that believes the job stopped may release
> a lock or delete a file the still-live job is using.**"*

and a `SIGALRM` version *"would silently do nothing in the TUI"*. Conclusion: **bound work
where the OS can enforce it.**

`JobContext.deadline` is a declared field no construction site sets — F8 deletes it.

---

## 2. User stories

- **US-1** As an operator, I can see what a run is doing now, and what it did, after the
  process that ran it is gone.
- **US-2** As an operator, two runners cannot both drive one workflow. The second is refused
  with a reason, not silently ignored.
- **US-3** As an operator, `cancel` stops a running walk — it is not overwritten by the walk it
  cancelled.
- **US-4** After `kill -9`, a new runner resumes from the last committed node, and a step
  declared as effecting runs **exactly once** across the crash.
- **US-5** As an operator, a scope whose runner died is reported as abandoned, not as running
  forever.
- **US-6** As a maintainer, I can ask "which surface started the runs that failed this week"
  and get an answer, because the record carries `RunRequest.surface`.

---

## 3. Behaviour

### 3.1 A run record, opened where every door already passes

> The record is opened inside `engine.run()` — the one place every door reaches after F1. That
> is the whole reason this feature is sequenced behind F1 and not before it.

It carries what the request said (job, surface, group options, scope, force), what happened
(status, timings, step outcomes) and who ran it (runner identity). It is **not** the history
ring: history stays a 200-entry summary of top-level runs, and its `invoke_depth == 0` gate is
unchanged.

### 3.2 An event log that persists what the bus already emits

A subscriber persists events per run. **The bus stays fire-and-forget** — no publisher is
added, no event name changes, no synchronous write is put on the emit path.

### 3.3 A lease with a fencing token

A runner claims a scope with an owner identity, an expiry, and a **monotonically increasing
generation**. Every write to that scope carries the generation it was acquired under, and a
write whose generation is stale is **refused, not merged**.

> A lease without a fencing token is a suggestion. The generation check is the mechanism;
> the expiry is only how a dead runner's claim eventually clears.

This closes §1.5 and the concurrent-`resume` limitation 0.3.0 shipped knowingly, together.

### 3.4 Timeouts are lease expiry, not preemption

> **This feature does not overturn `exec_policy.py`'s decision, and must not appear to.**

A step's "timeout" means: the runner stops renewing its lease, the scope becomes claimable, and
another runner may take it. The original work is **not stopped** — Python cannot preempt it —
and the record says so in those words. Anything that reports `timed_out` while the work
continues is the exact failure `exec_policy.py` rejected.

Work that *can* be bounded is still bounded where the OS can enforce it: `sh(..., timeout=N)`
kills a process group.

### 3.5 An effects outbox

A step may be declared as **effecting**. An effecting step's completion is committed with its
record in one batch, so a crash cannot replay it. A pure step re-runs on resume, exactly as
today — which is the current behaviour, now *declared* rather than assumed.

### 3.6 Abandoned scopes are reported, never silently reaped

A scope whose lease has expired with no renewal is reported as **abandoned** — a derived state,
like every other (`_workflow_view.py`'s `derived_state`), with no new stored field. Reclaiming
it is an explicit verb.

> Nothing deletes a user's run record automatically. `purge` stays the only destructive verb.

### 3.7 What must not change

- `state.json` discards on a version mismatch; `scopes.json` **refuses**. That asymmetry is
  PR #34's decision and it is right (decision **K4**): new fields go **inside** the scope
  record, never into `_SECTIONS`.
- The history ring, its 200 cap, its `invoke_depth == 0` gate, and its no-argument-values
  secrets policy.
- `EventBus`'s in-memory, fire-and-forget dispatch and its name grammar.
- `_execute_lifecycle`'s 20-step order.
- `atomic_write_json` and the batch helpers.

---

## 4. Acceptance criteria

**The record**

- **AC-1** Every run through `engine.run()` opens a run record, including nested and parallel
  runs that history excludes.
- **AC-2** The record carries `RunRequest.surface`, and "which surface started this run" is a
  query.
- **AC-3** The history ring is unchanged — same shape, same 200 cap, same depth gate, still no
  argument values.

**Events**

- **AC-4** Events emitted during a run are persisted against that run.
- **AC-5** `EventBus` still has no file I/O; persistence is a subscriber.
- **AC-6** A run with no subscriber costs no additional write.

**The lease**

- **AC-7** A runner claims a scope with an owner, an expiry and a generation.
- **AC-8** A write carrying a stale generation is **refused**, with an error naming the current
  holder — not merged, not last-writer-wins.
- **AC-9** Two concurrent `resume` invocations on one scope: one advances, the other is
  refused. *(The limitation 0.3.0 shipped knowingly.)*
- **AC-10** A `cancel` issued while a walk is running takes effect and is **not** overwritten
  by that walk's subsequent writes. §1.5.
- **AC-11** A scope whose lease expired without renewal derives as `abandoned`, and nothing
  deletes it.

**Timeouts**

- **AC-12** A step timeout expires a lease; it does not claim to stop the work, and the record
  says the work may still be running.
- **AC-13** No `SIGALRM`, no daemon-thread kill, no `asyncio.wait_for` on a job body.
  `exec_policy.py`'s decision stands.

**The outbox**

- **AC-14** A step declared effecting runs **exactly once** across a `kill -9` and a resume.
- **AC-15** A pure step re-runs on resume, exactly as today.

**Source identity**

- **AC-16** Resume refuses when the workflow **graph** changed, and succeeds when an unrelated
  job in the same file changed. The digest is of the graph projection, **not** the file
  (decision **K3**).
- **AC-17** A declared revision and a legacy-mapping path ship with it.

**Guard**

- **AC-18** `max_workflow_depth` refuses a nesting deeper than the configured limit
  (inherited **C9**).

---

## 5. Out of scope

- Loops, failure routing, `watch` and `notify` — **F7**, which depends on this.
- A server, a scheduler, or a daemon. pi-workflows' server-first architecture is **N10**: it
  forfeits the < 5 ms `boot_static` and the in-process `Invoke`.
- Re-opening the `state.json` / `scopes.json` split — **K4**.
- Preemptive cancellation of a running Python function. §3.4.

## 6. Prior art

- **pi-workflows** — the benchmark for durable runs; its lease and typed outcomes are the
  model, its server-first architecture is not (**N11**).
- **`_engine/exec_policy.py:7-22`** — the timeout decision this feature respects, with the
  `invoke` and `doit` comparison it cites.
- **PR #34** — the state/scopes split, its independent versions and its fail-closed read.
- **`app/_workflow_view.py:93-97`** — the codebase naming this feature's central gap before it
  was specified.
