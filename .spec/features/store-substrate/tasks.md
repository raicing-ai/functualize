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

## T1 · The port exists, with a filesystem implementation — [x]

`[F]` `src/functualize/_types/protocols.py`,
`src/functualize/_types/errors.py`,
`src/functualize/_primitives/substrate.py` (new),
`tests/primitives/test_substrate.py` (new)

`StoreSubstrate` with `read` / `write(expect=)` / `lock`, and
`JsonFileSubstrate` reproducing today's behaviour exactly — same paths, same
`flock`, same atomic replace.

```
rg -l "class StoreSubstrate" src/ || echo missing
```
now: `src/functualize/_types/protocols.py` · before: `missing`

### Three shapes settled while building it

Recorded because each departs from `plan.md` R-a, and a silent departure is
indistinguishable from an oversight.

1. **`lock` is variadic — `lock(*keys)`, not `lock(collection)`.** R-a predates
   the re-measurement note at the top of this file. Spec §E.2 is the authority:
   *"one lock for everything this substrate holds has to be expressible in the
   port"*, because a lock per collection reproduces the inversion in a new place
   and the feature would then have moved the bug rather than removed it.

2. **Keys, not collections.** `scope_state_store` is one document per scope, so
   the fourth store's name is `scope-state/<scope-id>` — a slash-separated
   document name a substrate maps however it likes. `collection` stopped being
   the right word when the fourth store arrived.

3. **`read` returns `Stored(data, revision)`, not a bare envelope.** R-a has
   `read -> dict` and `write(expect=int)`, which cannot work: a caller that
   reads the document in one call and its revision in another has a window
   between them and would pass an `expect` describing a document it never saw.
   The two travel together or compare-and-swap is decorative.

   For the same reason the filesystem implementation **honours** `expect`
   rather than ignoring it as R-a permits — the revision is a content hash of
   the bytes on disk, so a stale compare genuinely returns False and the
   refusal is reachable by a test. A port member nothing honours is a gate that
   cannot fail, which is what T7 would have discovered first.

### Sabotage

Eight sabotages, each asserted to have applied before its result was read:
`expect` ignored (3 fail), revision constant (3), acquisition unsorted (2),
`lock` holding only the first key (2), traversal allowed (5), unreadable
degrading to None (3), missing reading as empty (1), `write` taking the lock
again (1).

The ordering one was **inert on the first pass** — a liveness test cannot fail
here, because `file_lock` gives up after ten seconds and proceeds rather than
deadlocking, so an inverted pair stalls and loses a write instead of hanging.
Replaced with an assertion on the acquisition order itself, which is what
sorting actually guarantees.

`write` deliberately does **not** take the lock: `file_lock` opens a fresh
descriptor and `flock`s it, so a nested acquire inside a caller that already
holds the key spins the full ten-second timeout, warns that writes can now be
lost, and proceeds. `lock` is how a caller gets exclusion; `expect` is how a
caller gets it back from a substrate that has none to give.

## T2 · The stores take a substrate, not a path — [x]

`[F]` `src/functualize/_primitives/{fresh,scope,run,scope_state}_store.py`,
`src/functualize/_primitives/shell_history.py`,
`src/functualize/_primitives/{fresh,scope,run}_format.py`,
`src/functualize/_types/{protocols,errors}.py`,
`src/functualize/_engine/executor.py`, `src/functualize/_app/impl.py`,
`src/functualize/_cli/builtins.py`, `src/functualize/app/utils.py`,
`src/functualize/testing/builder.py`, and 30 test modules

**Five stores, not three.** `scope_state_store.py` arrived with
`scope-record-lifecycle`/T3 (see the re-measurement note above);
`shell_history.py` arrived with `durable-run-layer`/T3b. Leaving the fifth on
paths would have made AC-4 false in the one place nobody would look.

No typed method changes. `__init__` takes a substrate and a key. The per-file
discard rules stay on the **store** — they are decisions about meaning, not
storage.

```
rg -c "open\(|write_text|fcntl|os\.replace|mkstemp" src/functualize/_primitives/{fresh,scope,run}_store.py | awk -F: '{s+=$2} END {print s+0}'
```
now: `0` · after: `0` — **invariant**: the stores touch no file today and must
still touch none. This gate cannot go green by accident; it can only go red.

Re-run over all five stores it returns `1`, and the hit is the *prose* at
`scope_state_store.py:19` explaining why one file per scope means one `flock`.
Exactly what the re-measurement note at the top predicted. Do not "fix" it by
editing the docstring.

### `beside_fresh` is deleted, not ported

It existed on three stores to apply the sibling rule to an already-resolved
path, so two stores could not land in different directories. There is now one
substrate handed to both, so there is no second resolution to keep in
agreement — the rule is not *enforced*, it is **unsayable**. That is AC-4, and
it is a fact about the type rather than a convention.

Two tests that asserted "the two resolutions agree" were rewritten to assert
"the two stores are handed the same object", because the thing they guarded
against can no longer be expressed.

### What the port cost

The port grew from three members to six, each with one caller a three-member
port would have stranded on the filesystem — recorded in `protocols.py` and
revising spec AC-1:

| member | the caller that needs it |
|---|---|
| `clear` | `func builtin data clear`, the way out of a document the reader refuses. Must not read what it moves. |
| `delete` | the scope-state purge. Runs per scope, so it must not keep a copy — and there is nothing to recover once the record is gone. |
| `describe` | `func builtin data show`, which exists to say where a person's data is. A key ending `/` describes a namespace, because scope state is one document per run. |

`tests/primitives/test_substrate.py::TestItSatisfiesTheProtocol` is what made
that growth visible: its two hand-written stand-ins stopped satisfying the
Protocol the moment a member was added.

### Two spies got simpler, and that is the result

`test_walk_coalescing.py` patched **two** names — `save_scopes` and
`update_scopes` — because a write could go through either and a spy that
missed one counted too few. `test_lease_fencing.py::_no_locking` patched
`scope_format.file_lock`, leaving the other two formats' locking real.

Both now patch one method on the substrate. The tests did not get easier to
write by accident: there was one write path and one lock path to patch because
the feature made there be one.

## T3 · `ScopeStore` becomes a peer; the facade is deleted — [x]

`[F]` `src/functualize/_primitives/fresh_store.py`,
`src/functualize/_engine/{frontier,workflow_walker,workflow_runner,executor,
dependency_runner,workflow_orchestrator}.py`,
`src/functualize/app/_workflow_control.py`,
`src/functualize/app/adapters/workflow_flags.py`,
`src/functualize/_cli/builtins.py`, `src/functualize/app/utils.py`,
`src/functualize/_app/impl.py`,
`plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`,
and 48 test modules

**33 pass-throughs, not 25** — the file is `fresh_store.py` since
`durable-run-layer`/T3b, and eight more forwarders were added after this task
was written, which is the growth the task predicted. They are **deleted**;
callers accept a `ScopeStore` instead.

```
rg -c "self\._scopes\." src/functualize/_primitives/fresh_store.py
```
now: `0` · before: `33`. `fresh_store.py` went 359 → 226 lines.

### Three renames vanish with the facade

`hold_scope_generation`, `scope_generation` and `scope_batch` existed only
because on a store that *also* held fingerprints, a bare `hold`,
`generation_for` or `batch` would not have said what it acted on. On a
`ScopeStore` the plain names are unambiguous, so the callers use them.

That rename moved a recorded gate: `durable-run-layer`/T6 counts `generation`
in `frontier.py` and it went 14 → 13.
`tests/spec/test_task_gates_still_hold.py` caught it, and the drift is recorded
there rather than re-recorded here.

### The rename found a live bug, because a defensive lookup hid it

`cancel_scope` took the lease and then held what it took, or it fenced *itself*
out — its own status write would carry the generation the store held before the
claim. That fix read the store through `getattr(store, "scope_generation",
None)` with a `callable` guard, and `hasattr` on the way back.

After the rename the guards matched nothing, so `previous` became `None`, the
hold was never set, and the self-fencing bug came back — **silently**, which is
what a defensive lookup against a type you control buys you. Two tests caught
it. Both lookups are now direct calls.

### Sabotage

Four, each asserted to have applied first:

| sabotage | result |
|---|---|
| cancel forgets to hold what it took | 2 fail |
| cancel never restores the caller's hold | 2 fail |
| `FreshStore.__getattr__` forwards to `_scopes` again | 1 fail |
| the engine caches one shared `ScopeStore` | **0 fail** |

The last one is recorded rather than fixed. `_scope_store()`'s docstring said a
fresh instance per call kept a parent's fence off a child's scope — that was
true before `durable-run-layer`/T6 keyed the hold *per scope*, and is not true
now. Confirmed by widening the sabotage across all of `tests/workflow/`,
`test_fenced_writes.py` and the nested-workflow end-to-end tests: 303 passed.
The method is kept for the ordinary reasons and the safety claim was deleted
from the docstring, because a comment asserting a property no test can lose is
the same defect as a gate that cannot fail.

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
