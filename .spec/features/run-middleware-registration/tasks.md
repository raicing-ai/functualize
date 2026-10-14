# Run middleware registration tasks

## 1.1 Single execution store and observed run

- [x] Initialize the execution chain once in each boot path, retaining
  `_middleware_registry` as an alias. Route both registration forms to the
  chain. Migrate the inspection test and add a real job run test that exercises
  bare and parameterized decorators alongside function registration.
- Files: `src/functualize/_app/boot.py`, `src/functualize/_app/impl.py`,
  `tests/core/test_app_extensions.py`,
  `tests/integration/test_plugin_config_flow.py`, `CHANGELOG.md`.
- Gate: the new integration test observes middleware state inside a real job;
  the relevant core and integration tests pass. The test must fail when the
  decorator-to-chain registration call is broken after a commit.

## 2.1 Verification checkpoint

- [x] Run formatting, lint, typing, import contracts, the selected test tier,
  and dead-code delta. Record the production call path and sabotage result.
- Files: no source writes.
- Gate: local checks pass or each failure is reported as an unresolved risk.

The production path is `HooksFacade.run_middleware` →
`make_run_middleware_decorator` → `register_run_middleware` →
`ExecutionMiddlewareChain.register` → `JobExecutionEngine` through
`build_engine`. The integration test failed on the original code with
`decorator_state=None`, passed after the change, then failed the same way when
the decorator's registration call was removed from committed source. Source
was restored to the committed version.

Verification: 67 passed, 1 skipped in the targeted core/integration files;
225 passed, 1 skipped in the `tests-for-diff --run` step tier. Ruff check,
Ruff format check, mypy, and import-linter passed. The dead-code delta is
advisory; its findings are classified in `plan.md`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] }
  ]
}
```
