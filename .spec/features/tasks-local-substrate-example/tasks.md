# Tasks — tasks-local substrate example

Only an unchecked task in the lowest incomplete wave may start. A task is
checked only after its gate passes; production-path tasks also need a
sabotage pass, run after a commit and restored.

## Wave 0 — the example on the substrate

- [ ] **1.1 — Rewrite `todo_local` against `FunctualizeApp(...).substrate`.**
  - Scope: `plugins/domains/functualize-tasks-local/examples/todo_local/todo_local.py`;
    `plugins/domains/functualize-tasks-local/examples/todo_local/test_todo_local.py`.
  - Gate: `uv run pytest plugins/domains/functualize-tasks-local/examples -v`
    passes (AC-1, AC-2, AC-3). Call path: `python todo_local.py …` →
    `FunctualizeApp` boot → `app.substrate` (`JsonFileSubstrate.for_project`)
    → `LocalTaskProvider._mutate`/`_read`. Sabotage: point `open_list` at a
    per-process throwaway substrate and watch the persistence and read-back
    tests fail; restore.

## Wave 1 — the README prints the example

- [ ] **2.1 — Rewrite the README Quick Start and storage claims.**
  - Scope: `plugins/domains/functualize-tasks-local/README.md`;
    `plugins/domains/functualize-tasks-local/examples/README.md`.
  - Gate: `test_the_readme_quick_start_is_this_example` passes (AC-4); the
    Quick Start commands, run verbatim in a fresh directory, print the shown
    output (AC-5); `git grep -n functualize_state -- plugins/domains/functualize-tasks-local`
    is empty (AC-6). Sabotage: change one character of the README's `python`
    block and watch the parity test fail; restore.

## Wave 2 — record and verify

- [ ] **3.1 — Changelog and gates.**
  - Scope: `CHANGELOG.md`.
  - Gate: `[Unreleased]` entry present (AC-7); `uv run ruff check src/ tests/ plugins/ examples/`,
    `uv run ruff format --check src/ tests/ plugins/ examples/`, `uv run mypy src/`,
    `uv run lint-imports` pass; the plugin's own suite
    `uv run pytest plugins/domains/functualize-tasks-local/tests -q` passes.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1"]},
    {"id": 1, "tasks": ["2.1"]},
    {"id": 2, "tasks": ["3.1"]}
  ]
}
```
