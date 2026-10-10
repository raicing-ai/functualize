# job-exception-rendering — tasks

## Wave 1 — the engine knows who raised

- [ ] **T1 — mark the job's own exception on the result**
  - Files: `src/functualize/_types/outcome.py`,
    `src/functualize/_engine/executor.py`,
    `tests/engine/test_raised_by_job_mark.py` (new).
  - Do: add `RAISED_BY_JOB` + `raised_by_job(result)` to `_types/outcome.py`.
    In `_execute_with_lifecycle`, call the job through
    `_call_recording_escape`, and on the failure result apply
    `_mark_raised_by_job` after the `RunContext` metadata merge.
  - Invariants: the success path is unchanged; `JobResult` gains no field; no
    new import edge between peer layers.
  - Gate (spec AC3, engine half):
    `uv run pytest -q --no-header tests/engine/test_raised_by_job_mark.py` green —
    job raises → marked; middleware raises before the body or after a
    body that returned → unmarked;
    middleware re-raises the job's exception → marked; middleware plants the
    key in `context.metadata` and then raises → unmarked; success → unmarked.
  - Reachability: `engine.run()` → `_execute_lifecycle` → `_exec_policy().call(...)` → `_execute_with_lifecycle`
    → `_execute_job` → `_call_recording_escape`. Sabotage: drop the
    `_mark_raised_by_job` call and watch the "job raises → marked" test fail.

## Wave 2 — the boundary renders it

- [ ] **T2 — one line at the process boundary, traceback behind DEBUG**
  - Files: `src/functualize/app/adapters/click_params.py`,
    `tests/pipeline/test_exit_code_routing.py`,
    `tests/pipeline/test_job_exception_rendering.py` (new).
  - Do: `_renders_as_job_error(result)` and `_job_error_line(exc)`;
    `deliver_job_result` echoes the line and raises
    `SystemExit(exit_code_for_status(result.status))` when the result is
    marked, before its final `raise result.exception`.
  - Invariants: `BrokenPipeError`, pydantic `ValidationError`,
    `MissingValueError` arms unchanged and checked first; click signals and
    non-`Exception` `BaseException`s re-raised; exit-code table untouched.
  - Gate (spec AC1, AC2, AC4, AC5, AC6, AC7):
    `uv run pytest -q --no-header tests/pipeline/test_job_exception_rendering.py tests/pipeline/test_exit_code_routing.py`
    green, and `rg -n "raise result.exception" src/functualize/app` returns
    exactly one hit.
  - Reachability: `func <job>` → `_cli/main.py:_handle_job` →
    `invoke_command_capturing` → click → `wrapper` (cold) or
    `lazy_command` callback (warm) → `deliver_job_result`. The subprocess test
    runs both doors, each cold and warm. Sabotage: remove the new arm and
    watch the subprocess frame-absence test fail.

## Wave 3 — record and verify

- [ ] **T3 — changelog and native gates**
  - Files: `CHANGELOG.md`.
  - Do: one `[Unreleased]` entry describing the new rendering, the DEBUG
    opt-in and the classification rule.
  - Gate: `uv run ruff check src/ tests/ plugins/ examples/`,
    `uv run ruff format --check src/ tests/ plugins/ examples/`,
    `uv run mypy src/`, `uv run lint-imports` (7 kept, 0 broken), and the step
    tier: `uv run pytest -n auto -q --no-header $(.agents/skills/test-tiers/scripts/tests-for-diff)`.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": "W1", "tasks": ["T1"]},
    {"id": "W2", "tasks": ["T2"], "depends_on": ["W1"]},
    {"id": "W3", "tasks": ["T3"], "depends_on": ["W2"]}
  ]
}
```
