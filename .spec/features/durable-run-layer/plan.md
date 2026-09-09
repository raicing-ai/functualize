# Plan — durable-run-layer

---

## 1. The approach in one line

**Open a record where every door already passes, fence every scope write with a generation,
and let a timeout mean a lease expired rather than a thread was stopped.**

## 2. The three pieces, and which one is load-bearing

| Piece | Difficulty | Why |
|---|---|---|
| The run record and the event log | **low** | `engine.run()` is one site after F1; the bus already emits well-named events; the storage primitives (`atomic_write_json`, `scope_batch`) are solid |
| The lease and its fencing token | **high** | It is the only piece with no substrate. `state_lock` proceeds unlocked after its timeout, so cross-process exclusion has to come from the generation check, not the lock |
| Timeouts and the outbox | **medium** | Both are consequences of the lease |

> Everything here rests on the fencing token. Build it second, not last: the record and the log
> are useful alone, the outbox and timeouts are meaningless without it.

## 3. Files to change

### New

```
src/functualize/_primitives/run_format.py         runs.json, RUNS_VERSION
src/functualize/_primitives/run_store.py          the store
src/functualize/_primitives/lease.py              claim / renew / release, generation
src/functualize/app/_run_view.py                  describe_run / list_runs / run_events
src/functualize/_events/run_log.py                the persisting subscriber
tests/primitives/test_lease_fencing.py
tests/workflow/test_cancel_wins_the_race.py
tests/integration/test_crash_and_resume.py        kill -9, parity test 2
tests/workflow/test_source_identity.py            parity test 3
```

### Modified

```
src/functualize/_engine/executor.py               open/close the record in run()
src/functualize/_primitives/scope_store.py        every write takes a generation
src/functualize/_engine/frontier.py               writes carry the generation
src/functualize/_engine/workflow_walker.py        the walk holds a lease; renews per node
src/functualize/_engine/workflow_runner.py        claim on entry, release on exit
src/functualize/app/_workflow_view.py             derived_state gains `abandoned`
src/functualize/app/_workflow_control.py          resume/cancel under a lease
src/functualize/workflow/__init__.py              Step.effecting
src/functualize/_cli/builtins.py                  run list/show, workflow reclaim
plugins/functualize-mcp/.../_workflow_tools.py    four tools, verb for verb
```

## 4. Risks

- **R-a · The lease is built on a lock that gives up.** `state_lock` proceeds unlocked after
  10 s and is a no-op where neither `fcntl` nor `msvcrt` exists. *Mitigation:* **the lock is
  not the mechanism.** Correctness comes from the generation check inside the batch: read
  generation, compare, write or refuse. The lock only reduces contention. A test runs the
  fencing check with locking disabled entirely and it must still refuse.

- **R-b · Timeouts get built as preemption anyway.** The roadmap says "per-step timeouts", and
  the obvious implementation is a thread with a deadline — the one `exec_policy.py:7-22`
  rejected because *"a caller that believes the job stopped may release a lock or delete a file
  the still-live job is using"*. *Mitigation:* AC-13 forbids the mechanisms by name
  (`SIGALRM`, daemon-thread kill, `asyncio.wait_for` on a body) and a grep test asserts their
  absence, so the wrong implementation fails the suite rather than review.

- **R-c · The event log grows without bound on a long walk.** *Mitigation:* per-run ring cap,
  the same shape as `HISTORY_LIMIT`, chosen for the same reason.

- **R-d · `runs.json` becomes a third file to keep consistent.** *Mitigation:* it is
  deliberately the *discardable* one — a bad version discards, like `state.json`. Nothing reads
  it to make a decision; it is an observation. Putting it in `scopes.json` would force the
  strictest policy onto the most voluminous data.

- **R-e · `abandoned` mis-orders and a live run reports dead.** *Mitigation:* `derived_state`
  already documents that ordering is load-bearing for `completed`/`stalled`; the same test
  shape covers `abandoned` before `running`, and the docstring says why.

- **R-f · The outbox is claimed but never proven.** "Exactly once across a crash" is the kind
  of property a unit test can fake. *Mitigation:* parity test 2 is a real `kill -9` on a real
  process, and the effecting step writes a file it appends to — two lines means the outbox
  failed.

- **R-g · Source identity hashes the file, and every unrelated edit refuses a resume.**
  *Mitigation:* decision **K3** — digest the **graph projection** (`workflow_shape_of` →
  `to_dict()`), not the file. Parity test 3 asserts both halves: graph edit refuses,
  unrelated-job edit succeeds.

- **R-h · Two liveness facts drift.** A heartbeat and a lease expiry answering the same
  question. *Mitigation:* there is exactly one — the lease's `expires_at`. No separate
  heartbeat field (schema §7).

## 5. Ordering

```
W0  runs.json + RunStore                       (storage, unused)
W1  the record opens in engine.run()           (records appear; nothing reads them)
W2  the run projection + CLI/MCP read verbs
W3  the event-log subscriber
W4  the lease: claim/renew/release + generation ← the load-bearing piece
W5  every scope write carries a generation; stale writes refused
W6  the walk holds a lease; cancel wins; concurrent resume refused
W7  `abandoned` + reclaim
W8  Step.effecting + the outbox
W9  step timeout = lease expiry
W10 source identity + revision + legacy mapping
W11 max_workflow_depth
W12 checkpoint
```

W4 → W5 → W6 is the spine. W0–W3 deliver standalone value and can ship as a release on their
own, which matters for a feature the roadmap sizes as multi-release.

## 6. What this plan does not do

No server, no scheduler, no daemon (**N10**). No preemptive cancellation of a running Python
function. No automatic deletion of anything — `purge` stays the only destructive verb.
