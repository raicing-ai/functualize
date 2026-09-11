# Triage — `.spec/reviews/scope-state-review.md`

External review (omp, deepseek-v4-flash, via herdr) of `scope-record-lifecycle`
T3/T5. Nine findings; this records the verdict on each and where it went.

| # | finding | verdict | action |
|---|---|---|---|
| Q1.1 | `discard_state` unlinks outside every lock, on a fresh object that cannot see an open batch | **CONFIRMED** | fixed — routed through the cached instance, under `state_lock` |
| Q1.2 | another thread's read sees the pre-commit value during a batch | **NOT A BUG** | that is read-committed, which is the intended semantics; documented |
| Q1.3 | a batch held across `invoke_parallel` deadlocks (workers block on the holder, holder waits on workers) | **CONFIRMED, pre-existing** | documented as a footgun; the record batch had the same shape before T3 |
| Q1.4 | `_ensured` is never invalidated, so `delete_scope` → `set_state` writes state with no record | **CONFIRMED** | fixed — `delete_scope` drops the memo |
| Q1.5 | `_state_stores` is an unguarded check-then-set | **CONFIRMED** | fixed — `setdefault`, so the loser gets the winner's object |
| Q1.6 | `{"state": null}` reads as `{}` and the next write drops the file's contents | **CONFIRMED** | fixed — a present-but-not-a-dict `state` now refuses, matching the module's stated contract |
| Q2.1a | `discard_state` bypasses an open batch | **CONFIRMED** | same fix as Q1.1 |
| Q2.2 | two `ScopeStateStore` objects for one path self-deadlock on `flock` | **CONFIRMED** | removed by Q1.1 + Q1.5; no path now builds a second object for a path |
| Q2.3 | lock-order inversion: a state batch that writes a record takes state→scopes, while a record batch that writes state takes scopes→state | **CONFIRMED** | **not fixed** — recorded as a surviving smell; see below |

## Q2.3 — recorded, not fixed

The strongest finding, and the one I would not have found.

```
T1: with state.batch():        # holds STATE lock
        rc.track_phase(...)    # -> record write -> wants SCOPES lock
T2: with store.batch():        # holds SCOPES lock
        store.set_state(...)   # -> wants STATE lock
```

Both are reachable from user code. Neither lock can be dropped without losing
the guarantee it exists for, and a global ordering cannot be imposed from
inside the store because the *caller* chooses which batch to open first.

Mitigations in place rather than a fix:

* `_state_store` ensures the record **before** taking the state lock, so the
  common path acquires scopes and releases it before touching state. The
  inversion needs a record write *inside* a state batch.
* Both locks time out (10 s) and log audibly (`state_format._lock_timeout`,
  `capability-duality`/T9), so this deadlocks for ten seconds and then says so,
  rather than hanging forever.

The real fix is one store with one lock — `store-substrate`'s port — which is
the same conclusion `plan.md`'s surviving-smell #1 reached from a different
direction. Recorded there.
