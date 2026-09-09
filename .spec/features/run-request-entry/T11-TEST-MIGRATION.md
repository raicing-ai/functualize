# T11 Test Migration Report

## Files Changed and Call Sites

### Original 15 files (engine.execute → run_job/engine.run)

| File | Call sites | Migration |
|------|-----------|-----------|
| tests/test_shell_capability.py | 1 | `engine.execute` → `run_job` |
| tests/test_invoke_expanded.py | 1 | `engine.execute.side_effect` → `engine.run.side_effect` (mock) |
| tests/test_lazy_wrapper.py | 2 | `engine.execute.return_value/call_args` → `engine.run.return_value/call_args` (mock) |
| tests/context/test_parallel_and_log_properties.py | 1 | Comment update only |
| tests/core/test_app_interactivity.py | 1 | Docstring update only |
| tests/core/test_dynamic_job_registration.py | 2 | `engine.execute` → `engine.run(RunRequest(...))` |
| tests/core/test_scope_state_metadata.py | 4 | `engine.execute` → `run_job` |
| tests/engine/test_engine_run_entry.py | 1 | `engine.execute` comparison test rewritten to `engine.run` only |
| tests/execution/test_engine_interactivity.py | 6 | `engine.execute` → `run_job` |
| tests/execution/test_engine_pre_execute.py | 8 | `engine.execute` → `run_job` |
| tests/execution/test_lazy_materialization.py | 1 | `engine.execute` → `run_job` |
| tests/group_options/test_combination_matrix.py | 1 | `engine.execute` → `engine.run(RunRequest(...))` |
| tests/group_options/test_group_options_injection.py | 1 | `engine.execute` → `engine.run(RunRequest(...))` |
| tests/hooks/test_before_job_kwargs_properties.py | 1 | Docstring update only |
| tests/validation/test_validation_hooks_property.py | 4 | `engine.execute` → `run_job` |

### Additional CAUSE A files (Job not found in engine registry)

| File | Tests | Fix |
|------|-------|-----|
| tests/observability/test_job_instrumentation.py | 4 | Added `register()` call in `_build_cli` to register jobs with engine |
| tests/discovery/test_registry.py | 4 | Added `app.register_dynamic_job()` before invoking wrapped command |
| tests/config/test_unified_config_integration.py | 7 | Added `register()` call before invoking wrapped command |

### Additional CAUSE B files (FakeApp execute signature stale)

| File | Tests | Fix |
|------|-------|-----|
| tests/plugins/test_mcp_tools.py | 3 | `FakeApp.execute(self, job_name, **kwargs)` → `execute(self, request: RunRequest)` |
| tests/plugins/test_mcp_group_options_dispatch.py | 4 | `_RecordingApp.execute(self, job_name, *, group_option_values, **kwargs)` → `execute(self, request: RunRequest)` |

## Verification Commands

### 1. Grep count (must be 0)
```
grep -rn 'engine\.execute\|execution_engine\.execute' tests/ plugins/*/tests/ | wc -l
```
Result: **0**

### 2. Ruff check and format
```
uv run ruff check tests/ && uv run ruff format --check tests/
```
Result: **PASS** (after fixing import sorting issues)

### 3. Pytest on affected files
```
uv run pytest tests/execution tests/engine tests/core tests/hooks tests/validation tests/group_options tests/context tests/observability tests/discovery tests/plugins tests/config/test_unified_config_integration.py tests/test_shell_capability.py tests/test_invoke_expanded.py tests/test_lazy_wrapper.py -q -p no:randomly
```
Result: **3077 passed, 665 skipped, 3 warnings**

## Pre-existing vs New Failures

All failures were **pre-existing** (CAUSE A and CAUSE B) — they existed before the current engine change:
- **CAUSE A**: Tests that never registered jobs with the engine (relied on the old `execute(job_name, function, ...)` signature carrying the function)
- **CAUSE B**: FakeApp classes with stale `execute(self, job_name, **kwargs)` signatures from an earlier MCP door migration

No tests were weakened or skipped. All migrations preserve the original test meaning.

## Questions

None.
