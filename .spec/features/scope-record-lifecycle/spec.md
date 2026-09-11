# Scope record lifecycle — job state must not cost O(project age)

**Depends on:** nothing. **Blocks:** nothing — but it makes
`durable-run-layer`/T3b and `store-substrate` easier, and it is more urgent
than either.

## A · The defect

`capability-duality`/T2 moved a run's state into the scope record. That made it
durable, which was the point, and it also made every `rc.state` read and write
a **whole-file read-modify-write of a file that never stops growing**.

Measured by an external review on this repository's own `scopes.json`
(`.spec/reviews/omp-after-review.md` F1):

```
real project scopes.json: 1019 KB, 2188 scope records
  on that file : unbatched set 58.16 ms | 100 in batch 55.58 ms | get 11.75 ms
  on an empty  : unbatched set  0.28 ms | 100 in batch  0.81 ms | get  0.10 ms
```

~200×, and the cost scales with **how many runs the project has ever done**,
not with what the job stores.

Three things compound, and each is independently wrong:

1. **No cap.** `scopes.json` is the only one of the three stores without one —
   `state_format` has `HISTORY_LIMIT = 200`, `run_format` has `RUNS_LIMIT = 500`
   and `EVENTS_PER_RUN_LIMIT = 200`, `scope_format` has nothing.
2. **Whole-file RMW per operation.** `get_state` → `get_scope` → `_read()` →
   `load_scopes`, a full parse, for one key.
3. **Non-workflow records are immortal.** A plain job that calls
   `rc.state.set(...)` writes a record with `status: "running"`, and nothing
   ever marks it terminal. `purge_scopes` refuses a non-terminal scope
   (`_workflow_control.py:439-441`); the age filter refuses it again for having
   no timestamps; and since `a7fb91d` `list_scopes` hides it — so the growth is
   invisible to the person it is happening to. The only escape is
   `func builtin state clear --scopes`, which discards in-flight runs too.

**The defence of the design was measured on an empty store.** `0.557 ms per
unbatched set` appeared in the handoff and three docstrings; it is a test-time
figure. The docstrings now say so.

## B · Why the honest framing matters

This is not "durable state is slow". It is that **durability was bought by
putting a per-run value in a per-project file**, and the bill arrives later, on
someone else's machine, in a form they cannot see or clean up. That is worse
than a slow operation: it is a slow operation that looks fine in every test
because every test starts with an empty file.

## C · Acceptance criteria

- **AC-1** A state operation's cost does not grow with the number of scopes the
  project has accumulated. Stated as a measurement, not a feeling: `set` and
  `get` against a store holding 2,000 unrelated scope records are within 2× of
  the same operations on an empty one.
- **AC-2** `scopes.json` has a bound, and the bound is **not** "discard a
  running scope". A workflow blocked at a gate must survive any amount of
  unrelated traffic — evicting it is the failure the whole durable-state change
  exists to prevent.
- **AC-3** A non-workflow scope reaches a terminal status when its run ends, so
  `purge_scopes` can remove it. Today nothing marks one terminal.
- **AC-4** `func builtin state show` reports the scope file's size and record
  count, so the growth is visible before it is a problem. A user should not
  need a reviewer to discover it.
- **AC-5** There is a purge path that removes finished non-workflow scopes and
  leaves in-flight ones, reachable without `--scopes` (which moves the whole
  file aside).
- **AC-6** A run record's `scope_id` does not name a scope that is not a
  workflow — review F6. Either it is null for a plain job, or the field means
  "the scope this ran in" consistently and the reader is told which.

## D · Options, none chosen yet

Recorded so the Plan phase starts from the real choice rather than the first
idea. The architecture gate (`.claude/rules/spec-workflow.md`) applies: this
wants BEFORE/AFTER diagrams before an approach is picked.

1. **Mark non-workflow scopes terminal at run end** — smallest, fixes AC-3 and
   lets the existing purge work. Does not fix AC-1: a project with 2,000 *live*
   workflow scopes still pays.
2. **Cap and compact `scopes.json`** — fixes AC-1 and AC-2 only if eviction can
   never touch a live scope, which needs AC-3 first to tell them apart.
3. **Move job state out of the scope record** into its own per-scope file or a
   keyed store — fixes AC-1 directly, and reopens the question
   `capability-duality` answered ("state is a record, so it belongs beside the
   other records"). That answer is still right about *durability*; it did not
   consider *file size*.
4. **Index rather than parse** — a substrate that can read one key without
   loading the envelope. This is `store-substrate`'s port, which is why that
   feature makes this one easier. It does not fix the unbounded growth.

They are not exclusive; 1 is probably needed regardless.

## E · Out of scope

Test residue (`capability-duality`/T10). It inflated the measurement above —
2,200 records in a worktree is not a production number — but the **mechanism**
is production behaviour and does not depend on it.

## F · Inherited: when is a scope finished? (Q-2)

Routed here on 2026-09-11, by the maintainer, from `.spec/OPEN-QUESTIONS.md`
Q-2. It is the same question as §A's and must not be answered separately.

`WorkflowScope.close()` has **no production caller** — `git grep "\.close()"
-- src/` finds no hit on a scope anywhere outside tests. So the guarantee
`ScopeBackedStateStore._check_open` makes —

> once a scope is finished, a late write from a straggling thread must fail
> loudly rather than mutate a record something already read as final

— is reachable only from tests. That is the fourth instance of the shape
`contributor/guides/wiring-discipline.md` exists for, and `_check_open` was
added to the pile during `capability-duality`.

**Why it lands here rather than as its own fix.** Wiring `close()` requires
deciding *when* a scope is finished. A workflow scope has an obvious moment —
the walk reaches END. A plain job's scope does not, and "nothing marks a
non-workflow scope terminal" is precisely §A's defect: records that never end
are records that never get trimmed. One answer settles both.

**Do not resolve this by deleting `close()`.** Deleting it makes a late write
from a straggler silently mutate a record something already treated as final,
which is the failure the guarantee exists to prevent — and this feature adds
trimming, which makes "finished" load-bearing rather than decorative.

Whichever option §D takes must therefore say, in one sentence, what marks a
scope terminal for a non-workflow job, and wire `close()` to it.
