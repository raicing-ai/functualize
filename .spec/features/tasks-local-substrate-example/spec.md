# tasks-local: the example and Quick Start run against the app's substrate

## Problem

`plugins/domains/functualize-tasks-local/examples/todo_local` imports
`functualize_state.testing.InMemoryState`. ADR-022 retired that package, so
`pytest plugins/domains/functualize-tasks-local/examples` fails at collection
with `ModuleNotFoundError: No module named 'functualize_state'`. The plugin
README's Quick Start imports `functualize_state.InMemoryState`, constructs
`LocalTaskProvider(backend=...)` (a keyword the provider no longer has), and
claims a dependency on `functualize-state` and a `tasks:` key prefix. The
provider stores every task in one substrate document named `tasks` and takes a
callable returning the substrate.

This is a docs-and-example change. No `src/` or `plugins/**/src/` file changes,
and no published behavior of the provider or the plugin changes.

## Behavior

1. The example is a script that boots `FunctualizeApp`, builds
   `LocalTaskProvider(lambda: app.substrate)` — the provider `LocalTasksPlugin`
   registers — and runs one command (`add`, `done`, `list`) per process,
   printing the list afterwards.
2. In a project directory holding `.functualize/`, the list persists between
   processes in the `tasks` document of the app's substrate
   (`.functualize/tasks.json` on the default filesystem substrate).
3. The README Quick Start prints the example script unchanged and the exact
   commands to run it, with their output.
4. The README describes storage as it is: one `tasks` document in the app's
   substrate; no `functualize-state` dependency and no `tasks:` prefix.

## Acceptance criteria

- AC-1 `pytest plugins/domains/functualize-tasks-local/examples` passes.
- AC-2 The example's test runs the script as separate processes and observes
  the list persisting between them.
- AC-3 The example's test reads the `tasks` document back through a fresh
  `FunctualizeApp(...).substrate`, not through the example's own provider.
- AC-4 The README's `python` block equals the example script byte for byte,
  asserted by the example's test.
- AC-5 The README Quick Start commands, run verbatim in a fresh directory,
  print the output the README shows.
- AC-6 `git grep functualize_state -- plugins/domains/functualize-tasks-local`
  returns nothing.
- AC-7 `CHANGELOG.md` `[Unreleased]` records the fix.

## Out of scope

- Declaring `tasks: Tasks` in a job. Discovery refuses it today because
  providers register at `APP_READY`, after discovery decides what is
  injectable; the core fix is separate work. The example uses the substrate
  path that works now.
- The plugin test standard's other rows for this plugin: conformance via real
  registration, persistence end-to-end on SQLite, the journey test, the
  uninstall sabotage and the CI leg.
- Stale wording in `plugins/**/src/**` docstrings and in `pyproject.toml`
  descriptions.
