# T15 Test Migration A — `app.execute(name, **kwargs)` → `app.execute(RunRequest)`

Scope: `tests/workflow/`, `tests/engine/`, `tests/integration/`, `tests/plugins/`,
`tests/context/`, `tests/pipeline/`. No git commands were run; no file outside
this scope was edited (the only non-test file written is this report).

## Recipe applied

- Plain: `app.execute(<job>, <args>)` → `app.execute(request_for(<job>, <args>))`.
- Control input (`scope_id=`): `app.execute(<job>, scope_id=S, k=v)` →
  `app.execute(RunRequest(job_name=<job>, surface="app.execute",
  kwargs={"k": v}, workflow_scope_id=S))`.
- `group_option_values=` never appeared in scope (0 sites), so every
  control-input migration was `scope_id` → `workflow_scope_id`.
- Imports added: `from functualize.app.core import request_for` and/or
  `from functualize.types import RunRequest`, merged into existing
  `functualize.*` import lines by isort.
- Inline comments inside an argument list were preserved. One site had one
  (`tests/workflow/test_launch_validation.py`, `# type: ignore[attr-defined]`
  after `app.execute(`); it was hand-restored onto the opening line.
- `conn.execute` / `cursor.execute` / `connection.execute` (15 calls, sqlite)
  and prose mentions of `app.execute()` in docstrings/comments were left
  untouched. Fake apps that already take `RunRequest`
  (`tests/plugins/test_mcp_tools.py`, `test_mcp_group_options_dispatch.py`) were
  left untouched.

## Files and call sites

| File | Call sites | Control-input | Plain |
|---|---:|---:|---:|
| tests/context/test_invoke_gate_wiring.py | 3 | 0 | 3 |
| tests/engine/test_workflow_gates.py | 11 | 0 | 11 |
| tests/integration/test_child_lazy_boot.py | 1 | 0 | 1 |
| tests/integration/test_cli_workflow_parity.py | 10 | 10 | 0 |
| tests/integration/test_declared_capabilities_e2e.py | 64 | 7 | 57 |
| tests/integration/test_lazy_true_engine_materialization.py | 3 | 0 | 3 |
| tests/integration/test_mcp_workflow_loop_e2e.py | 7 | 7 | 0 |
| tests/integration/test_part_i_remaining_cells.py | 8 | 6 | 2 |
| tests/integration/test_phase1_integration.py | 11 | 1 | 10 |
| tests/integration/test_workflow_as_job_e2e.py | 35 | 26 | 9 |
| tests/pipeline/test_history_producer.py | 7 | 0 | 7 |
| tests/plugins/test_gate_tool_narrowing.py | 6 | 6 | 0 |
| tests/plugins/test_mcp_gate_tool_policy.py | 12 | 12 | 0 |
| tests/plugins/test_mcp_workflow_tools.py | 43 | 43 | 0 |
| tests/workflow/test_cancel_is_terminal.py | 9 | 8 | 1 |
| tests/workflow/test_gate_drafts.py | 4 | 4 | 0 |
| tests/workflow/test_gate_payload_shape.py | 1 | 1 | 0 |
| tests/workflow/test_launch_validation.py | 22 | 16 | 6 |
| tests/workflow/test_scope_projection.py | 6 | 6 | 0 |
| tests/workflow/test_workflow_control.py | 4 | 4 | 0 |
| **Total (20 files)** | **267** | **157** | **110** |

Meaning preservation notes:

- Every migrated call keeps its job name, its job arguments, and (for the 157
  control calls) its scope identity — now named `workflow_scope_id` on the
  request instead of the deleted keyword. E.g. `test_launch_validation.py`'s
  `scope_id="a4"` resume cells still resume the same scope; the refusal cells
  still assert the graph did not run.
- No assertion was deleted, weakened, skipped, or xfailed; no `pytest.raises`
  was removed.
- `tests/engine/test_run_request_stdin.py` needed no change (it calls
  `engine.run(RunRequest(...))`, not the facade) and was left byte-identical.

## Verification (commands actually run)

### 1. No string-literal job names left at an `.execute(` call in scope

```
rg -n '\.execute\("' tests/workflow tests/engine tests/integration tests/plugins tests/context tests/pipeline | grep -v 'conn\.\|cursor\.\|connection\.'
```

Output: *(empty)*

AST cross-check over the same six directories: 267 `execute` calls on app-like
receivers, 267 of whose first argument is `request_for(...)` or `RunRequest(...)`,
0 others.

### 2. Lint and format

```
uv run ruff check tests/ && uv run ruff format --check tests/
```

```
All checks passed!
769 files already formatted
```

### 3. Tests

```
uv run pytest tests/workflow tests/engine tests/integration tests/plugins tests/context tests/pipeline -q -p no:randomly
```

```
26 failed, 1866 passed, 444 skipped, 3 warnings in 231.70s (0:03:51)
```

## The 26 failures are not from this migration — `src/` is incomplete

All 26 route through one stale call site in **`src/`**, which rule 2 puts out of
my hands:

```
src/functualize/app/_workflow_control.py:180
    return app.execute(_canonical(job_name), scope_id=scope_id, **kwargs)
```

`execute` no longer accepts `scope_id`, so every helper built on
`guarded_execute` raises `TypeError: FunctualizeApp.execute() got an unexpected
keyword argument 'scope_id'`. Static trace of the failing paths:

- `resume_scope` → `guarded_execute` (`_workflow_control.py:331`)
- `call_gate_tool` → `guarded_execute` (`_workflow_control.py:518`)
- MCP `WorkflowToolProvider._resume_workflow` / `_call_gate_tool`
  (`plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py:268,309`)
  call those two helpers.

Diagnostic run (2nd pytest invocation) confirming the frame:

```
uv run pytest "tests/plugins/test_gate_tool_narrowing.py::TestCallGateTool::test_a_permitted_call_runs_and_returns" \
  "tests/workflow/test_workflow_control.py::TestResumeAdvances::test_an_answered_scope_walks_to_completion" \
  -q -p no:randomly --tb=long
```

```
tests/workflow/test_workflow_control.py:110:
src/functualize/app/_workflow_control.py:331:
E       TypeError: FunctualizeApp.execute() got an unexpected keyword argument 'scope_id'
src/functualize/app/_workflow_control.py:180: TypeError
2 failed in 0.50s
```

Failure spread (all reduce to the same call site): 11 in
`tests/workflow/test_workflow_control.py`, 7 in
`tests/plugins/test_gate_tool_narrowing.py`, 4 in
`tests/plugins/test_mcp_workflow_tools.py`, 3 in
`tests/integration/test_cli_workflow_parity.py`, 1 in
`tests/integration/test_part_i_remaining_cells.py`. The non-`TypeError`
symptoms (`KeyError: 'return_value'`, `IndexError`, `assert 0 == N`) are the
refusal/error envelopes those helpers return once the inner call raises.

These 26 were red before my change too — beforehand the tests themselves passed
`scope_id=` straight into the new `execute`, which raises the identical
`TypeError` at the test's own line.

I did **not** edit `src/`. Fixing `_workflow_control.py:180` means building a
`RunRequest` with `workflow_scope_id=scope_id` and `kwargs=kwargs`; that is a
`src/` change and belongs to whoever owns the src half of this task.

## Tests I could not migrate

None. Every `app.execute` call in scope was migrated with its meaning intact.

## Questions (non-blocking)

1. Is `src/functualize/app/_workflow_control.py` (lines 180, and the
   `scope_id=` plumbing at 163/331/518) already assigned to another agent? If
   not, the 26 failures above stay red until it is migrated.
2. `src/functualize/_types/http_status.py:19` still contains a docstring example
   `app.execute(job_name, **job_kwargs)`; docstring-only, not touched by me.
