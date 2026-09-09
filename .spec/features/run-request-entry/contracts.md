# Contracts — run-request-entry

External interfaces only. Internal shapes are in `schema.md`.

---

## 1. `functualize.types` — the request

New module `src/functualize/_types/run_request.py`, re-exported from `functualize.types`.
Stdlib-only: no import from `_engine`, `_app`, `app`, `_config` or any third party.

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Surface = Literal[
    "func.job", "func.group", "func.single-file", "func.bare", "func.builtin",
    "app.cli", "app.execute",
    "tui.inline", "tui.shell",
    "mcp.tool", "mcp.run-job", "mcp.async",
    "http", "lambda",
    "invoke", "invoke.parallel",
    "event.job-submit",
    "engine.step", "engine.dependency",
]


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Everything one run needs, frozen at the door that built it.

    The job is named, never resolved: `engine.run` performs the lookup, as it
    already does for workflow steps and dependencies. Nothing outside
    `_engine/` holds a job function in order to execute it.
    """

    job_name: str
    surface: Surface
    kwargs: Mapping[str, Any] = field(default_factory=dict)

    # Delivery inputs — were deposits on the app object (spec §1.2)
    prompt_gates: bool = False
    output_format: str = "auto"
    force: bool = False

    # Execution inputs
    group_option_values: Mapping[str, Any] | None = None
    parent_scope: Any | None = None
    workflow_scope_id: str | None = None
    invoke_depth: int = 0
    run_dependencies: bool = True
    force_fresh: bool = False
    cwd: Path | None = None
    job_directory: Path | None = None

    def replace(self, **changes: Any) -> RunRequest: ...
```

`surface` has no default. A door must name itself.

## 2. `functualize._engine.executor` — the entry

```python
class JobExecutionEngine:
    def run(self, request: RunRequest) -> JobResult:
        """Resolve, materialize, and execute the job named by `request`."""
        ...
```

### Removed

- `JobExecutionEngine.execute(job_name, function, *, kwargs, …)` — **deleted**, no shim.
- `function` and `config_class` are no longer accepted by any engine entry point. The engine
  derives `config_class` from the registered job, as `execute()` already re-derived it.

## 3. `functualize.app` — the facade

```python
class FunctualizeApp:
    def execute(self, request: RunRequest) -> JobResult:
        """The single surface-facing entry. Creates the WorkflowScope."""
        ...
```

### Changed

`FunctualizeApp.execute` previously took `(job_name, *, scope_id=None,
group_option_values=None, **kwargs)`. It now takes one `RunRequest`. Every caller — including
`app/adapters/click_params.py` and `app/adapters/lazy_command.py`, which bypass the facade
today — constructs a request.

A convenience constructor keeps the common programmatic case short:

```python
def request_for(
    job_name: str, *, surface: Surface = "app.execute", **kwargs: Any
) -> RunRequest: ...
```

## 4. `functualize.app.utils` — the `_cli` corridor

`_cli` may import from public folders only. Added re-exports:

```python
from functualize.types import RunRequest, Surface   # noqa: F401
```

No other name is added. Per the orphan-scan rule, a re-export with no `_cli` consumer at
close is removed.

## 5. Surfaces — what each door now builds

Every row is a door that today assembles arguments or reads a deposit. After this feature each
builds a `RunRequest` and calls the facade.

| Door | Surface value | Was |
|---|---|---|
| `func <job>` | `func.job` | `_handle_job` → click callback → `engine.execute(name, function, …)` |
| `func <group> <job>` | `func.group` | `_dispatch_group`'s own materialization path |
| `func <file>.py` | `func.single-file` | `_handle_single_file` |
| bare `func` | `func.bare` | `_handle_bare` |
| `func builtin parallel` | `func.builtin` | `app.execute_parallel` |
| app's own CLI | `app.cli` | `_build_job_command` → eager or lazy callback |
| `app.execute(...)` | `app.execute` | resolved the function itself (`core.py:620-621`) |
| inline TUI | `tui.inline` | `app._func_app.execute` |
| full-screen TUI | `tui.shell` | `app.execute` |
| MCP per-job tool | `mcp.tool` | `_server.py:278` |
| MCP `run_job` | `mcp.run-job` | `_tools.py:287` |
| MCP async worker | `mcp.async` | `_tools.py:450` |
| HTTP plugin | `http` | `functualize_http/__init__.py` |
| Lambda plugin | `lambda` | `functualize_lambda/__init__.py` |
| `rc.invoke` | `invoke` | `invoke.py:401` |
| `rc.invoke_parallel` | `invoke.parallel` | `invoke.py:598` |
| `interactivity.job.submit` | `event.job-submit` | `app.execution_engine.execute` **direct** (D-13) |
| workflow step | `engine.step` | `executor.py:1216` |
| dependency | `engine.dependency` | `executor.py:1795` |
| `guarded_execute` | *inherits its caller's* | `app/_workflow_control.py:176` |

`guarded_execute` forwards the request it is given rather than minting a surface, so a
workflow resumed from the CLI still reports `func.builtin` and one resumed over MCP reports
`mcp.tool`. It is a funnel, not a door.

## 6. Click surface

### 6.1 New on a project's own entry point

```
--prompt-gates / --no-prompt-gates   Prompt for gate input interactively
--output [auto|json|ndjson|raw]      Output format
```

Registered by the app-side root callback (`app/adapters/cli.py`), matching `func`'s spelling
exactly. Negative spelling comes from `negative_flag_for`, unchanged.

### 6.2 Unchanged

`--force`, `--scope-id`'s successors (`--wf-*`), group flags, and every job parameter keep
their current spelling. This feature moves where the value travels, not what the user types.

### 6.3 Environment

`FUNCTUALIZE_CLI_OUTPUT` is documented in `builtins.py` help text and read by nothing.
It is **read** — resolving to `RunRequest.output_format` beneath an explicit `--output` — or
removed from the help text. Not left inert.

## 7. Plugin-facing changes

Both trigger plugins and the MCP plugin construct requests instead of forwarding kwargs.

```python
# functualize_http
result = app.execute(RunRequest(job_name=name, surface="http", kwargs=body,
                                group_option_values=group_opts, force=force))
```

**Breaking for out-of-tree plugins** that call `engine.execute` or construct a
`JobExecutionEngine` directly. The `AdapterPlugin` protocol only ever promised `__call__(app)`,
so facade-only entry is already the documented contract — but the break is silent and is not
enumerable from this repo. It needs a plugin-guide release note.

## 8. Error contract

| Condition | Raised / returned |
|---|---|
| `job_name` not registered | `JobNotFoundError`, unchanged |
| `surface` not in the closed set | `ValueError` at construction |
| a gate blocks | `JobResult(status=BLOCKED)` with a scope id — **on every door**, including `event.job-submit` |
| `force=True` on a fresh job | the job runs; `SKIP_FRESH` and `SKIP_SATISFIED` are overridden, a failing `Precondition` and a gate are not (`executor.py:1000-1025`, unchanged) |
