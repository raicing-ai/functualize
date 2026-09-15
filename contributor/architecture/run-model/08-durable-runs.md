# 08 · Durable runs — events, leases, timeouts, and an outbox

Roadmap **item 8**, sized by the roadmap itself as *"Multi-release"*. This document is mostly
about what already exists, because the substrate turns out to be strong in three places and
absent in one — and the absent one is load-bearing for everything else.

---

## A. What exists, measured

### A.1 An event bus that forgets

`EventBus` (`_events/bus.py:290`) is **in-memory only** — a `TrieRouter` for pattern routing
and an `EventCatalog` for introspection. No file I/O, no queue, no replay. Dispatch is
synchronous and in registration order; a raising subscriber is logged and skipped
(`bus.py:400-410`). Event names are grammar-checked — `{domain}.{resource}.{action}`, at least
three dot-segments, regex at `bus.py:33` — and invalid names are dropped.

The framework emits a genuinely useful set already: `job.execute.start` (`executor.py:1032`),
`job.execute.end` on **four** exit paths (`:1149`, `:2078`, `:2444`, `:2523`),
`job.teardown.start/end`, `shell.command.start/end`, the whole config resolution chain, plugin
discovery and load, `discovery.pipeline.resolved`, `cli.parse.end`, `lifecycle.registry.frozen`.

> **Nothing persists any of it.** No subscriber in `src/` or `plugins/` writes an event to
> disk. The bus is a live notification mesh that evaporates with the process.

Two adjacent findings, both F8-sized:

- **Three catalog entries have no emit site.** `job.execute.error`, `cli.parse.start` and
  `tui.session.start/end` are declared in `_events/_catalog_entries.py` and emitted nowhere —
  the same shape as STATUS #13 and #14, in a different subsystem.
- **`hooks.py:2-5` is stale.** It says `HookRegistry` is *"a facade over EventBus … routing
  through the event bus internally"*. It does not touch the bus at all. The
  CONSTITUTION's non-overlap rule (HookRegistry controls, EventBus observes) **holds in the
  code**; only the docstring drifted. Worth fixing before anyone builds on the wording.

### A.2 Two state files with deliberately opposite failure modes

| | `state.json` | `scopes.json` |
|---|---|---|
| Owner | `_primitives/state_format.py` / `StateStore` | `_primitives/scope_format.py` / `ScopeStore` |
| Version | `STATE_VERSION = 1` (`:63`) | `SCOPES_VERSION = 1` (`:64`) |
| Sections | `("fingerprints", "history", "session")` (`:71`) | `{"scopes": {id: record}}` |
| On a bad version | **discards** the file — every section is derived | **refuses** — `ScopeStoreUnreadableError` |

That asymmetry is PR #34's decision and it is right: derived data may be thrown away, a
blocked run may not. **The durable run layer does not reopen it** (decision **K4**: new fields
go inside the scope record, never into `_SECTIONS`).

The scope record is already close to a run record:

```python
{"workflow": None, "status": "running", "steps": {}, "branches": {},
 "gates": {}, "position": None, "epilogue": None, "tool_calls": []}
```

with per-step records carrying `status`, `return_value`, `return_value_reusable`, `inputs`,
`completed_at` (`frontier.py:142-154`).

### A.3 History, and the gate that excludes most runs

`state.json`'s `history` is a **200-entry ring** (`HISTORY_LIMIT`, `state_format.py:69`).
The record is deliberately thin — no argument values, only a hash, under a stated secrets
policy (`executor.py:714-720`):

```python
{"namespace": "job", "job": …, "args_hash": …, "status": …, "duration_ms": …, "at": …}
```

And the gate, verbatim at `executor.py:705-707`:

```python
if invoke_depth == 0:
    self._record_history(job_name, kwargs, result)
```

So workflow steps, dependencies, `rc.invoke` children and **parallel batch items** are never
recorded. The rationale is sound — a deep workflow would evict the whole ring in one run
(`executor.py:683-688`) — and it is exactly why a run *record* is a different object from a
history *entry*, not a bigger one.

### A.4 Atomicity is solved; mutual exclusion is not

**Solved.** `atomic_write_json` (`state_format.py:194-226`): mkstemp in the target directory →
write → `fsync` → `os.replace`. And `ScopeStore.batch()` (`scope_store.py:128-150`) holds the
lock across many mutations and writes once, all-or-nothing — which is what makes a node's
three writes (step record, position, status) atomic. A half-written node is not possible.

**Not solved.** `state_lock` (`state_format.py:240-258`) is an advisory `flock` on a `.lock`
sidecar, and:

> after the timeout it **proceeds unlocked** — *"advisory: proceed rather than deadlock a
> build"* (`state_format.py:276-278`)

and on a platform with neither `fcntl` nor `msvcrt` it is a **no-op** (`:261-266`). It is
best-effort mutual exclusion, not a correctness boundary — a deliberate and defensible choice
for a build tool, and not a foundation a lease can be built on top of unchanged.

### A.5 There is no lease, and the codebase says so

Searched across `src/` and `plugins/`:

- `owner_id|locked_by|claimed_by|worker_id|runner_id|acquired_by|fencing|fence` → **zero matches**
- `lease|heartbeat|ttl|expires_at|expiry` → one substantive hit, and it is a comment naming
  the gap (`app/_workflow_view.py:94-97`): *"Not derived here: whether a resumed walk is
  running right now."*

No lock carries a held-since or expires-at. Scope records carry `blocked_at` per gate and
`completed_at` per step — and `_workflow_control.py:382-389` documents that `blocked_at`
**resets on re-block** and is explicitly unusable as an age measure.

> The one lease-shaped sentence in this codebase is a wish, not a mechanism.

## B. What a crash actually costs today

| | |
|---|---|
| **Survives** | step records and JSON-able return values, branch choices, gate payloads and drafts, `position`, the epilogue once written |
| **Lost — the in-flight step** | It has no record, so on resume it re-runs. Correct for a pure step; **wrong for an effecting one**, and there is no way to declare the difference. This is the effects outbox's entire reason to exist |
| **Lost — unstorable return values** | `classify_return_value` drops non-JSON returns, keeping only kind and type (`frontier.py:127-140`). The in-process compensation lives in a dict on the engine (`executor.py:1938-1944`) and dies with it, forcing `force_fresh` re-runs — `executor.py:1265-1268` says so |
| **Left behind — a scope stuck `running` forever** | Only `FrontierWalk.start` sets `RUNNING`, and only when no position exists (`frontier.py:104-107`). A crashed walk leaves `status="running"` plus a position permanently. `derived_state` faithfully reports `running` (`_workflow_view.py:107`). **There is no reaper and no timeout that clears it** |

## C. Cancellation loses a race, and the race is visible in the code

The roadmap's item 2 shipped in 0.3.0: `WorkflowRunner.prelude` raises `ScopeCancelledError`
when the scope is cancelled (`workflow_runner.py:116-120`), checked there because *"this is
the one point every continuation passes through"*. That is correct and it closed the
documented defect.

**It is not sufficient, and this set records why as a new finding.**

The walker's run loop (`workflow_walker.py:234-345`) never reads `scope["status"]`. Its only
store reads are `get_step`, `get_branch`, `gate_payload`, and position via `start`. So a walk
already in flight when `cancel_scope` writes runs to completion — and worse, it **keeps
writing status and position per node** (`frontier.py:106`, `:163-167`, `:196-197`) and stamps
`COMPLETED` unconditionally at the end (`workflow_walker.py:347`).

> A cancel issued mid-run is **silently overwritten** by the walk's own next write.
> Last-writer-wins per locked write, no generation check, no fencing.

And the window is exactly when it matters: `cancel_scope` refuses anything not in
`LIVE_STATUSES = {"running", "blocked"}`, so a `running` scope is cancellable *precisely
while it is running* — which is precisely when the cancel loses.

This is the same defect as the unfenced concurrent `resume` that 0.3.0 shipped knowingly.
They are one bug with two symptoms, and one fix.

## D. Timeouts — the codebase already decided, with a better argument than the roadmap's

Roadmap item 8 lists "per-step timeouts". **There is no timeout on a job, a step or a walk
today, and that is an explicit, documented decision**, not an omission
(`_engine/exec_policy.py:7-22`):

- A thread-based version *"reported TIMEOUT on overrun"* while the work continued — Python
  cannot preempt a thread, so the status was a lie.
- A `SIGALRM` version works only on POSIX and only on the main thread, so it *"would silently
  do nothing in the TUI"*.
- Conclusion: **bound work where the OS can enforce it** — `sh(..., timeout=N)` kills the
  process group.

Every timeout that does exist honours that rule or is honest about not enforcing:
`sh()` kills a process group; `rc.invoke(timeout=)` returns `RunStatus.TIMEOUT` while
**the thread keeps running** (`invoke.py:784-809`); `invoke_parallel` shuts its executor down
with `wait=False`; remote config fetch has a 30 s future.

And there is a dead declaration: `JobContext.deadline`
(`_engine/capabilities/job_context.py:27,38`) — *"Optional deadline after which the job should
abort"* — is **never set by any construction site**. Another #13/#14.

> **F5 must not overturn this quietly.** A per-step timeout that reports `timed_out` while the
> step's thread runs on is the exact failure `exec_policy.py` rejected. Either the timeout
> bounds something the OS can kill (a subprocess, a child process runner), or it is a
> *lease expiry* — the runner stops renewing and another runner may claim the scope — which is
> honest about not stopping the original work. **This set takes the second reading**, which is
> why timeouts and leases are one piece of work rather than two.

## E. What F5 builds

| Piece | Builds on | Is new |
|---|---|---|
| **Run record** | the scope record's shape; `RunRequest` for identity and `surface` provenance ([04](04-request-and-entry.md)) | a record for **every** run, not only workflows; opened in `engine.run` (decision **K1**) |
| **Event log** | the `EventBus` grammar and the existing emit sites | a persisting subscriber; the bus itself stays fire-and-forget |
| **Lease + fencing token** | `ScopeStore.batch()` for atomic claim; `state_lock` for the write | owner identity, an expiry, and a **generation counter checked on write** — the thing §A.5 proves absent. Fixes §C and the shipped `resume` race together |
| **Per-step timeouts** | the lease's expiry | §D — expiry, not preemption |
| **Effects outbox** | the per-node `scope_batch` | a declared distinction between a replayable step and an effecting one — §B row 2 |
| **Source identity** | `workflow_shape_of` → `to_dict()` | a canonical digest of the **graph projection**, not the file (decision **K3**), plus revision and legacy mapping |
| **Lifecycle verbs** | `cancel_scope`, `purge_scopes`, `resume_scope` in `app/_workflow_control.py` | pause; and cancel becomes enforceable rather than advisory |
| **Depth guard** | `_max_invoke_depth` | `max_workflow_depth` (inherited **C9**) |

## F. Why this cannot come before F1

The argument is in [03 §C](03-the-run-model.md) and it is the reason this set exists. In
short: the record must say **what was requested**, and a request object is what the nine doors
do not build. Opening the record inside `engine.run` costs one site; opening it today costs
nine, or means inventing `RunRequest` inside the durable layer — in the wrong module, by the
wrong feature, with no obligation on any door to fill it.

The three things that make the run *addressable* — `RunRequest.surface`, one resolution point,
one facade — are all F1.

## G. Sabotage checks

| Break this | This must fail |
|---|---|
| Skip the fencing-token check on a scope write | the concurrent-resume test: two resumes on one scope, second must be refused, not silently win |
| Let the walk stamp `COMPLETED` over a `cancelled` status | the mid-run cancel test (§C) |
| Drop the outbox marker on an effecting step | the `kill -9` parity test — the effect must re-run exactly once, not twice |
| Stop renewing a lease without expiring it | the stale-`running` reaper test (§B row 4) |
