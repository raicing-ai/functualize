# Tasks

- [x] 1.1 Add a timed subprocess regression with two real proxies, a module that materializes the other proxy during import, and two worker threads. Show timeout on the previous code. Scope: `tests/execution/test_lazy_materialization.py`.
- [x] 2.1 Use `_IMPORT_LOCK` as the sole first-materialization guard and correct its scope comment. Scope: `src/functualize/_discovery/lazy_wrapper.py`. Gate: the new test and existing materialization tests pass.
- [x] 3.1 Correct durable behavior claims and verify reachability and quality gates. Scope: `.spec/STATUS.md`, `CHANGELOG.md`, tests and task ledger. Gate: selected tests, Ruff, mypy, and `lint-imports` pass; restoring the old proxy lock after a clean commit makes the regression fail.

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["1.1"]}, {"id": 1, "tasks": ["2.1"]}, {"id": 2, "tasks": ["3.1"]}]}
```
