# T15 Test Migration B — `app.execute(name, **kwargs)` → `app.execute(RunRequest)`

Scope: `tests/config/`, `tests/core/`, `tests/group_options/`, `tests/discovery/`,
`tests/execution/`, `tests/observability/`, `tests/cli/`, `tests/app/`, plus
`tests/test_state_split_regression.py`, `tests/test_fingerprint.py`,
`tests/test_middleware_chain.py`. No git command was run; no file outside this
scope was edited (the only non-test file written is this report).

## Recipe applied

- Plain: `app.execute(<job>, <args>)` → `app.execute(request_for(<job>, <args>))`.
- Control input — scope:
  `app.execute("wf", scope_id=S, k=v)` →
  `app.execute(RunRequest(job_name="wf", surface="app.execute",
  kwargs={"k": v}, workflow_scope_id=S))`. The old keyword `scope_id` is the
  field `workflow_scope_id`.
- Control input — group-CLI layer:
  `app.execute("d", group_option_values=G)` →
  `app.execute(RunRequest(job_name="d", surface="app.execute",
  group_option_values=G))`.
- Imports added: `from functualize.app.core import request_for` (merged into the
  existing `functualize.app.core` / `functualize.app` import block by isort) and
  `from functualize.types import RunRequest` where the control form is used.
- `conn.execute` / `cursor.execute` / `connection.execute` (sqlite, 7 calls in
  `tests/config/test_vault_staleness.py`, `tests/config/test_vault_store.py`,
  `tests/cli/test_vault_commands.py`) were left byte-identical, as were the
  click-command calls (`deploy.execute(["--env", "prod"])`,
  `node.execute([])`) and the middleware calls
  (`MiddlewareStack.execute(op_point, operation)` in
  `tests/observability/test_middleware_properties.py`,
  `MiddlewareChain.execute(context, operation)` in
  `tests/test_middleware_chain.py`) — none of those receivers is
  `FunctualizeApp` and none of their signatures changed.

## Files and call sites

| File | Call sites | Control-input | Plain |
|---|---:|---:|---:|
| tests/config/test_config_injection_pep563.py | 3 | 0 | 3 |
| tests/config/test_config_resolution_failure.py | 10 | 0 | 10 |
| tests/config/test_missing_config_prompt.py | 17 | 0 | 17 |
| tests/config/test_vault_staleness.py | 1 | 0 | 1 |
| tests/core/test_descriptor_declaration_authority.py | 3 | 0 | 3 |
| tests/group_options/test_combination_matrix.py | 8 | 3 | 5 |
| tests/group_options/test_group_options_injection.py | 1 | 0 | 1 |
| tests/group_options/test_group_options_missing_prompt.py | 5 | 0 | 5 |
| tests/discovery/test_job_deps_validation.py | 1 | 0 | 1 |
| tests/execution/test_runcontext_log_sink.py | 3 | 0 | 3 |
| tests/test_fingerprint.py | 2 | 0 | 2 |
| tests/test_state_split_regression.py | 5 | 5 | 0 |
| tests/app/test_facade_request.py | 0 (+2 assertion rewrites, below) | — | — |
| **Total (12 files + 1)** | **59** | **8** | **51** |

`tests/observability/` and `tests/cli/` had **0** `app.execute` call sites and
were not edited (`tests/cli/test_snapshot_recording.py` mentions
`FunctualizeApp.execute()` in prose only; left alone).

Meaning preservation notes:

- The 5 control migrations in `tests/test_state_split_regression.py` still join
  the **same** scope (`rel-1`) — now via a new module-level helper
  `_resume_release(app, scope_id="rel-1")` that builds the request with
  `workflow_scope_id=`. The resume/replay/clear assertions are unchanged.
- The 3 control migrations in `test_combination_matrix.py` still carry the same
  group-CLI dict into the same runs, so the `group-cli-*` matrix cells still
  assert the CLI layer wins over env/file/default.
- Job arguments were kept as job arguments: `request_for("report", city="Kyoto")`,
  `request_for("report", days=-1)`, `request_for("report", db={})`.
- No assertion was deleted, weakened, skipped, or xfailed; no `pytest.raises`
  was removed.
- Four docstrings/quotes that had become false were corrected (not assertions):
  `test_combination_matrix.py` module header,
  `test_group_options_injection.py` module header + `_execute` helper,
  `test_combination_matrix.py::test_omitting_the_facades_group_cli_layer_still_resolves_the_others`.

### The 2 assertions I rewrote rather than mechanically migrated

1. `tests/app/test_facade_request.py::test_request_and_extra_arguments_is_a_type_error`
   — `match="takes no other arguments"` was pinned to a custom message that
   `src/` no longer raises (actual: `got an unexpected keyword argument
   'scope_id'`). Now `pytest.raises(TypeError, match="scope_id")`: same
   behaviour (two answers to "what scope is this run in?" is refused by the
   call), matched on the offender's name instead of incidental wording.
2. `tests/app/test_facade_request.py::test_legacy_form_still_works_until_t15`
   → renamed `test_the_legacy_job_name_form_is_gone`. It pinned
   `TRANSITIONAL(run-request/T15)` — the very form T15 removes — so it cannot
   pass as written. Inverted rather than deleted: it now asserts
   `app.execute("greet", name="d")` raises `TypeError`, i.e. the accidental
   channel stays closed and nobody can re-add `**kwargs` to `execute` silently.
3. `tests/group_options/test_combination_matrix.py::test_the_facade_accepts_a_group_cli_layer`
   — asserted `inspect.signature(FunctualizeApp.execute)` has a keyword-only
   `group_option_values=None` parameter. The property it protects is that the
   facade path reaches the group-CLI layer and that omitting it equals passing
   nothing; it now asserts exactly that on `RunRequest`
   (`group_option_values={"env": "cli-env"}` round-trips; a request built without
   it has `None`). The behavioural half lives in
   `test_app_execute_resolves_every_reachable_layer[group-cli-*]`.

## Verification (commands actually run)

### 1. No string-literal job name left at an `.execute(` call in scope

```
rg -n '\.execute\("' tests/config tests/core tests/group_options tests/discovery tests/execution tests/observability tests/cli tests/app tests/test_state_split_regression.py tests/test_fingerprint.py tests/test_middleware_chain.py | grep -v 'conn\.\|cursor\.\|connection\.'
```

```
tests/observability/test_middleware_properties.py:96:        result = stack.execute("test.op", operation)
tests/observability/test_middleware_properties.py:163:        result = stack.execute("test.op", operation)
tests/observability/test_middleware_properties.py:220:            stack.execute("test.op", failing_operation)
tests/observability/test_middleware_properties.py:273:        stack.execute("test.op", operation)
tests/app/test_facade_request.py:96:        app.execute("greet", name="d")  # type: ignore[arg-type]
tests/test_state_split_regression.py:182:    request. The old `app.execute("release", scope_id=...)` keyword was the
tests/test_middleware_chain.py:403:        result = chain.execute("ctx", lambda: 42)
```

Not empty, and cannot be — see the first question below. Narrowed to the
receiver the rule is about, it is empty:

```
rg -n 'app\.execute\("' <same paths> | grep -v 'app\.execute("greet", name="d")' | grep -v 'test_state_split_regression.py:182'
```

```
(no output — exit 1)
```

The two excluded lines are deliberate: one is the inverted negative test, the
other is a docstring quoting the deleted keyword.

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
uv run pytest tests/config tests/core tests/group_options tests/discovery tests/execution tests/observability tests/cli tests/app tests/test_state_split_regression.py tests/test_fingerprint.py tests/test_middleware_chain.py -q -p no:randomly
```

```
4015 passed, 621 skipped in 153.87s (0:02:33)
```

Same selection, before this migration: `109 failed, 3906 passed, 621 skipped`
(147.45s). All 109 were in this scope and every one was a `TypeError:
FunctualizeApp.execute() got an unexpected keyword argument …` or the follow-on
`AttributeError: 'str' object has no attribute 'job_name'`.

`tests/_cli/` (a different directory from `tests/cli/`) is outside this scope and
was not run, so the two known-red items named in the task never entered my
verification.

## Tests I could not migrate

None. Every `app.execute` call in scope was migrated with its meaning intact;
the three rewrites above are recorded because they changed the *spelling* of an
assertion, not what it pins.

## Questions (non-blocking)

1. The verify grep quoted in the task (`rg -n '\.execute\("' … | grep -v
   'conn\.\|cursor\.\|connection\.'`) can never be empty in this scope: four
   hits are `MiddlewareStack.execute("test.op", operation)` and one is
   `MiddlewareChain.execute("ctx", …)`, both in scope but not `FunctualizeApp`,
   and the remaining two are the deliberate negative test and a docstring. If
   the intent was "no `app.execute` takes a string job name", the pattern should
   be `app\.execute\("` (empty, shown above).
2. `app.execute("greet")` — a bare string, no trailing keyword — does not raise
   `TypeError`; the string reaches the body and fails as `AttributeError: 'str'
   object has no attribute 'job_name'`. The annotation says `RunRequest` but the
   boundary does not enforce it. Not wrong per the spec and I did not touch
   `src/`; asking only in case a guard at the door (so the closed channel fails
   loudly and early) is wanted.
3. `request_for` is reachable as `functualize.app.core.request_for` but is not in
   `functualize.app.__all__`. I followed the recipe's import path; flagging in
   case the public re-export is intended.
