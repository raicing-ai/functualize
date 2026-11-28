# Plan — tasks-local substrate example

## Alignment

Dispatched as row A3 of the 0.5.0 pre-tag table: "tasks-local: the example and
README import the retired `functualize_state`", done when
"`pytest plugins/domains/functualize-tasks-local/examples` passes; README Quick
Start runs against the substrate". A docs-and-example change with no product
surface change; no shape file was raised for it.

## Architecture gate

Region: one example directory and one README. Retrieval run at
`8bd07003cbe61388f021af3c1f9967f2e8c494c3`:

- **zvec-grep** — Query: "Why was functualize-state retired in ADR-022,
  and how should tasks-local persist tasks via the app substrate?" The fresh
  repository index returned `contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md`
  (Decision), `docs/examples/plugins/custom-state-backend.md` (why the old
  `StateBackend` was retired), and this plugin's README. They confirm one
  storage choice per app: the old backend seam could split a scope's steps
  from its variables, while the provider now writes a `tasks` document to
  the selected substrate. This confirms the substrate premise.
- **Serena** — `get_symbols_overview` on `examples/todo_local/todo_local.py`
  returned `open_list` and `main`; on `_provider.py` it returned
  `LocalTaskProvider`. `find_symbol(LocalTaskProvider/__init__)` shows a
  `Callable[[], StoreSubstrate]` and `key=TASKS_KEY`, not a `backend=`
  argument. `find_referencing_symbols(LocalTaskProvider)` found the plugin's
  `_on_app_ready`, which constructs `LocalTaskProvider(lambda: app.substrate)`
  and provides `TaskProvider`. `find_referencing_symbols(FunctualizeApp/substrate)`
  found the example's `open_list` and its read-back test; the property returns
  `execution_engine.substrate`. This confirms the current public call path.
- **Graphify** — `get_neighbors("LocalTaskProvider")` returned an extracted
  incoming `_on_app_ready` call and outgoing provider methods. But this
  checkout's `graphify-out/graph.json` is stale: it locates the plugin at
  `plugins/functualize-tasks-local/...` and `_on_app_ready` has an old
  `TaskDocument` edge. The current files are under `plugins/domains/`, and
  `git grep -n "LocalTaskProvider(lambda: app.substrate)" --
  plugins/domains/functualize-tasks-local` finds the example, README, and
  plugin registration. Current source and Serena, rather than the stale edge,
  establish the dependency direction here.

`git grep functualize_state -- plugins/domains/functualize-tasks-local` is
empty. The repository-wide grep is not empty: history, this feature's spec,
the distinct live `functualize_state_memory` example, and scaffold fixtures
still contain the string. The gate is deliberately plugin-scoped; no history
is removed. The import-linter contracts govern `src/`; the example imports
only public packages (`functualize.app`, `functualize_tasks`,
`functualize_tasks_local`).

BEFORE:

```text
examples/todo_local/todo_local.py [plugin example]
  -> functualize_state.testing.InMemoryState   [retired by ADR-022; absent]  ✗ collection error
  -> functualize_tasks.Tasks(_provider=LocalTaskProvider(backend))           [stale signature]
README.md Quick Start
  -> functualize_state.InMemoryState                                          ✗ ModuleNotFoundError
  -> LocalTaskProvider(backend=...)                                           ✗ no such keyword
```

AFTER:

```text
examples/todo_local/todo_local.py [plugin example, public API only]
  -> functualize.app.FunctualizeApp [public app]  --boot-->  app.substrate
       -> JsonFileSubstrate.for_project(cwd)  [_primitives, reached through the public property]
  -> functualize_tasks_local.LocalTaskProvider(lambda: app.substrate) [plugin public]
README.md Quick Start == todo_local.py (byte for byte; asserted)
examples/todo_local/test_todo_local.py
  -> subprocess: python todo_local.py …  (one process per command)
  -> FunctualizeApp("reader").substrate.read("tasks")  (independent read-back)
```

Nothing crosses a layer boundary; the example's only path to `_primitives` is
the public `FunctualizeApp.substrate` property.

Skills consulted: `design-patterns-refactoring` (user-level). The BEFORE
carries **Duplicate Code** in its worst form — two hand-written copies (README
and example) of the same usage, which drifted independently and both broke.
The AFTER removes it: the README prints the example, and a test fails when
they differ. The candidate of keeping the job-shaped example (`checklist(rc)`
building its own provider) was rejected: it never reaches the app's substrate,
so it demonstrates nothing the plugin does.

## Surviving smells

- **Duplicate Code, contained** — the README carries a verbatim copy of
  `todo_local.py`. Accepted: a Quick Start must be readable without opening
  another file. The copy cannot drift silently because
  `test_the_readme_quick_start_is_this_example` fails on any difference. No
  maintainer review needed.

## Technical approach

1. Rewrite `todo_local.py` as a script over `FunctualizeApp(...).substrate`;
   rewrite its test to drive it through subprocesses in a project directory
   with `.functualize/`, read back through a fresh app, and pin README parity.
2. Rewrite the README's intro, Quick Start, Features and API Reference against
   the substrate; update `examples/README.md`.
3. `CHANGELOG.md` `[Unreleased]` entry; run the gates.

## Files

- `plugins/domains/functualize-tasks-local/examples/todo_local/todo_local.py`
- `plugins/domains/functualize-tasks-local/examples/todo_local/test_todo_local.py`
- `plugins/domains/functualize-tasks-local/README.md`
- `plugins/domains/functualize-tasks-local/examples/README.md`
- `CHANGELOG.md`

## Risks

- The example boots a full `FunctualizeApp` per command, so it loads every
  installed plugin; in the workspace that is ~1–2 s per process. Acceptable
  for an example; the test runs six processes.
- Running the Quick Start without `.functualize/` still works, but the list
  lands in the XDG cache keyed by project id (standalone mode), not beside
  the script. The README tells the reader to create the directory.
