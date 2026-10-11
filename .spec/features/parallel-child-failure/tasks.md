# Parallel child failure tasks

Status: approved for Execute on 2026-10-11, including the plan's Long Method
tradeoff. The specification and `_app/impl.py` scope extension are approved.
The execution anchor is `AGENTS.md`, `.spec/CONSTITUTION.md`,
`.spec/ARCHITECTURE.md`, `.spec/TESTING.md`, optional `.spec/STATE.md`, and
this file. A fresh execution context must be prepared from that anchor.

## Wave 0 — remove forbidden class growth before behavior change

- [x] **1.1 Extract the private parallel batch collaborator.**
  - [F] `src/functualize/_engine/capabilities/invoke.py`.
  - Move the existing worker submission, collection, timeout sweep and
    nonblocking shutdown out of `WiredInvoke` into a private `_ParallelBatch`
    in the same module. Keep `WiredInvoke.parallel` as the API delegate. This
    step preserves the old result-only behavior and all signatures.
  - Acceptance: `WiredInvoke` is at most 500 lines by the AST count command
    below; no new peer-layer import; `uv run lint-imports` passes; and the
    current parallel, CLI and history tests remain green. The baseline count
    was **658** lines, so this gate is intentionally red until extraction.
    The baseline tests were **3 passed** direct property cases and **66 passed**
    context/CLI/history cases; import-linter reported **7 kept, 0 broken**.
  - Gate commands (run at authoring):
    ```bash
    uv run python - <<'PY'
    import ast
    p = 'src/functualize/_engine/capabilities/invoke.py'
    n = next(n for n in ast.parse(open(p).read()).body
             if isinstance(n, ast.ClassDef) and n.name == 'WiredInvoke')
    assert n.end_lineno - n.lineno + 1 <= 500
    PY
    uv run lint-imports
    uv run pytest -q --no-header tests/test_invoke_expanded.py -k TestParallelExecutionPreservesInputOrder
    uv run pytest -q --no-header tests/context/test_invoke_parallel_and_schema.py tests/pipeline/test_builtin_parallel.py tests/pipeline/test_history_producer.py
    ```
  - Reachability: job `RunContext.invoke_parallel` and top-level
    `FunctualizeApp.execute_parallel` both call `WiredInvoke.parallel`; after
    committing the extraction, briefly break its delegate, run a selected
    public-path test and verify failure, then restore safely.
  - Transitional marker: because task 2.1 adds the approved failure policy,
    label the result-only delegate `# TRANSITIONAL(2.1): ...` until that task
    resolves it. Update `.spec/STATE.md` with the actual interim behavior.

## Wave 1 — apply the approved failure contract

- [x] **2.1 Raise on failed child by default, preserve top-level reporting.**
  - [F] `src/functualize/_engine/capabilities/invoke.py`,
    `src/functualize/_app/impl.py`,
    `tests/context/test_invoke_parallel_and_schema.py`.
  - Add the keyword-only option to stub and wired signatures; classify ordered
    results with `Family.TOOL` after the existing collection; report every
    failed position/name/status and chain the first failed exception, if any.
    Keep success, skip, block, empty, max-32 and deadline behavior. The app
    caller passes `raise_on_failure=False`. Update the three context tests
    which presently expect returned failures from the default to expect a
    raised batch error; keep their sibling-completion assertions. The `rg`
    authoring hit set found **one** app call and **six** direct `rc.invoke_parallel`
    result assignments in that test file, of which three are failure cases.
  - Acceptance: the context tests, existing CLI reporting tests and history
    tests pass; a default failing child raises; top-level `execute_parallel`
    still returns the mixed list. No `raise_on_failure` reaches a child kwargs
    dict. `WiredInvoke` remains at most 500 lines. Remove task 1.1's
    transitional marker and update `.spec/STATE.md`.
  - Gate commands (run at authoring; baseline **66 passed**):
    ```bash
    rg -n 'return invoke\.parallel\(' src/functualize/_app/impl.py
    rg -n 'results = rc\.invoke_parallel\(' tests/context/test_invoke_parallel_and_schema.py
    uv run pytest -q --no-header tests/context/test_invoke_parallel_and_schema.py tests/pipeline/test_builtin_parallel.py tests/pipeline/test_history_producer.py
    ```
    The two `rg` commands identify the task's one app caller and six context
    assertions; after editing, review their output against this same hit set.
  - Reachability: engine parent job -> `RunContext.invoke_parallel` ->
    `WiredInvoke.parallel` -> `_ParallelBatch`; CLI -> public app facade ->
    `_app.impl.execute_parallel` -> same batch with explicit opt-out. Commit
    before separately sabotaging the failure check and app opt-out; each
    selected test must fail, then restore. No worker-pool lifecycle edit.

## Wave 2 — prove the external behavior and explain it

- [x] **3.1 Add capability and application regressions.**
  - [F] `tests/integration/test_declared_capabilities_e2e.py`,
    `tests/test_invoke_expanded.py`, `tests/test_invoke_stub_expanded.py`.
  - Cover an ignored one-of-three child failure through public
    `FunctualizeApp.execute`; three failures with repeated names and positions;
    completion order versus return order; opt-out mixed results and child-kwargs
    isolation; failure without an exception; cause identity; default and
    opt-out deadline behavior with released workers; empty and 32-job bounds;
    `SKIPPED` and `BLOCKED`; and stub keyword acceptance. Use events/finally
    to release any worker started by a timeout test. The existing context/CLI
    tests from task 2.1 provide the top-level mixed reporting assertion.
  - Acceptance: the new tests fail when their production path is sabotaged,
    pass on the implemented code, and the existing direct property tests still
    pass. Baseline authoring run of the integration and stub files was
    **68 passed**; the direct parallel property selection was **3 passed**.
  - Gate commands (run at authoring):
    ```bash
    uv run pytest -q --no-header tests/integration/test_declared_capabilities_e2e.py tests/test_invoke_stub_expanded.py
    uv run pytest -q --no-header tests/test_invoke_expanded.py -k TestParallelExecutionPreservesInputOrder
    ```
  - Reachability: the E2E case declares jobs and observes the parent result
    through `FunctualizeApp.execute`, not a constructed collaborator. Commit
    before sabotage and restore after the selected test fails.

- [x] **3.2 Publish the documented batch contract.**
  - [F] `docs/api/context.md`, `docs/guides/run-context.md`.
  - Make `docs/api/context.md` the canonical `invoke.parallel` reference:
    default raise, explicit `raise_on_failure=False` example using injected
    `Invoke`, failure statuses, ordering, deadline conventions and the fact
    that running threads cannot be interrupted. Correct the RunContext guide's
    always-return example and link to the reference. Do not imply the opt-out
    exists on `RunContext.invoke_parallel` or `Invoke.__call__`.
  - Acceptance: both pages accurately describe the implemented signatures
    and a reader can find the escape hatch. The authoring `rg` command below
    found **four** old `invoke_parallel(jobs)` references across precisely
    these two files; inspect all four during the edit.
  - Gate command (run at authoring):
    ```bash
    rg -n 'invoke_parallel\(jobs\)|results = rc\.invoke_parallel\(jobs\)' docs/api/context.md docs/guides/run-context.md
    ```

## Wave 3 — checkpoint before independent review

- [ ] **4.1 Verify the complete feature and hand it off.**
  - [F] `.spec/features/parallel-child-failure/tasks.md` (task state),
    `.spec/STATE.md` (gitignored phase state). Source fixes discovered by
    a failing gate go back into their owning earlier task before this is
    checked; this checkpoint does not silently widen its file scope.
  - Acceptance: all preceding tasks checked; no `TRANSITIONAL` marker for
    this feature; `ruff check`, `ruff format --check`, `mypy`, and
    `lint-imports` pass; relevant wave test directories pass; production
    reachability and safe sabotage results are recorded; the PR points at
    the delivered commit. Run the repo's dead-code delta script over dispatch
    base to delivered head and report findings as advisory. Do not self-review
    or self-verify, merge, release, or deploy.
  - Gate commands (run at authoring on baseline: ruff **pass**, format **1337**
    formatted files, mypy **388** files with no issues, import-linter
    **7 kept / 0 broken**; focused tests noted above):
    ```bash
    uv run ruff check src/ tests/
    uv run ruff format --check src/ tests/
    uv run mypy src/
    uv run lint-imports
    uv run pytest -q --no-header tests/context/test_invoke_parallel_and_schema.py tests/integration/test_declared_capabilities_e2e.py tests/test_invoke_expanded.py tests/test_invoke_stub_expanded.py tests/pipeline/test_builtin_parallel.py tests/pipeline/test_history_producer.py
    ```

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1"]},
    {"id": 1, "tasks": ["2.1"]},
    {"id": 2, "tasks": ["3.1", "3.2"]},
    {"id": 3, "tasks": ["4.1"]}
  ]
}
```
