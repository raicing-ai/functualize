# Research — findings that changed this feature's shape

Everything here was established by running a command or a probe, not by
reading. Where a claim is a negative ("nothing does X"), the falsifying command
is given so a future reader can re-run it rather than trust it.

## 1 · Why the capability map is passed explicitly, not held in a ContextVar

Asked directly during design: would `contextvars` or a singleton be a better
carrier than threading `caps` through? No, and the reasons are measurable.

**Contextvars isolate a binding; they do not make a value safe.**
`copy_context()` is a shallow snapshot of the var→value mapping. The thing we
need shared *is* a mutable dict, and every context would share that one object —
so contextvars protect nothing that matters here.

**The asyncio benefit does not apply: there is no asyncio.** Zero `async def`
in `_engine/`, no `iscoroutinefunction`, nothing awaits a job body. Even the
MCP tool named `run_job_async` is a bare `threading.Thread`
(`plugins/functualize-mcp/.../_tools.py:419`). Every concurrency boundary is a
thread: `invoke.parallel` (ThreadPoolExecutor, 32), `scheduler.py`, that MCP
door, and `shell.py`'s drain threads. Threads are exactly where contextvars do
not propagate.

```
rg -n "copy_context" src/          # -> no matches, anywhere
```

**Measured consequence, and a real defect.** The one propagation contextvar the
codebase has (`trace_id`) is already lost across a parallel batch:

```
serial  parent=f952bd1a  children=['f952bd1a']    -> INHERITED
batch   parent=35d736e8  children=['None','None'] -> LOST
```

Every `invoke_parallel` item is untraceable. No test covers it. **Out of scope
here** (it is an observability fix on a different axis) but it wants a task of
its own: `copy_context()` at the four submit sites.

**It is also not future-proof.** Per CPython docs, `sys.flags.thread_inherit_context`
defaults to **false** on GIL builds (threads start empty) and **true** on
free-threaded builds. `pyproject.toml` says `requires-python = ">=3.11"` with no
upper bound; CI tests 3.11–3.13. A free-threaded 3.14 is inside the supported
range and outside the tested one, and a contextvar design would quietly change
behaviour there. Explicit passing behaves identically on every build.

**Singletons** are forbidden by the Constitution (*"Global mutable state /
module-level singletons — breaks testability and DI"*) and the reason showed up
immediately: `perf_timeline` **is** a module-level singleton, and a mark from
one test leaked into the next test's same-named job while writing
`test_both_doors_land_in_one_timeline`. That assertion is containment rather
than equality for exactly this reason, with a comment saying so.

## 2 · The four paths state could travel, before T3

Mapped by running each one, not by reading:

| path | carried state? |
|---|---|
| `rc.invoke` parent ↔ children | yes |
| `@workflow` step → next step | **no** |
| `@workflow` step → epilogue | **no** |
| `state: State` (DI), anywhere | **no** |

Cause: `rc.state` returns the scope's store only `if self._workflow_scope is not
None`, and `nested_request` resets `parent_scope` unless a caller states it. The
orchestrator stated the scope *id* and never the scope *object*. The id names
which **records** a resume replays; the object is where the run's **state**
lives. Passing one without the other is what made "state between the steps of a
workflow" a reasonable belief that happened to be false.

## 3 · Five things wear the word "state"

| holds | class | file |
|---|---|---|
| one invocation's dict | `capabilities.state.State` | — |
| a run's shared keys | `capabilities.state_store.StateStore` | — (in memory) |
| fingerprints, history, preconditions | `_primitives.state_store.StateStore` | `state.json` |
| scope records | `_primitives.scope_store.ScopeStore` | `scopes.json` |
| the run log | `_primitives.run_store.RunStore` | `runs.json` |

The two classes called `StateStore` **share no code, no import and no
behaviour**. Grepping the name returns both. The three `_primitives` stores
*are* genuinely related: one upward walk locates all three files as siblings
(`StateStore.for_project`, then `ScopeStore.beside_state`, `RunStore.beside_state`).

## 4 · The on-disk stores are concurrency-safe; the timeout is the hole

Verified by reading all three write paths:

- **One lock per file** — `state_lock(path)` locks a `<file>.lock` sidecar, so
  the three never block one another. The sidecar exists so the lock outlives
  the atomic replace of the file it guards.
- **Read-modify-write inside the lock** — `update_state` / `update_scopes` /
  `update_runs` all re-read inside the lock, so two writers touching different
  records **merge** rather than clobber. Last-writer-wins per record, not per
  file.
- **Atomic write** — `tempfile.mkstemp` + `os.replace`.
- **Both boundaries** — `flock` across processes, and across threads too, since
  each `open()` creates its own file description.
- **Shared per project** — one upward walk to `.functualize/`, so two `func`
  processes in one project share all three files. That is what makes the
  locking load-bearing rather than decorative.

**The hole** (`state_format.py:276`): after 10s of contention `_acquire_lock`
returns *without* the lock — `# advisory: proceed rather than deadlock a
build`. Correct default, but it is the one path that can lose an update and it
is currently silent. There is no concurrency test for any of the three stores.
That is T9.

Separate caveat, not fixed: locking "degrades to a no-op where OS locking is
unavailable", so on a filesystem without working `flock` it is unprotected and
says nothing.

## 5 · Why `keys()` matches by glob

First draft used a bare prefix, which is a `startswith`: `keys("fetch")`
silently returned `"fetchmeta.x"` — a *different* job's namespace. The first fix
was to require a trailing dot, `keys("fetch.")`. The maintainer rejected that,
correctly: the dot reads as a typo rather than a rule, and nobody expects to
type it.

Glob costs no new code because the repo already has one matcher, and `*`
already stops at `.`:

```
keys("fetch.*")   -> ['fetch.ms', 'fetch.rows']     # fetchmeta.x excluded
keys("fetch.**")  -> + ['fetch.io.bytes']
keys("*.rows")    -> ['fetch.rows', 'report.rows']
```

It calls `_events._pattern_matcher.matches_pattern`, the same function behind
`rc.events.on_event("job.*")` and perf-phase filtering. A test asserts the two
never become two implementations — that being the exact divergence this whole
feature exists to remove.

## 6 · Why there is no in-memory state tier at all

**Maintainer decision, superseding the first plan.** The in-memory store was a
fallback for when no state plugin was installed. A fallback that empties on
resume is not one: the case you most need state in — a workflow that blocked at
a gate and came back — is precisely the case that loses it.

`WorkflowScope` holds the store and `app._scope_registry` holds the scopes, and
`_scope_registry` is reset to `{}` at boot (`_app/boot.py:297`), so a resume in
a new process got a fresh scope object and an empty store while its *step
records* came back fine from `scopes.json`. State was the one thing that did not
survive, which is the least defensible split possible.

So `State` is backed by `ScopeStore`. `scopes.json` is the right file by the
rule that file already states: it holds **records** — not recomputable,
refuse-on-corrupt — and job-written state is a record by that test, whereas
`state.json` may discard its contents on a bad read.

`StateStoreProtocol` (`capabilities/protocols.py`) already exists and is
already the plugin seam — `functualize-state-sqlite` implements it and calls
`WorkflowScope.replace_state_store`. That seam **stays**; what changes is the
default it replaces.

## 7 · Adjacent, deliberately not done here

- `copy_context()` for `trace_id` across `invoke_parallel` (§1).
- Renaming `state.json` / `state_root` / `beside_state`. T8 renames the
  *classes*, which is the collision a reader hits; the file name is a
  user-visible path and a public constructor argument, so it is a migration.
- The run-observability surface. Maintainer chose **API first, CLI as a
  consumer**: `app.runs.get(id)` returns the typed record and
  `func builtin why` formats what the API returns, computing nothing of its
  own — one projection, the same rule as the rest of this feature. That is
  `durable-run-layer`/T3, not this feature.
