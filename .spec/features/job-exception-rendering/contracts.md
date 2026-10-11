# job-exception-rendering — contracts

## C1 — the process boundary (user-visible)

| Surface | Before | After |
| --- | --- | --- |
| stderr, job's own `Exception` | Python traceback, ~40 lines | `Error: <ExceptionClass>: <message>` (or `Error: <ExceptionClass>`) — one line |
| stderr, same, under `--log-level DEBUG` | Python traceback | Python traceback (unchanged) |
| stdout | whatever the job emitted | unchanged |
| exit code | 1 | 1 — `exit_code_for_status(RunStatus.FAILURE)`, table unchanged |
| `--emit-format` on a failure | no stdout document | unchanged; the stderr line does not vary with it |

`<ExceptionClass>` is `type(exc).__qualname__`, without a module prefix.

Both entry points (`func`, a project's `FunctualizeApp` + `CliAdapter` script),
cold and warm.

## C2 — `JobResult.metadata["raised_by_job"]` (internal)

- **Producer:** `JobExecutionEngine._execute_with_lifecycle`
  (`src/functualize/_engine/executor.py`). Sets `True` when the caught
  exception `is` an object that escaped `function(**call_kwargs)`; otherwise
  removes the key from the failure result's metadata. Never set on a result
  built anywhere else.
- **Consumer:** `deliver_job_result` (`src/functualize/app/adapters/click_params.py`),
  through `raised_by_job(result)`.
- **Vocabulary:** the key and the predicate live in
  `src/functualize/_types/outcome.py` — the layer both sides may import
  (`_types` → `_engine`, `_types` → `app`), so neither restates the string.

```python
RAISED_BY_JOB: Final = "raised_by_job"

def raised_by_job(result: Any) -> bool:
    """True when the exception on ``result`` escaped the job function call."""
```

`JobResult` itself gains no field: it is public surface
(`functualize.types.JobResult`), and a metadata key keeps this out of the
public API, its ADR and its example-coverage rule. The key is not documented
for job authors.
