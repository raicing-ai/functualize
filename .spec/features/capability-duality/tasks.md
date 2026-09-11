# Tasks — capability duality

Gates were run at authoring time from the worktree root; `now:` is what each
command returned on `8b18ee1`.

## T1 · `StateStore.keys` takes a prefix

`[F]` `src/functualize/_engine/capabilities/state_store.py`

Lift the `prefix` parameter off the class about to be deleted, so the
maintainer's `"fetch.count"` convention is usable without a second API.

```
rg -c "def keys\(self, prefix" src/functualize/_engine/capabilities/state_store.py
```
now: `0` · after: `1`

## T2 · `State` names one class

`[F]` `src/functualize/_engine/capabilities/state.py` (deleted),
`src/functualize/_engine/capabilities/state_store.py`,
`src/functualize/_engine/capabilities/registry.py`,
`src/functualize/job/_state.py`, `src/functualize/testing/builder.py`,
`src/functualize/testing/doubles.py`

Delete the per-invocation dict; `State` becomes the public name of the
scope-aware store. The capability factory returns the run's instance rather
than a new object.

```
rg -c "^class State" src/functualize/_engine/capabilities/state.py src/functualize/_engine/capabilities/state_store.py src/functualize/_primitives/state_store.py src/functualize/_engine/capabilities/protocols.py | awk -F: '{s+=$2} END {print s}'
```
now: `4` · after: `3`

## T3 · A workflow step's `rc.state` is the scope's store

`[F]` `src/functualize/_engine/workflow_orchestrator.py`

Pass the scope object, not only its id. This is the behaviour change: steps
that each held a private store begin sharing one.

```
rg -c "parent_scope" src/functualize/_engine/workflow_orchestrator.py
```
now: `0` · after: `1`

## T4 · `rc._cap` is the one resolver

`[F]` `src/functualize/_engine/capabilities/runcontext.py`

`_log_sink` collapses into it; `rc[T]` and `T in rc` consult it before the DI
registry. It never constructs — see `plan.md` R-a.

```
rg -c "_caps\.get|_cap\(" src/functualize/_engine/capabilities/runcontext.py
```
now: `1` · after: `>1`

## T5 · ADR-021 states the mechanism and its exemptions

`[F]` `contributor/adr/021-capability-duality.md`, `.spec/CONSTITUTION.md`

Name the mechanism, then every class of capability that legitimately cannot
share — qualified providers, factory-scoped providers, exclusive resources
(`TTY`), pre-flight-bound capabilities (`Sources`, `Freshness`), app-scoped
singletons — each with its reason and its remedy. The Constitution's rule
gains a pointer rather than a restatement.

```
test -f contributor/adr/021-capability-duality.md && echo exists || echo missing
```
now: `missing` · after: `exists`

## T6 · The tripwire

`[F]` `tests/integration/test_capability_duality.py`

Parametrized over `CAPABILITY_SPECS`, so a capability added tomorrow is covered
the day its spec is written.

```
uv run pytest tests/integration/test_capability_duality.py -q -p no:randomly 2>&1 | tail -1
```
now: `7 passed` · after: `>7 passed`

## T7 · The example stops teaching the trap

`[F]` `examples/standalone/composition_lab/jobs/pipeline.py`

§8 exists to demonstrate the isolation T3 removes, so it is rewritten rather
than edited.

```
rg -c "the trap this job pins" examples/standalone/composition_lab/jobs/pipeline.py
```
now: `1` · after: `0`

## T8 · One name per store

`[F]` `src/functualize/_engine/capabilities/state_store.py`,
`src/functualize/_primitives/state_store.py`, and their importers
(28 files import the on-disk one, 13 the in-memory one)

Five things wear the word "state" and two distinct classes are both called
`StateStore`, sharing no code, no import and no behaviour — one is an
in-memory dict behind `rc.state`, the other reads `state.json`. A reader who
greps `StateStore` gets both.

After T2 the job-facing store is the only thing a user touches, so it takes the
short name:

| holds | was | becomes |
|---|---|---|
| one invocation's dict | `capabilities.state.State` | *deleted* (T2) |
| a run's shared keys, in memory — `rc.state` | `capabilities.state_store.StateStore` | `State` |
| `state.json` — fingerprints, history, preconditions | `_primitives.state_store.StateStore` | `RuntimeStore` |
| `scopes.json` | `ScopeStore` | unchanged |
| `runs.json` | `RunStore` | unchanged |

**The file name and `state_root` do not move.** `state.json`, `state_root`,
`resolve_state_location` and `beside_state` are a user-visible path and a
public constructor argument; renaming the *class* fixes the collision a reader
actually hits, while renaming the *file* is a migration. Recorded as a decision
rather than an omission — if the file is renamed later it is its own change.

```
rg -c "^class StateStore" src/functualize/_engine/capabilities/state_store.py src/functualize/_primitives/state_store.py | awk -F: '{s+=$2} END {print s}'
```
now: `2` · after: `0`

## T9 · The lock's timeout is not silent

`[F]` `src/functualize/_primitives/state_format.py`,
`tests/primitives/test_store_concurrency.py`

`_acquire_lock` returns **without the lock** after 10s — *"advisory: proceed
rather than deadlock a build"*. That is the right default (a stuck lock must
not wedge CI) and it is the one path where two writers can lose an update. It
currently happens with no signal at all.

Emit a warning when it gives up, and add the concurrency test the three stores
never had: N threads and N processes writing distinct keys, then assert every
key survived.

```
rg -c "advisory: proceed" src/functualize/_primitives/state_format.py
```
now: `1` · after: `1` (invariant — the behaviour stays; only its silence goes)

## Task Dependency Graph

T1 and T5 touch no file any other task touches. T2 depends on T1 (it deletes
the class T1 lifts the parameter from). T3 and T4 are independent of each other
and of T2, but T6's assertions cover all three, and T7 documents T3's outcome.

```json
{"waves": [
  {"id": 0, "tasks": ["T1", "T5"]},
  {"id": 1, "tasks": ["T2", "T3", "T4"]},
  {"id": 2, "tasks": ["T6", "T7", "T8", "T9"]}
]}
```
