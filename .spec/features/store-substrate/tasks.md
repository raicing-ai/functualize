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

## T4 · One choice moves all four stores — [x]

`[F]` `src/functualize/_primitives/substrate.py`,
`src/functualize/_primitives/{fresh,scope,run}_store.py`,
`src/functualize/_primitives/shell_history.py`,
`src/functualize/_app/boot.py`, `src/functualize/_app/impl.py`,
`src/functualize/_engine/executor.py`,
`tests/primitives/test_one_substrate_choice.py` (new)

The substrate is chosen in **one function**, and every store's `for_project`
routes through it. The split-brain in spec §E becomes unreachable: there is no
way to give the scope records one backend and the state inside them another,
because there is one place that decides and one object handed to both.

### The gate as written no longer measures anything

```
rg -c "StateStore\.for_project|ScopeStore\.beside_state|RunStore\.beside_state" src/ -g '*.py' | rg -v "_primitives/" | awk -F: '{s+=$2} END {print s+0}'
```
now: `0` · before: `0` — **and it was already 0 before this task ran.** Every
name in it is gone: `StateStore` was renamed by `durable-run-layer`/T3b, and
`beside_state`/`beside_fresh` were deleted in T2. The recorded `17` described a
tree that no longer exists. A gate that passes because its subject was renamed
is the failure mode `tests/spec/test_task_gates_still_hold.py` exists to find,
so it is replaced rather than quietly kept green:

```
rg -c "JsonFileSubstrate\.for_project\(" src/ -g '*.py' | awk -F: '{s+=$2} END {print s+0}'
```
now: `1` · before: `4` — the one place that names the filesystem substrate. The
trailing `(` matters: four docstrings in `_primitives` *mention*
`JsonFileSubstrate.for_project`, and a grep without it answers with prose. The
test does the same count by walking the AST, with a guard that the walk found
calls at all.

### Not cached, deliberately

`substrate_for_project` re-resolves on every call. A cache keyed by path would
be module-level mutable state — forbidden outright — and would also be wrong:
the CLI changes directory and so do the tests, so a memoised answer hands the
second project the first one's documents, silently, in a way that looks like
data loss.

The *engine* caches one, because it has a run's lifetime. A run touches the
ledger, the records, the state inside them and the run log; resolving per store
is four upward walks per run and, once a substrate is configurable, four
chances to be told a different answer halfway through.

### Sabotage

Three, each asserted to have applied first:

| sabotage | result |
|---|---|
| `RunStore.for_project` resolves its own substrate | 2 fail |
| the one decision memoises by path | 1 fail |
| the engine resolves per store instead of holding one | 2 fail |

The first is what AC-4 forbids and it is caught by redirecting the decision's
**body** — not by rebinding its name. Rebinding would not reach the stores at
all (they import the function by name), and patching each store's own binding
would assert exactly the convention this feature replaced.

## T5 · The second seam is deleted — [x]

`[F]` `src/functualize/_engine/capabilities/protocols.py` (deleted),
`src/functualize/job/_protocols.py` (deleted),
`src/functualize/_engine/capabilities/workflow_scope.py`,
`src/functualize/_engine/capabilities/state.py`,
`src/functualize/_types/protocols.py`, `src/functualize/app/core.py`,
`src/functualize/_app/impl.py`, `src/functualize/_engine/executor.py`,
`plugins/functualize-state-sqlite/` (rewritten),
`tests/core/test_scope_state_metadata.py`,
`tests/context/test_state_store_protocol.py` (deleted),
`tests/test_facade_loc_limits.py`

`StateStoreProtocol` and `WorkflowScope.replace_state_store` are gone. One seam,
at the substrate.

```
rg -c "replace_state_store|StateStoreProtocol" src/ plugins/ -g '*.py' | awk -F: '{s+=$2} END {print s+0}'
```
now: `4` · before: `28` — **and all four are prose**, in docstrings explaining
the deletion. The same failure this branch has now hit three times: a grep
answered by the sentence describing the thing. Measured properly by AST —
attribute accesses, names and defs — it is **0**:

```
python3 -c "import ast,pathlib; …"   # see tests/spec/, same shape as the
                                     # SIGALRM and kill gates
```

### How a plugin installs a backend now

`EngineHost.substrate`, set at `APP_READY`. The engine prefers the host's and
otherwise resolves the filesystem default — one member, chosen once, and every
store follows.

`_primitives` could not have discovered it: `substrate_for_project` may not
import `_plugins` or `_config`, they are peer layers. So the composition root
chooses and the engine is handed the answer, exactly as `fresh_root` works.

Installing **after** the engine has resolved one is refused rather than
half-applied (`_app/impl.py::install_substrate`), because a late install leaves
some of a run's documents in one backend and some in the other — the split
brain arriving through a different door.

### The facade tripwire caught the addition

`FunctualizeApp` went 9 executable lines over its 300 budget. Moving the
setter's guard to `_app/impl.py` took it to +2; the budget was then raised to
**302**, deliberately, in `tests/test_facade_loc_limits.py` with the reason —
which is the third answer that file's own failure message names. No headroom
added: a tight ceiling raised to exactly what fits still binds the next
addition.

### `functualize-state-sqlite` is now a substrate

`SQLiteSubstrate` — one table, six methods — plus a plugin that installs it.
Deleted with the KV design: `_backend.py`, `_execution_store.py`,
`sqlite_backend.py`, `state_store.py`, `tracker.py`, `_migrations.py`,
`plugin.py` and three test modules.

It is the first implementation that makes the port a port rather than an
interface drawn round one class, and two of its properties are tested as
behaviour:

- **One lock.** A transaction covers every key, so the two orders that
  deadlock a per-file substrate both complete. `JsonFileSubstrate` can only
  sort within one `lock()` call, which does not help a caller that takes one
  lock, does something, and takes another.
- **Compare-and-swap with no lock held.** Two threads racing one revision:
  exactly one wins. On the filesystem `expect` is only exact under the
  caller's `flock`.

`tests/…/test_sqlite_substrate.py::test_no_store_asks_the_substrate_for_a_path`
wraps the substrate so `path_for`, `root` and `path` raise, then drives all
three stores. A store reaching for a filesystem detail would work on a laptop
and fail on any backend without one — the failure this feature exists to
prevent, arriving at the last moment.

## T6 · `functualize-state` is removed, and the reason recorded — [x]

`[F]` `plugins/functualize-state/` (deleted),
`plugins/functualize-tasks-local/` (ported),
`plugins/functualize-mcp/src/functualize_mcp/_history_tools.py` (ported),
`plugins/functualize-ai/src/functualize_ai/_state_fallback.py`,
`pyproject.toml`, `plugins/*/pyproject.toml`,
`src/functualize/_cli/data/plugin_catalog.toml`,
`src/functualize/_cli/builtins.py`, `src/functualize/_cli/scaffold/cli.py`,
`contributor/adr/022-*.md`, and 9 test modules

```
test -d plugins/functualize-state && echo present || echo removed
```
now: `removed` · before: `present`

### The blast radius was five plugins, not one

The recorded `[F]` named the package, an ADR and one example. Measured, five
plugins imported `functualize_state`, and only two of those imports were the
optional probes the task assumed:

| plugin | what it used | what happened |
|---|---|---|
| `functualize-tasks-local` | `StateBackend`, at import time | **ported** — tasks live in one substrate document |
| `functualize-mcp` | `ExecutionStore` | **ported** — the tools read the run log |
| `functualize-ai` | an import probe | probe deleted; it would have answered "no" forever |
| `functualize-ai-pydantic` | an import probe | same |
| `functualize-state-sqlite` | the whole domain | rewritten by T5 |

Plus nine test modules, the plugin catalog, two `pip install` hints and three
`pyproject.toml` files.

### The MCP port is the argument for the deletion, in code

`get_job_history` could not ask the `ExecutionStore` for recent executions —
the protocol had no such method — so it probed for four
(`get_all_executions`, `get_recent_executions`, `get_session_executions` with
an empty session, then with the app's session) and took whichever the installed
backend happened to have. Its tests used a fake implementing all four, so they
were more capable than any real backend and could not say which path an install
would take.

That is what "the intersection of every backend" costs: a caller guessing at
five shapes because the contract cannot express the question. The run log
answers it in one call, and the MCP surface and `func builtin history` now
report one set of facts instead of two.

The tools also register **unconditionally** now. They used to appear only if
`functualize-state` was importable, so on an ordinary install they were simply
absent and the absence looked like a missing feature.

## T7 · A gate survives a machine with no shared disk — [x]

`[F]` `tests/integration/test_substrate_durability.py` (new),
`src/functualize/_cli/builtins.py`,
`src/functualize/app/_workflow_control.py`,
`src/functualize/app/adapters/workflow_flags.py`,
`plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`

```
uv run pytest tests/integration/test_substrate_durability.py --run-slow -q
```
now: passing (4 tests) · before: `no such file`

### What "no shared disk" means on one machine

Two processes with **different working directories and different
`.functualize/` directories**, joined only by the substrate. The framework's own
file layout is what a resumed run used to depend on; if any of it still carried
the state, the second worker would find nothing, because it is looking
elsewhere.

Not claimed: that a *remote* substrate works. SQLite is a local file. This shows
the store stack is substrate-addressed, which is the prerequisite.

The falsifier is its own test: after a full block-and-resume, neither worker's
`.functualize/` may hold `fresh.json`, `scopes.json`, `runs.json`,
`shell-history.json` or a `scope-state/` directory. `cache.json` is explicitly
allowed — the discovery cache is derived from that checkout's own sources and
has always been per-worker. An assertion of "no `.json` at all" failed on it and
would have said nothing true.

### It found four stores still reading the filesystem

This is what T7 is for, and it earned its place immediately. T5 wired the
*engine* to the host's substrate but left four app-layer stores resolving
`for_project(Path.cwd())`:

| site | symptom |
|---|---|
| `workflow_flags._store` | `--wf-resume <id>` → "No workflow scope" for an id that existed |
| `_workflow_control.WorkflowControl.store` | `advanceable_scopes`, `cancel`, `purge` blind to the database |
| `_cli/builtins._workflow_store` | `builtin workflow list` empty |
| MCP `_workflow_tools` | the same, over MCP |

All four now take the app's substrate. Three CLI commands gained
`@click.pass_context` to reach the app, which is how the other subcommands
already do it.

### Recorded, not fixed: a lockless backend needs a retry loop

The stores do `with lock(key): read; mutate; write(...)` and **ignore what
`write` returns**, which is correct while `lock` provides exclusion. A backend
that cannot lock — DynamoDB, S3 — would make `lock` a no-op and rely on
`expect`, and then a `False` return means "someone else wrote, re-read and
retry" and nothing retries.

Not in scope here: SQLite locks, so no shipped implementation exercises it, and
inventing the loop now would be a retry path with no failing caller — the
gate-that-cannot-fail shape this branch keeps deleting. It belongs with the
first lockless substrate, and is written down so that feature starts from it.

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
