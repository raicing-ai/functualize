# Tasks — store substrate

Gates were run at authoring time from the worktree root on `6c77889`; `now:` is
what each command returned. **Not started** — this feature is written and held.

## Re-measured 2026-09-11 — what changed underneath

`scope-record-lifecycle`/T3 landed between authoring and now, and it moves this
feature's ground in three ways. Recorded here rather than left for whoever picks
it up to discover:

1. **There is a fourth store.** `_primitives/scope_state_store.py` holds one
   run's job state, one file per scope. T2's file list and gate below say
   *three*; they now mean four.
2. **T2's invariant still holds, and the gate needs one word.** Re-run over all
   four stores it returns `1`, not `0` — and the hit is a *docstring* mentioning
   `fcntl.flock`, not file I/O. The stores still touch no file. Add `-g` or
   match code only; do not "fix" it by editing the docstring.
3. **The feature gained a second, independent reason to exist.** It was
   motivated by one store per file with one seam. External review of T3
   (`.spec/reviews/scope-state-review.md` Q2.3) found a **lock-order
   inversion** between the scope lock and the state lock, reachable from user
   code in both directions:

   ```
   T1: with state.batch():        # holds STATE lock
           rc.track_phase(...)    # -> record write -> wants SCOPES lock
   T2: with store.batch():        # holds SCOPES lock
           store.set_state(...)   # -> wants STATE lock
   ```

   It cannot be fixed from inside the stores, because the *caller* chooses
   which batch to open first. One substrate with one lock removes it by
   construction. `scope-record-lifecycle/plan.md` reached the same conclusion
   from its surviving-smell #1 ("two files describe one run"), independently.

   **This means T1's `lock` is load-bearing, not incidental.** A substrate that
   exposes per-collection locks reproduces the inversion in a new place. The
   port has to make "one lock for everything this substrate holds" expressible,
   and T7's no-shared-disk case has to work under it.

## T1 · The port exists, with a filesystem implementation

`[F]` `src/functualize/_types/protocols.py`,
`src/functualize/_primitives/substrate.py` (new)

`StoreSubstrate` with `read` / `write(expect=)` / `lock`, and
`JsonFileSubstrate` reproducing today's behaviour exactly — same paths, same
`flock`, same atomic replace.

```
rg -l "class StoreSubstrate" src/ || echo missing
```
now: `missing` · after: the protocol's file

## T2 · The three stores take a substrate, not a path

`[F]` `src/functualize/_primitives/{state,scope,run,scope_state}_store.py`,
`src/functualize/_primitives/{state,scope,run}_format.py`

**Four stores, not three** — `scope_state_store.py` arrived with
`scope-record-lifecycle`/T3. See the re-measurement note at the top.

No typed method changes. `__init__` takes a substrate and a collection name.
The per-file discard rules stay on the **store** — they are decisions about
meaning, not storage.

```
rg -c "open\(|write_text|fcntl|os\.replace|mkstemp" src/functualize/_primitives/{state,scope,run}_store.py | awk -F: '{s+=$2} END {print s+0}'
```
now: `0` · after: `0` — **invariant**: the stores touch no file today and must
still touch none. This gate cannot go green by accident; it can only go red.

## T3 · `ScopeStore` becomes a peer; the facade is deleted

`[F]` `src/functualize/_primitives/state_store.py`,
`src/functualize/app/_workflow_answer.py`,
`src/functualize/app/_workflow_control.py`,
`src/functualize/app/adapters/workflow_flags.py`,
`src/functualize/_cli/builtins.py`, `src/functualize/app/utils.py`,
`plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`

25 of `StateStore`'s 36 methods are pure pass-through. They are **deleted**;
callers accept a `ScopeStore` instead. All five modules already take the store
by injection, so this is a type change rather than a rewiring.

```
rg -c "self\._scopes\." src/functualize/_primitives/state_store.py
```
now: `25` · after: `0`

## T4 · One choice moves all four stores

`[F]` `src/functualize/_app/boot.py`, `src/functualize/_engine/executor.py`,
`src/functualize/app/core.py`

The substrate is chosen once, at boot, and handed to every store. The
split-brain in spec §E becomes unreachable: there is no way to give the scope
records one backend and the state inside them another.

```
rg -c "StateStore\.for_project|ScopeStore\.beside_state|RunStore\.beside_state" src/ -g '*.py' | rg -v "_primitives/" | awk -F: '{s+=$2} END {print s+0}'
```
now: `17` · after: `0`

## T5 · The second seam is deleted

`[F]` `src/functualize/_engine/capabilities/protocols.py` (deleted),
`src/functualize/_engine/capabilities/workflow_scope.py`,
`src/functualize/_engine/capabilities/state.py`,
`plugins/functualize-state-sqlite/`

`StateStoreProtocol` and `WorkflowScope.replace_state_store` go. One seam, at
the substrate. Two seams at two levels is what produced the split-brain; keeping
the old one "for compatibility" reintroduces it (*Pre-Release Stance*).

`functualize-state-sqlite` is rewritten as a substrate, not a KV store — which
is what it was trying to be.

```
rg -c "replace_state_store|StateStoreProtocol" src/ plugins/ -g '*.py' | awk -F: '{s+=$2} END {print s+0}'
```
now: `28` · after: `0`

## T6 · `functualize-state` is removed, and the reason recorded

`[F]` `plugins/functualize-state/` (deleted), `contributor/adr/022-*.md`,
`examples/plugins/custom_state_backend/`, `docs/examples/plugins/`

Retired, not expanded — spec §B. The ADR records *why*, because a
backend-agnostic KV protocol is an idea that gets re-proposed: it can only
offer the intersection of every backend, which is worth least exactly where the
database is worth most.

```
test -d plugins/functualize-state && echo present || echo removed
```
now: `present` · after: `removed`

## T7 · A gate survives a machine with no shared disk

`[F]` `tests/integration/test_substrate_durability.py` (new)

**The criterion the feature exists for, and the easiest to fake.** Swapping the
substrate in one process proves nothing — the objects are still shared. Two
processes, no shared disk, substrate configured to something neither owns:
block at a gate in one, resume in the other.

`tests/integration/test_capability_duality.py::TestStateIsDurable` already does
the two-process trick for files and is the pattern to copy.

```
uv run pytest tests/integration/test_substrate_durability.py -q
```
now: `no such file` · after: passing

## T8 · The default is invisible, proved by swapping it

`[F]` `tests/conftest.py`, `tests/integration/test_substrate_durability.py`

The whole suite passes unchanged on `JsonFileSubstrate`, and passes again with
an in-memory substrate wired in. **That second run is this feature's sabotage
step**: if the suite only passes on files, something still reaches through the
port.

```
FUNCTUALIZE_SUBSTRATE=memory uv run pytest tests/ -q
```
now: `n/a` · after: passing

## T9 · Say so in the docs

`[F]` `docs/guides/deployment.md`, `docs/guides/workflows.md`

Gates need a durable store; here is how to configure one; the filesystem
default is fine on a laptop and not on Lambda. Currently **nothing** in `docs/`
says this.

```
rg -cl "durable.*store|persistent filesystem|serverless.*resume" docs/ | wc -l
```
now: `0` · after: `> 0`

## Task Dependency Graph

T1 is the port. T2 depends on it. T3 (peers) and T4 (one choice) both need T2
and touch disjoint files. T5 and T6 are deletions that need T4 landed. T7–T9
verify and document.

```json
{"waves": [
  {"id": 0, "tasks": ["T1"]},
  {"id": 1, "tasks": ["T2"]},
  {"id": 2, "tasks": ["T3", "T4"]},
  {"id": 3, "tasks": ["T5", "T6"]},
  {"id": 4, "tasks": ["T7", "T8", "T9"]}
]}
```
