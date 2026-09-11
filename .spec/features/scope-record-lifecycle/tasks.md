# Tasks — Scope record lifecycle

Gates were run from the worktree root at authoring time; each `now:` is what it
printed. `[F]` is the file scope, equal to the gate's hit set.

## T1 · A non-workflow scope reaches a terminal status when its run ends [x]

`[F]` `src/functualize/_engine/executor.py`
`src/functualize/_engine/capabilities/workflow_scope.py`
`tests/integration/test_scope_lifecycle.py`

AC-3, and the prerequisite for T2 and T5 — eviction and purge are only safe
once a finished scope is distinguishable from a blocked one.

A plain job that calls `rc.state.set(...)` writes a record with
`status: "running"` and nothing ever changes it. `purge_scopes` then refuses it
(`app/_workflow_control.py:442`), the age filter refuses it for having no
timestamps (`:424-426`), and `list_scopes` hides it — so the record is
immortal *and* invisible.

The moment already exists. `engine.run` closes the **run record** in a
`try/finally` (`executor.py:795-822`), added when a raising lifecycle left
records `"running"` for ever. The scope is the same moment and the same
guarantee, so it goes in the same `finally` rather than a second one.

Only a scope this run *minted* is closed. A nested run, a workflow step and an
`rc.invoke` child all arrive with `parent_scope` already set and must not close
a scope their parent still owns.

This also answers Q-2 (`spec.md` §F): `WorkflowScope.close()` gets its first
production caller.

```
grep -c "scope.close()\|set_scope_status" src/functualize/_engine/executor.py
```
now: `0` · after: `>= 1`

## T2 · `scopes.json` gets a cap that cannot evict a live scope [x]

`[F]` `src/functualize/_primitives/scope_format.py`
`tests/primitives/test_scope_cap.py`

AC-2. `scopes.json` is the only one of the three stores with no bound —
`state_format` has `HISTORY_LIMIT = 200`, `run_format` has `RUNS_LIMIT = 500`
(`run_format.py:69`), `scope_format` has nothing.

Follows `run_format`'s shape: trim on write, newest kept. It differs in the one
way that matters — **eviction considers terminal records only**. A workflow
blocked at a gate must survive any amount of unrelated traffic; evicting it is
precisely the failure durable state exists to prevent (AC-2 says so outright).

So the cap is not "keep the newest N". It is "if the file exceeds N, drop the
oldest *terminal* records until it fits, and if that is not enough, leave it
oversized". An oversized file of live runs is correct behaviour, not a bug.

```
grep -c "SCOPES_LIMIT" src/functualize/_primitives/scope_format.py
```
now: `0` · after: `>= 2` (the constant and its use)

## T3 · Job state moves to a per-scope file

`[F]` `src/functualize/_primitives/scope_state_store.py`
`src/functualize/_primitives/scope_store.py`
`src/functualize/_primitives/scope_format.py`
`tests/primitives/test_scope_state_store.py`

AC-1, and the load-bearing change. A cap alone cannot satisfy AC-1 *as
written*: it measures against 2,000 accumulated records, and capping makes that
state unreachable — which makes the criterion untestable rather than met.

Today one `rc.state.set()` parses and rewrites every scope record the project
ever made. After this it touches one file holding one run's state, so the cost
is O(this run's state) and a 2,000-record project measures like an empty one.

Second effect, worth as much: **unrelated runs stop contending.** One file
means one `fcntl.flock` sidecar, so two jobs sharing nothing serialize on every
`set` today. Per-scope files give each run its own lock.

Migration is one read: an existing record may carry a `state` section, so read
it when the new file is absent (an in-flight run must resume), write to the new
location, and never write the old section back.

`_batch` is thread-local on `ScopeStore` (`scope_store.py:115-121`) and the new
store matches, or a batch opened on one thread leaks into another.

```
uv run python -c "
import json, pathlib, tempfile, time
from functualize._primitives.scope_store import ScopeStore
d = pathlib.Path(tempfile.mkdtemp())
s = ScopeStore(d / 'scopes.json')
for i in range(2000): s.ensure_scope(f'noise-{i:05d}')
s.ensure_scope('mine')
t = time.perf_counter(); s.set_state('mine', 'k', 1); big = time.perf_counter() - t
e = ScopeStore(pathlib.Path(tempfile.mkdtemp()) / 'scopes.json'); e.ensure_scope('mine')
t = time.perf_counter(); e.set_state('mine', 'k', 1); small = time.perf_counter() - t
print(f'{big*1000:.2f}ms vs {small*1000:.2f}ms -> {big/small:.1f}x')
"
```
now: `116.4x` — measured here at authoring time on a 448 KB / 2,001-record
file (`get` on the same file: `102.1x`) · after: `< 2.0x` (AC-1)

The review's figure was 58 ms on 1,019 KB / 2,188 records; this one is 39 ms on
448 KB because `ensure_scope` writes blank records while a real project's carry
steps and gates. **The ratio is the claim, not the millisecond** — the absolute
number depends on how much each record holds, the multiple does not.

## T4 · `state show` reports the scope file's size and record count [x]

`[F]` `src/functualize/_cli/builtins.py`
`tests/cli/test_state_show_scopes.py`

AC-4. The defect's real cost was invisibility: 1.6 MB accumulated in this
worktree and only an external review noticed. A user should not need one.

```
uv run func builtin state show 2>&1 | grep -ci "scope"
```
now: `1` — the line read `Scopes: 7`, a number with no ceiling and no size
beside it · after: `Scopes: 7 of 500 (412 B)`

## T5 · Purge removes a finished scope's state file with its record

`[F]` `src/functualize/app/_workflow_control.py`
`tests/core/test_purge_scopes_state.py`

AC-5. `purge_scopes` already refuses non-terminal records correctly and needs no
new logic — T1 is what makes it reach anything. What it does need is to delete
the per-scope state file T3 introduces, or purging leaves orphans that nothing
ever collects.

Order matters and is asserted: the **record** goes first, then the state file.
The reverse leaves a record pointing at state that is gone, which reads as
corruption; this order leaves a file nothing references, which reads as empty.

```
grep -c "scope_state\|state_path" src/functualize/app/_workflow_control.py
```
now: `0` · after: `>= 1`

## T6 · A run record's `scope_id` means one thing [x]

`[F]` `src/functualize/_engine/executor.py`
`tests/integration/test_run_record_scope_id.py`

AC-6 and review F6. Decide against what the run log actually writes, not
against what the field is named: either `scope_id` is null for a plain job, or
it means "the scope this ran in" for every run and the reader is told so.

Since T1 gives every run a scope with a real lifecycle, the second reading is
now the honest one — but that is a conclusion to verify by reading the writer,
not to assume here.

```
uv run pytest tests/integration/test_run_record_scope_id.py -q -p no:randomly 2>&1 | tail -1
```
now: `1 failed, 3 passed` — a nested run's record read `scope_id: null` ·
after: `4 passed`

**The gate written at planning time was wrong and is replaced rather than
quietly dropped.** It counted `scope_id` in `_primitives/run_format.py`, which
has **zero** occurrences — the field is written by `executor._open_run_record`,
not defined by the format module. Running it before writing it would have
caught that; this is the Retrieval Before Assertion rule, failed and corrected.

What the corrected gate found is worse than F6 reported. F6 said `scope_id`
*names a scope that is not a workflow*; in fact every **nested** run's record
carried `scope_id: null`, because `nested_request` withholds the scope id from
a child (so it does not share step records and gates) while still handing it
the scope object — so `_ensure_scope` returns early and the id is never filled
in. A run tree could not say which scope its branches ran in.

## Task Dependency Graph

T1 is the prerequisite for T2 (eviction needs terminal records to be reachable)
and for T5 (purge needs the same). T3 touches the primitives and shares
`scope_format.py` with T2, so they cannot run in one wave. T4 and T6 touch
files nothing else in this feature touches.

```json
{"waves": [
  {"id": 0, "tasks": ["T1"]},
  {"id": 1, "tasks": ["T2", "T4", "T6"]},
  {"id": 2, "tasks": ["T3"]},
  {"id": 3, "tasks": ["T5"]}
]}
```
