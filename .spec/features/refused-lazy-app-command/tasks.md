# Refused lazy app command tasks

## Wave 1

### [x] 1.1 Route refused lazy app jobs to the shared refusing command

Scope: `src/functualize/app/adapters/lazy_command.py`, `tests/cli/test_app_refused_call_rendering.py`.

Acceptance gate: `uv run pytest -x -q --no-header --basetemp ../pytest-refused-local tests/cli/test_app_refused_call_rendering.py tests/cli/test_invalid_call_rendering.py` passed (15 tests); the new test confirms cold/warm parity, exact refusal line, no frames, help, workflow and group arguments. The local basetemp keeps unrelated `/tmp/config.bak.*` out of project discovery. `uv run ruff check src/ tests/ plugins/ examples/`, `uv run ruff format --check src/ tests/ plugins/ examples/`, `uv run mypy src/`, and `uv run lint-imports` passed. The CLI wave passed (1990 tests, 428 skipped); approved-shape §11 passed unchanged.

Production path: `FunctualizeApp -> CliAdapter.run -> _build_job_command -> make_lazy_command -> _refused_parameter -> _refused_job_command`. After commit `9fb24fc6`, disabling the new guard made the app-script bare-call test fail on the old `Parameter 'p' was refused` line. The committed guard was restored; `git status --short` was clean before this task record was edited.

At authoring, the existing `func` gate file is `tests/cli/test_invalid_call_rendering.py`; the app sibling is absent and is the task's test output. The source scope was checked against the two command constructors and their shared refusal helpers.

## Task Dependency Graph

```json
{"waves": [{"id": 1, "tasks": ["1.1"]}]}
```
