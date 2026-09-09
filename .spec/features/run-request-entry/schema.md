# Schema — run-request-entry

Internal shapes. The external contract is `contracts.md`.

---

## 1. What `engine.run` does with a request, in order

`run(request)` is the resolution step and nothing else — it ends by calling the lifecycle it
already called.

```
run(request)
  1. entry = self.get_job(request.job_name)          → JobNotFoundError if absent
  2. self._ensure_materialized(entry)                 → imports once, then no-ops
  3. config_class = entry.config_class or detected    → the derivation execute() already did
  4. config_fields, job_kwargs = split(request.kwargs, config_class)
  5. job_kwargs = resolve_stdin_markers(job_kwargs)
  6. return self._execute_lifecycle(...)              ← UNCHANGED, 20 steps, same order
```

Steps 4 and 5 are the moved code — from `app/adapters/click_params.py:1099-1104` and
`:1108-1124` respectively. **They must move verbatim.** They are the riskiest part of the
feature because a silent change shows up as a missing config value, not an error.

Step 3 is why `config_class` leaves the public call: `execute()` already re-derived it at
`:390` (`entry.config_class or detected_config`), so passing it at `:1221` and `:1800` was
always redundant.

## 2. The request builder — one, shared by both click paths

`app/adapters/_request_builder.py`:

```python
def build_request(
    *, job_name: str, surface: Surface, click_ctx: click.Context,
    params: Mapping[str, Any], app: FunctualizeApp,
) -> RunRequest: ...
```

Both the eager callback (`click_params.py:1148`) and the lazy one (`lazy_command.py:153`) call
it. `pitfalls.md` §23 — *two dispatch paths, one result-handling contract*: they already
converge on `deliver_job_result`; after this they converge on the request too.

**The property that pins it:** for one argv, both paths produce **equal** requests. That is a
test, not a convention (`tasks.md` T5).

## 3. `Surface` — a closed set, and why it is `Literal` rather than `Enum`

```python
Surface = Literal["func.job", "func.group", …, "engine.dependency"]
```

`Literal` rather than `Enum` for two reasons:

- It is stdlib-typing only, so `_types/run_request.py` stays importable by every layer with no
  runtime object to construct.
- A wrong value is a **mypy error at the door that wrote it**, not a runtime lookup failure
  three layers later. A new door that forgets to declare itself fails type-checking.

Runtime validation still happens in `__post_init__`, because a plugin outside this repo is not
type-checked by our CI.

The naming is `<family>.<variant>` so a prefix match answers "all MCP runs" without a second
table.

## 4. What the deposit protocol becomes, field by field

| Was | Read at | Becomes |
|---|---|---|
| `app._prompt_gates` | `executor.py:1283`, `getattr(…, False)` | `request.prompt_gates` |
| `app._output_format` | `stdout.py:151,156`, `getattr(…, "auto")` | `request.output_format` |
| `app._force` | `click_params.py:74` | `request.force` |

Every read today has a **silent default**, which is why D-1 and D-2 went unnoticed: a door that
never deposits does not fail, it gets `False`. As fields with no default at the construction
site, a door that omits one is a type error.

## 5. Not stored, not carried

- **The resolved function.** Nothing outside `_engine/` holds one for execution. That is the
  invariant, and it is grep-asserted (`tasks.md` T11).
- **`config_class`.** §1 step 3.
- **Argument values in history.** The 200-entry ring keeps `args_hash` only, under the secrets
  policy at `executor.py:714-720`. This feature does not change it.
