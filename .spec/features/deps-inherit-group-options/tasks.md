# tasks.md — deps-inherit-group-options

## Wave 0 — the seam and its proof

- [x] **1.1 State the group-CLI layer on every `engine.dependency` request**

`DependencyRunner.run_node` (`src/functualize/_engine/dependency_runner.py`)
reads the dependent's request once (`context.request`), passes it to
`nested_request` as today, and additionally states
`group_option_values=<that request's group_option_values>` so the reset in
`nested_request` is overridden for the dependency surface — exactly the way
`invoke.py` states its caller's value. A comment at the line names the
carve-out and why a dependency differs from a step or an `rc.invoke` child.

- Files: `src/functualize/_engine/dependency_runner.py`
- Gate (run at authoring time): the AC-1..AC-4 tests below are red before the
  edit and green after it.

- [x] **1.2 Regression tests: the repro, the depth, the ladder, the CLI door**

New `tests/group_options/test_group_options_deps.py`, in the style of
`test_group_options_injection.py` (module-level `GroupOptions` class bound to
`group="demo"` with a `target` field; jobs registered on a `FunctualizeApp`;
runs through `app._execution_engine.run(RunRequest(...))`):

- **AC-1**: `report` with `deps=Deps("build")`, both injecting `DemoOptions`;
  run with `group_option_values={"target": "b"}`; the dependency resolved
  `target="b"` — asserted on a value the *dependency job body* recorded, not
  on the request object (a vacuous pass is ruled out by asserting the
  dependency actually ran).
- **AC-2**: a chain `report → build → prepare`; `prepare` (depth 2, scheduled
  from the same dependent's request) also resolved `target="b"`.
- **AC-3**: with `DEMO__TARGET=a` exported, the CLI `b` wins at the
  dependency; with no CLI layer, the dependency resolves `a` (today's
  resolution — the reset is still the default when nothing was typed).
- **AC-4**: `func demo --target b report` through the real dispatch — a
  project tree with `JOB_GROUP = "demo"` modules, run in-process through
  `_handle_group(["demo", "--target", "b", "report"], ...)`, asserting the
  dependency's resolved value off the process output.
- **AC-5**: no edits to `test_combination_matrix.py`,
  `test_invoke_group_options.py` or `test_nested_delivery_inputs.py`; they
  run green unmodified.

- Files: `tests/group_options/test_group_options_deps.py`
- Gate: `uv run pytest tests/group_options/test_group_options_deps.py tests/group_options/test_combination_matrix.py tests/execution/test_invoke_group_options.py tests/engine/test_nested_delivery_inputs.py -q`
  — exit 0.

## Wave 1 — the record and the audit

- [x] **2.1 Document the `Deps` carve-out**

`docs/guides/group-options.md` § "Steering a whole run from code": a
dependency inherits the group-CLI layer because it is part of fulfilling the
request that carried the flag; steps and `rc.invoke` children keep the
documented boundary. The "flag layer is not inherited" paragraph names the
carve-out rather than implying all nested runs.

- Files: `docs/guides/group-options.md`
- Gate: the section names `Deps` explicitly and no longer reads as a blanket
  prohibition over nested runs — verified by reading the rendered section.

- [x] **2.2 Reachability proof and the full check pass**

- Name the production call path (below), break it once (comment out the
  stated field in `run_node`), confirm the AC-1 test fails, restore. Commit
  before sabotaging.
- Run all five checks: `ruff check`, `ruff format --check`, `mypy src/`,
  `lint-imports`, and the step-tier pytest selection from
  `.agents/skills/test-tiers/scripts/tests-for-diff`.

Production call path: `_cli/main.py` (`_dispatch_group` collects
`walk.options`) → `app/adapters/click_params.py:build_job_engine_callback` →
`app/adapters/_request_builder.py:build_request(group_option_values=...)` →
`_engine/executor.py:run` → `_execute_lifecycle` →
`_engine/dependency_runner.py:run_for/run_node` → **the line this feature
adds** → `nested_request` → `engine.run(dep)` → `_execute_lifecycle` →
`_resolve_group_options` — the dependency's parameter.

- Files: none (proof only)
- Gate: sabotage red / restore green on AC-1; all five checks exit 0.

Evidence: removing the group-option pass-through made AC-1 fail with
`prepare=a`, `build=a`, `report=b`; restoring the committed line made AC-1 pass.
The wave suite passed 79 tests. Ruff, mypy, and import contracts passed. The
commit-range task-graph check found one contract-bearing path and the graph.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": ["1.1", "1.2"]
    },
    {
      "id": 1,
      "tasks": ["2.1", "2.2"]
    }
  ]
}
```
