# Parallel failure contract

Status: draft; not implemented. Confirm with `spec.md` before Plan.

## Job-author surface

```python
def parallel(
    self,
    jobs: Sequence[tuple[str | Callable[..., Any], dict[str, Any]]],
    *,
    timeout: float | None = None,
    raise_on_failure: bool = True,
) -> list[JobResult]: ...
```

The wired implementation retains its existing keyword-only `observer`.

| Outcome | `raise_on_failure=True` | `raise_on_failure=False` |
|---|---|---|
| No failing inputs | Ordered `list[JobResult]` | Same ordered results |
| Failed input | `RuntimeError` after collection | Ordered results, including failures |
| Unfinished input at deadline | `RuntimeError` after timeout classification | Ordered results, including `TIMEOUT` |
| Empty input | `[]` | `[]` |
| More than 32 inputs | Existing `ValueError` | Existing `ValueError` |

The failure set is `FAILURE`, `TIMEOUT`, `CANCELLED`, `REFUSED`, and `UNKNOWN`.
`SUCCESS`, `SKIPPED`, and `BLOCKED` do not cause the batch exception.

The exception message contains every failing input's position, name, and status
in submission order. Repeated job names retain distinct positions. The first
failed result's exception is the cause when one exists. No new exception class
or `JobResult` fields are introduced.

The keyword is consumed by the batch. Child kwargs remain the dictionaries in
the submitted pairs.

## Related existing surfaces

- `Invoke.__call__` retains its existing signature and single-job result policy.
- `RunContext.invoke_parallel(jobs)` inherits the safe default through its
  existing delegation. The explicit opt-out is available through the injected
  `Invoke` capability; extending the facade's signature is outside this draft.
- `FunctualizeApp.execute_parallel` retains its existing results/reporting
  contract. Its shared caller must select result handling explicitly, subject
  to the scope decision identified in `spec.md`.
- No CLI flag, delivery exit-code table, or parallel observer interface changes.

## Timing

The deadline remains a batch deadline. No exception or return path waits for
workers already reported as timed out. Python threads already running may
finish later; this contract makes no worker interruption guarantee.
