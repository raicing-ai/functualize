# Triage — external AFTER review

Every finding in `omp-after-review.md`, with what was done. The review was run
by an independent agent against `d7a01c4` and was **good**: three of its
findings were real defects, two of them reproduced, and one of those was a data
loss I had introduced myself.

| # | severity | verdict | outcome |
|---|---|---|---|
| F1 | HIGH | **upheld** | new feature `scope-record-lifecycle` — the largest thing on the branch |
| F2 | HIGH | **upheld, fixed** | `43f5809` — thread-local batch |
| F3 | MEDIUM | **upheld, fixed** | `03f9eec` — `try/finally` around the lifecycle |
| F4 | MEDIUM | **upheld, fixed** | `43f5809` — registry-driven tripwire (T6) |
| F5 | MEDIUM | upheld, **deferred** | Q-2 |
| F6 | MEDIUM | upheld, **deferred** | folded into `scope-record-lifecycle` |
| F7 | MEDIUM | **already planned** | `durable-run-layer`/T3 |
| F8 | LOW-MED | upheld, **deferred** | Q-3 |
| F9 | LOW | **upheld, fixed** | the ledger is corrected below |
| F10 | LOW | **already planned** | `store-substrate`/T3 |
| F11 | LOW | upheld, **deferred** | Q-4 |
| F12 | LOW | **not reproduced** | see below |

## Fixed in this pass

**F2 — a lost write, and the worst finding of the set.** `ScopeStore._batch`
was one attribute on an object that `invoke_parallel` now shares across 32
workers, and `_mutate` folded *any* write into whatever batch was open. A
sibling thread's `set_state` returned successfully and vanished when another
thread's batch raised. That is the exact failure class the durable-state change
existed to remove, reintroduced one layer down by my own sharing change. Fixed
thread-local, pinned by three tests including one that keeps all-or-nothing
true *within* a thread — without it the fix could have been "never discard".

**F3 — records that said `running` for ever.** Reproduced, fixed, and the
first test I wrote for it was vacuous: it used an unprovided DI dependency,
the exception never left `engine.run()`, and it passed with the fix removed.
The contract is "whatever the lifecycle does, the record closes", so the test
now forces the lifecycle to raise.

**F4 — the ADR's central claim was false.** ADR-021 argued the duality rule is
enforced by a test parametrized over `CAPABILITY_SPECS` "because a third prose
rule would fail the same way", and no such test existed. Now it does, and it
immediately found that `rc.invoke()` and an `inv: Invoke` parameter were still
two objects — I had fixed the symptom and not the duality.

**F9 — the ledger contradicted itself.** `STATUS-HANDOFF.md` listed T4 as not
started when `d7a01c4` implemented it. Corrected.

## F1 — the one that needs its own feature

Upheld in full, and the most important finding. Putting job state inside the
scope record made every `rc.state` read and write **O(project age)**:

```
real project scopes.json: 1019 KB, 2188 records
  on that file : set 58.16 ms | get 11.75 ms
  on an empty  : set  0.28 ms | get  0.10 ms
```

Three things compound:

1. `scopes.json` is the only one of the three stores with **no cap** —
   `state_format` has `HISTORY_LIMIT`, `run_format` has `RUNS_LIMIT` and
   `EVENTS_PER_RUN_LIMIT`, `scope_format` has nothing.
2. Every state operation is a whole-file read-modify-write.
3. A non-workflow scope is written `status: "running"` and **nothing ever marks
   it terminal**, so `purge_scopes` skips it for ever — and since `a7fb91d`
   `list_scopes` hides it, the growth is invisible to the person it is
   happening to. The only escape is `state clear --scopes`, which discards
   in-flight runs too.

**My defence of the design was measured on an empty store.** `0.557 ms per
unbatched set` appears in the handoff and in three docstrings; it is an
empty-file number and does not survive a project that has run 2,000 jobs. The
docstrings are corrected to say so.

Written up as `.spec/features/scope-record-lifecycle/`. It also absorbs **F6**
(a plain job's run record carries a `scope_id` naming a scope that is not a
workflow).

## Deferred, with questions for the maintainer

Recorded as Q-2 … Q-4 in `.spec/OPEN-QUESTIONS.md`.

- **F5 — `WorkflowScope.close()` has no production caller.** The "sealed on
  close" guarantee is reachable only from tests. That is a **fourth** instance
  of the shape `contributor/guides/wiring-discipline.md` exists for, and I
  added code to it this week (`_check_open`). Either wire it or delete it; the
  question is which, and that is the maintainer's.
- **F8 — `Prompt` and `Sources` reach `engine.host` rather than the capability
  map.** The reviewer looked for observable divergence and found none, because
  both doors end at the same collector. So it is an enforcement gap, not a live
  defect — but the tripwire now demands a decision about every capability, and
  these two have none recorded.
- **F11 — the namespace API the ADR decided *not* to build was built.**
  `get_job_state` / `list_job_namespaces` are a framework namespace accessor,
  and ADR-021 §B says a namespace should be a string prefix rather than an API.
  Neither has a caller outside tests. Deleting them changes
  `StateStoreProtocol`, which is a plugin contract — hence a question.

## F12 — not reproduced

The reviewer flagged it **suspected**, correctly. A nested `scopes_lock` in one
process is claimed to self-deadlock and then proceed unlocked after the 10s
timeout. `batch()` returns early when a batch is already open, so the nested
call does not reach `scopes_lock` on the path I could construct. Recorded
rather than dismissed: `state_format._acquire_lock` *does* proceed without the
lock on timeout, which is real and is `capability-duality`/T9.

## What the review got right that is easy to miss

It noticed that the worktree moved under it, said so, pinned every claim to a
single revision with `git show`, and **excluded the in-flight T6 work from
judgement** rather than reviewing a tree it could not reproduce. It also
separated "verified" from "suspected" throughout and marked one finding as not
reproducible. That is what made it usable.
