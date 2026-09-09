# Contracts — surface-request-parity

External interfaces only.

---

## 1. `functualize.job` — `Invoke` gains one keyword

```python
class Invoke(Protocol):
    def __call__(
        self,
        job_name: str,
        *,
        group_option_values: Mapping[str, Any] | None = None,   # NEW
        config: ... = None,
        awaits_input: bool = False,
        available_tools: ... = None,
        force_gate: ... = None,
        gate_strategy: ... = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> JobResult: ...
```

`None` means **inherit the parent's values** — today's behaviour, and the default. A mapping
overrides for that call only. Additive; no existing call changes meaning.

`invoke_parallel` is **unchanged**, including `parent_scope=None` for items
(`_engine/capabilities/invoke.py:603`).

## 2. MCP — three doors, one input set

```jsonc
// run_job, run_job_async, and every per-job tool
{
  "job_name": "build",
  "arguments": { /* the job's own parameters */ },
  "group_option_values": { "verbose": true },   // NEW on run_job + async worker
  "scope_id": "wf-01H…"                          // NEW, explicit, schema-visible
}
```

`arguments` is a **nested object**, not top-level `**kwargs`. That is the change that makes
§3.3 true: a job parameter named `scope_id` lives inside `arguments` and cannot collide with
the control input beside it.

Per-job tools keep their generated schemas; `group_option_values` joins them as a declared
property, so the translator no longer advertises group fields an agent cannot pass.

## 3. HTTP — documented body keys

```jsonc
POST /jobs/{name}/execute
{
  "arguments": { /* the job's parameters */ },
  "group_option_values": { … },   // NEW
  "scope_id": "wf-01H…",          // NEW
  "force": false                   // NEW — reaches the request field
}
```

**Breaking**: a body was previously splatted whole as job arguments. Job parameters now live
under `arguments`. That is the fix, not a side effect — the old shape is what let `scope_id`
bind to a control parameter.

Documented in the plugin's README with a before/after example.

## 4. Lambda — the same shape, both handlers

The fat handler (`__init__.py:197`) and thin handler (`:159`) accept the same envelope as §3.
A gated workflow started over Lambda is resumable over Lambda by passing `scope_id`.

## 5. `functualize.app` — the splat is unrepresentable

`FunctualizeApp.execute` takes a `RunRequest` (F1's contract). This feature adds no signature;
it removes the last callers that built one from `**kwargs` at the boundary, and adds the test
that pins it.

## 6. Removed — the seal

No module under `src/functualize/app/adapters/` imports from `functualize._engine`. The five
imports removed:

| Was | Becomes |
|---|---|
| `lazy_command.py:87` → `_engine.capabilities.tty.terminal_available` | one shared route |
| `click_params.py:1069` → the same function, again | *(the second copy is deleted)* |
| `surface_gate.py:37` → `_engine.ambient.has_eligible_ambient` | public surface |
| `click_params.py:1064` → `_engine.executor` | not needed after F1 |
| `click_params.py:1230` → `_engine.missing_value.MissingValueError` | public error type |

## 7. Import contracts, tightened

`pyproject.toml`'s import-linter config gains a forbidden edge:
`functualize.app.adapters` **must not import** `functualize._engine`.

> The contract is the deliverable. Removing the imports without forbidding them leaves the
> door open and calls it closed.

## 8. Unchanged

- Every existing flag and parameter spelling.
- `parallel`'s independence.
- Pre-boot-only flags: aliases, `--exclude`, `--perf-report`'s lookahead.
- `RunRequest` — this feature adds no field.
