# Contracts: Workflow Launch Validation

External interfaces only. What a caller outside this feature can observe.

**Summary: no signature changes, no new exported symbols, no new types.** One
behavioral narrowing on an existing entry point, which propagates to every
surface that already forwards a `JobResult`.

---

## 1. `FunctualizeApp.execute`

`src/functualize/app/core.py:573` — the public entry point. **Signature
unchanged:**

```python
def execute(
    self,
    job_name: str,
    *,
    scope_id: str | None = None,
    group_option_values: dict[str, Any] | None = None,
    **kwargs: Any,
) -> JobResult: ...
```

### Narrowed behavior

| Call | Before | After |
|---|---|---|
| `execute('<workflow>', <accepted kwarg>)` | walks the graph | **unchanged** |
| `execute('<workflow>')` (DI-only signature) | walks the graph | **unchanged** |
| `execute('<workflow>', <unaccepted kwarg>)` | walks the graph, blocks or completes, fails at the epilogue | `FAILURE` before the graph walks |
| `execute('<plain job>', <unaccepted kwarg>)` | `FAILURE` | **unchanged** |

`scope_id` and `group_option_values` are unaffected. Neither is a job-function
parameter, and neither participates in the check.

### Guarantee on refusal

When the call is refused, **the runtime state store is not written.** No scope
record is created; an existing scope named by `scope_id` keeps its `status`,
`steps`, `gates` and `position` exactly as they were. This is the observable
that makes the acceptance criterion non-vacuous — status alone cannot
distinguish the two behaviors.

---

## 2. `JobResult` — the returned payload

`src/functualize/_types/descriptors.py:471`. **No field added, removed or
retyped.** The contract is on the values a refused launch produces:

| Field | Value on refusal |
|---|---|
| `status` | `RunStatus.FAILURE` |
| `exception` | a `TypeError` naming the function and the offending argument, in Python's own wording — e.g. `release() got an unexpected keyword argument 'zzz_nonsense'` |
| `return_value` | `None` |
| `job_name` | the workflow job's registered name |
| `duration_ms` | present; a launch refusal is fast, not zero |

The exception is **returned on the result, never raised.** Callers that today
distinguish success from failure by reading `result.status` keep working
unchanged; callers relying on `execute()` not raising keep that guarantee.

---

## 3. `RunContext.invoke` and `Invoke.__call__`

`_engine/capabilities/runcontext.py:365`, `_engine/capabilities/invoke.py:84,282`.

**Signatures unchanged.** These reach the same engine entry point, so a job
invoking a workflow job with an unaccepted argument gets the same `FAILURE`
result at launch. The shipped test double `MockInvoke`
(`testing/doubles.py:71`) is unaffected — no protocol member changes.

---

## 4. Trigger plugin surfaces

None of the three changes shape. Each already forwards whatever `JobResult`
`execute()` returns, so the visible difference is the *value* of the status
they surface, arriving earlier.

### `functualize-http`

`plugins/functualize-http/src/functualize_http/__init__.py:175`. Response stays
**HTTP 200** with the same JSON keys:

```json
{ "status": "failure", "duration_ms": 1.2, "return_value": null }
```

Previously this body carried `"status": "blocked"` for a mistyped field, and a
gate had been published as a side effect. The 400/404/500 branches are
untouched: a malformed body is still 400, an unknown job still 404, and a raised
exception still 500 — and a refused launch does not raise, so it does not become
a 500.

### `functualize-lambda`

`plugins/functualize-lambda/src/functualize_lambda/__init__.py:126`. Returns
`{"statusCode": 200, "body": result.return_value}`.

**Observation, not a change:** this handler ignores `result.status` entirely, so
a refused launch surfaces as `{"statusCode": 200, "body": None}` — the same
envelope it already produces for *any* failed job. This feature does not fix
that, and must not be described as fixing it. Recorded here because a reviewer
comparing surfaces will notice the asymmetry and should know it is pre-existing.

### `functualize-mcp`

`plugins/functualize-mcp/src/functualize_mcp/_server.py:272-276`. Emits
`result.status` into its tool result payload. An agent that sent a misspelled
argument now reads `failure` immediately instead of `blocked`, and no gate is
published for a person to answer.

---

## 5. Declaration surface

**Nothing added.** `@workflow(steps=..., edges=...)` is unchanged;
`functualize.workflow` exports the same names. No `Param` marker, no
`params=` argument, no new configuration key — those belong to
[`workflow-run-parameters.md`](../../shape-intents/workflow-run-parameters.md)
and are out of scope.

The decorated function's signature keeps its current meaning: DI capabilities
(`Log`, `Stdout`, …) and `FromJob` results are filled by the engine; anything
else is a caller-supplied argument bound to the epilogue. This feature checks
that binding earlier; it does not redefine it.

---

## 6. CLI surface

**Unchanged, and already correct.** click refuses an unknown option at parse
time before `execute()` is reached:

```
$ func lab release --zzz-nonsense 1
Error: No such option '--zzz-nonsense'.
```

No help text, exit code, or error wording changes. Verified at this base — the
CLI is the one surface that could not reach the defect, which is why it survived
to now.
