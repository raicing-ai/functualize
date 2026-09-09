# Schema — durable-run-layer

Internal shapes. The external contract is `contracts.md`.

---

## 1. Where it lives

A new sibling of `state.json` and `scopes.json`, with its **own version**, following PR #34's
precedent exactly:

```
.functualize/runs.json      RUNS_VERSION = 1
```

Why a third file rather than a section of either:

| | Failure mode on a bad version | Why |
|---|---|---|
| `state.json` | **discard** | every section is derived — fingerprints, history, session |
| `scopes.json` | **refuse** | a blocked run is not derived; losing it loses user work |
| `runs.json` | **discard** | a run record is an observation of something that already happened |

Run records are derived in the same sense fingerprints are: losing them costs history, not
work. Putting them in `scopes.json` would force the strictest policy onto the most voluminous
data and make a corrupt run log block every workflow.

> **New scope fields still go inside the scope record, never into `_SECTIONS`** (decision
> **K4**). The lease is a scope concern and lives in `scopes.json`; the run record is not.

## 2. The run record

```jsonc
{
  "run_id": "run-01H…",              // ULID — sortable, so "recent" needs no index
  "job": "build",
  "surface": "mcp.run-job",          // from RunRequest.surface — spec AC-2
  "args_hash": "…",                  // same derivation as history; NO argument values
  "scope_id": "wf-01H…",             // when the run is a workflow, else null
  "parent_run_id": null,             // nested and parallel runs — the ones history excludes
  "invoke_depth": 0,
  "status": "running",               // stored; `state` is derived, as elsewhere
  "started_at": "…", "ended_at": null,
  "group_option_values": { },        // what was requested
  "force": false,
  "runner": "host-1/pid-4821",
  "generation": 3                    // the fencing token this run wrote under
}
```

**No argument values**, matching `executor.py:714-720`'s secrets policy. `args_hash` only.

## 3. The event record

```jsonc
{
  "run_id": "run-01H…",
  "seq": 17,                          // monotonic per run — replay order without timestamps
  "event_name": "job.execute.end",    // the bus's existing grammar, unchanged
  "resource": "build",
  "payload": { },
  "at": "…"
}
```

Appended by a **subscriber**. The bus does not know it exists (spec AC-5).

Capped per run, ring-style, as history is — an unbounded log on a long walk is the same defect
`HISTORY_LIMIT` exists to prevent.

## 4. The lease, inside the scope record

```jsonc
// scopes.json → scopes[<id>] gains one key
"lease": {
  "owner": "host-1/pid-4821",
  "generation": 7,
  "expires_at": "2026-09-09T12:00:00Z"
}
```

`generation` increases on **every** claim, including a reclaim of an expired lease. That is
what makes it a fencing token: a runner holding generation 6 cannot write after generation 7
was issued, even if its own clock disagrees about the expiry.

Additive — **no `SCOPES_VERSION` bump**, the same judgement 0.3.0 made for `draft`.

## 5. The step record gains one key

```jsonc
// scopes.json → scopes[<id>].steps[<key>]
{
  "status": "success",
  "effecting": true,          // NEW — declared on the Step
  ...
}
```

An effecting step's record is written in the **same `scope_batch`** as its completion, so a
crash cannot leave the effect done and the record absent. That is the outbox: the batch helper
already guarantees all-or-nothing (`scope_store.py:129-150`); this feature declares which steps
need it.

## 6. Derived state

```python
# app/_workflow_view.py — one new branch, ordered before `running`
def derived_state(scope) -> str:
    # cancelled -> failed -> completed(+epilogue failed => stalled)
    # -> abandoned: status is "running" and lease is absent or expired
    # -> running -> blocked: "waiting" if any(pending_gates) else "ready"
```

> **Ordering is load-bearing**, exactly as the existing docstring warns for the
> `completed`/`stalled` pair: `abandoned` must be tested **before** `running`, or a dead
> runner's scope reports as live — which is the bug §1.6 describes.

## 7. What is not stored

- Argument values, anywhere.
- A "last seen" heartbeat separate from the lease. The lease's `expires_at` is the only
  liveness fact; two would drift.
- Any automatic reaping schedule. `abandoned` is derived on read; reclaiming is a verb.
