# Hooks

The hooks system provides a way to attach cross-cutting behavior to job execution. You can register callbacks that fire at specific points in a job's lifecycle — globally for all jobs, or scoped to a specific job by name.

## How Jobs and Hooks Relate

Jobs don't use hooks — hooks use jobs. A job is a plain function that the framework discovers and wraps. The `JobRegistry` automatically invokes the hook lifecycle around every job execution. The job author writes zero hook-related code:

```python
# jobs/greet.py — a job knows nothing about hooks
from pydantic import BaseModel, Field
from functualize.job import RunContext

JOB_NAME = "greet"

class GreetConfig(BaseModel):
    name: str = Field(description="Name of the person to greet")

def run(config: GreetConfig, rc: RunContext) -> None:
    """Execute the greet job."""
    rc.log(f"Hello, {config.name}!")
```

When this job runs, the framework wraps it with the full hook lifecycle:

```
1. PRE_EXECUTE hooks fire      ← after config resolution, before call
2. BEFORE_JOB hooks fire       ← framework invokes automatically
3. run(config, rc)             ← your job function executes
4. AFTER_SUCCESS hooks fire    ← if no exception was raised
   OR AFTER_FAILURE hooks fire ← if an exception was raised
5. ON_TEARDOWN hooks fire      ← always, regardless of outcome
```

The job doesn't opt in to hooks. If someone registers a global `BEFORE_JOB` hook, it fires for every job automatically. Job-scoped hooks (`register_for_job`) target a specific job by name, but even then the job code itself is untouched.

### Who Registers Hooks?

Hooks are registered by code external to the job — either a plugin or your app's bootstrap logic:

**From a plugin** (most common for reusable behavior):

```python
from functualize.plugin import HookEvent

class AuditPlugin:
    name = "audit"
    version = "1.0.0"
    description = "Logs every job start for auditing"

    def __call__(self, app):
        app.hook_app.hook_registry.register_global(HookEvent.BEFORE_JOB, self._on_start)

    def _on_start(self, rc):
        rc.log(f"[audit] Job '{rc.name}' starting")
```

**Directly in app bootstrap** (for project-specific concerns):

```python
from functualize.app import FunctualizeApp, JobSources
from functualize.plugin import HookEvent

app = FunctualizeApp(name="my-app", job_sources=JobSources(directories=["jobs"]))

app.hook_app.hook_registry.register_for_job(
    "data_sync", HookEvent.AFTER_FAILURE, send_alert
)
app.hook_app.hook_registry.register_global(HookEvent.ON_TEARDOWN, cleanup_temp_files)
```

## Lifecycle Hook Events

Functualize defines lifecycle events that fire during job execution and application-level events for broader integration points.

### Job Execution Events

These events fire during the job execution pipeline, in this order:

| Event | Constant | When it fires |
|-------|----------|---------------|
| Pre Execute | `HookEvent.PRE_EXECUTE` | After config resolution, before the job function is called |
| Before Job | `HookEvent.BEFORE_JOB` | Immediately before the job function runs |
| After Success | `HookEvent.AFTER_SUCCESS` | When the job completes without raising an exception |
| After Failure | `HookEvent.AFTER_FAILURE` | When the job raises an exception |
| On Teardown | `HookEvent.ON_TEARDOWN` | After either `AFTER_SUCCESS` or `AFTER_FAILURE`, regardless of outcome |

### Application-Level Events

These events fire outside the per-job pipeline:

| Event | Constant | When it fires |
|-------|----------|---------------|
| App Ready | `HookEvent.APP_READY` | After all boot steps complete (plugins loaded, jobs registered) |
| Job Registered | `HookEvent.JOB_REGISTERED` | When a job is registered (including dynamic jobs) |
| Invoke Start | `HookEvent.INVOKE_START` | Before a nested `rc.invoke()` child job begins |
| Invoke End | `HookEvent.INVOKE_END` | After a nested `rc.invoke()` child job completes |
| On Scope Created | `HookEvent.ON_SCOPE_CREATED` | When a WorkflowScope is created |
| TUI Started | `HookEvent.TUI_STARTED` | When the TUI application launches |

### Invocation Order

When an event fires, hooks are invoked in this order:

1. **Global hooks** — in registration order
2. **Job-scoped hooks** — in registration order

This means a global `BEFORE_JOB` hook always runs before a job-scoped `BEFORE_JOB` hook, even if the job-scoped hook was registered first.

## Registration Methods

The hook registry provides two methods for registering hooks:

### `register_global`

Registers a hook that fires for **all jobs** on the given event.

```python
from functualize.plugin import HookEvent

def log_start(rc):
    rc.log("info", "Job is starting")

app.hook_registry.register_global(HookEvent.BEFORE_JOB, log_start)
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event` | `str` | The lifecycle event (use `HookEvent` constants) |
| `hook` | `Callable` | The handler to invoke when the event fires |

### `register_for_job`

Registers a hook scoped to a **specific job** by name.

```python
app.hook_registry.register_for_job("data_sync", HookEvent.AFTER_SUCCESS, notify_complete)
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_name` | `str` | The name of the job this hook applies to |
| `event` | `str` | The lifecycle event (use `HookEvent` constants) |
| `hook` | `Callable` | The handler to invoke when the event fires |

## Handler Callable Signatures

The expected signature of a hook handler depends on the event:

| Event | Signature | Description |
|-------|-----------|-------------|
| `PRE_EXECUTE` | `hook(rc, kwargs) -> HookDecision \| None` | Receives run context and resolved kwargs; returns decision |
| `BEFORE_JOB` | `hook(rc)` or `hook(rc, *, kwargs=...)` | Receives run context; optionally receives original kwargs |
| `AFTER_SUCCESS` | `hook(rc)` or `hook(rc, *, result=...)` | Receives run context; optionally receives return value |
| `AFTER_FAILURE` | `hook(rc, exception)` | Receives run context **and** the raised exception |
| `ON_TEARDOWN` | `hook(rc)` | Receives the run context |
| `APP_READY` | `hook(app)` | Receives the FunctualizeApp instance |
| `JOB_REGISTERED` | `hook(metadata)` | Receives a metadata dict (name, group, config_schema, docstring) |
| `INVOKE_START` | `hook(rc, child_job_name, kwargs, depth)` | Receives parent context + child details |
| `INVOKE_END` | `hook(rc, child_job_name, depth, result)` | Receives parent context + child result |
| `ON_SCOPE_CREATED` | `hook(scope)` | Receives the WorkflowScope instance |
| `TUI_STARTED` | `hook(metadata)` | Receives a metadata dict (app_name, command_name) |

### Signature-Adaptive Dispatch

`BEFORE_JOB` and `AFTER_SUCCESS` hooks use **signature-adaptive dispatch**. The framework introspects your handler's signature at invocation time:

- If your `BEFORE_JOB` handler accepts a `kwargs` keyword parameter, it receives a shallow copy of the original call kwargs.
- If your `AFTER_SUCCESS` handler accepts a `result` keyword parameter, it receives the job's return value.
- If your handler does **not** accept those parameters, it is called without them — no `TypeError`.

This means existing hooks written before these enhancements continue to work unchanged:

```python
# Old-style handler — still works perfectly
def old_before_hook(rc: RunContext) -> None:
    rc.log("Job starting")

# New-style handler — receives kwargs
def new_before_hook(rc: RunContext, *, kwargs: dict) -> None:
    rc.log(f"Job starting with {len(kwargs)} args")

# Both can be registered for the same event:
app.hook_registry.register_global(HookEvent.BEFORE_JOB, old_before_hook)
app.hook_registry.register_global(HookEvent.BEFORE_JOB, new_before_hook)
```

!!! note "AFTER_FAILURE is the exception"

    Only `AFTER_FAILURE` handlers receive a second argument — the exception that caused the job to fail. All other standard lifecycle handlers receive only the `RunContext` (plus optional keyword parameters for `BEFORE_JOB` and `AFTER_SUCCESS`).

## PRE_EXECUTE Hooks

`PRE_EXECUTE` is a special hook that fires **after config resolution** and **before the job function is called**. Unlike other hooks, PRE_EXECUTE hooks return a `HookDecision` that controls execution flow.

### HookDecision

```python
from functualize.plugin import HookEvent
```

| Factory | Effect |
|---------|--------|
| `HookDecision.PROCEED()` | Continue execution unchanged |
| `HookDecision.BLOCK(reason)` | Skip job execution; return failure with reason (1-500 chars) |
| `HookDecision.MODIFY(kwargs)` | Replace call kwargs before invoking the job |

### PRE_EXECUTE Hook Chain

When multiple PRE_EXECUTE hooks are registered, they execute as a chain:

1. Each hook receives `(rc, kwargs_copy)` — a copy of the current kwargs
2. `PROCEED` or `None` → continue to next hook
3. `MODIFY` → update kwargs for subsequent hooks and final execution
4. `BLOCK` → stop immediately, job is not executed
5. If a hook raises an exception → logged at ERROR, treated as PROCEED

```python
from functualize.plugin import HookEvent
from functualize.job import RunContext


def rate_limiter(rc: RunContext, kwargs: dict) -> HookDecision | None:
    """Block execution if rate limit exceeded."""
    if is_rate_limited(rc.job_name):
        return HookDecision.BLOCK("Rate limit exceeded for this job")
    return HookDecision.PROCEED()


def inject_defaults(rc: RunContext, kwargs: dict) -> HookDecision | None:
    """Inject default values into kwargs before execution."""
    if "timeout" not in kwargs:
        kwargs["timeout"] = 30
        return HookDecision.MODIFY(kwargs)
    return None  # None is treated as PROCEED


app.hook_app.hook_registry.register_global(HookEvent.PRE_EXECUTE, rate_limiter)
app.hook_app.hook_registry.register_global(HookEvent.PRE_EXECUTE, inject_defaults)
```

## Application-Level Hook Examples

### APP_READY

Fires once after the full boot sequence completes:

```python
def on_ready(app):
    """Run one-time initialization after all plugins and jobs are loaded."""
    print(f"App '{app.name}' ready with {len(app.job_registry)} jobs")

app.hook_app.hook_registry.register_global(HookEvent.APP_READY, on_ready)
```

### JOB_REGISTERED

Fires each time a job is registered (including dynamic jobs):

```python
def sync_to_orchestrator(metadata: dict) -> None:
    """Sync job definition to external orchestrator."""
    # metadata keys: name, group, config_schema, docstring
    post_to_orchestrator(metadata["name"], metadata["group"])

app.hook_app.hook_registry.register_global(HookEvent.JOB_REGISTERED, sync_to_orchestrator)
```

### INVOKE_START / INVOKE_END

Fire around nested `rc.invoke()` calls:

```python
def trace_invoke_start(rc, child_job_name, kwargs, depth):
    rc.log(f"→ Invoking '{child_job_name}' at depth {depth}")

def trace_invoke_end(rc, child_job_name, depth, result):
    rc.log(f"← '{child_job_name}' completed: {result.status.value}")

app.hook_app.hook_registry.register_global(HookEvent.INVOKE_START, trace_invoke_start)
app.hook_app.hook_registry.register_global(HookEvent.INVOKE_END, trace_invoke_end)
```

### ON_SCOPE_CREATED

Fires when a WorkflowScope is created — useful for replacing the state store:

```python
from my_plugin.sqlite_store import SQLiteStateStore

def inject_persistent_store(scope):
    """Replace the default in-memory store with SQLite."""
    scope.replace_state_store(SQLiteStateStore(db_path="state.db"))

app.hook_app.hook_registry.register_global(HookEvent.ON_SCOPE_CREATED, inject_persistent_store)
```

### TUI_STARTED

Fires when the TUI launches:

```python
def on_tui(metadata: dict) -> None:
    print(f"TUI launched for '{metadata['app_name']}'")

app.hook_app.hook_registry.register_global(HookEvent.TUI_STARTED, on_tui)
```

## Error Isolation

If a hook raises an exception during execution, the error is **logged** and the remaining hooks **continue executing**. A misbehaving hook will never prevent other hooks from running or crash the job lifecycle.

!!! info "Error isolation guarantee"

    Hook errors are logged at the `ERROR` level with the hook function name, the event, and the job name. The exception does not propagate — subsequent hooks in the invocation chain still fire normally.

    For `JOB_REGISTERED` hooks, errors are logged at `WARNING` level and do not prevent job registration from completing.

## Complete Example

The following example demonstrates registering both a global hook and a job-scoped hook, covering two distinct events (`BEFORE_JOB` and `AFTER_FAILURE`):

```python
from functualize.plugin import HookEvent, EventBus
from functualize.job import RunContext


# --- Define hook handlers ---

def audit_start(rc: RunContext, *, kwargs: dict):  # (1)!
    """Global hook: log every job start with the original kwargs."""
    rc.log("info", f"[AUDIT] Job started with {len(kwargs)} args")


def handle_data_sync_failure(rc: RunContext, exception: Exception):  # (2)!
    """Job-scoped hook: handle failures specific to the data_sync job."""
    rc.log("error", f"data_sync failed: {exception}")
    # Could send an alert, write to a dead-letter queue, etc.


def capture_result(rc: RunContext, *, result):  # (3)!
    """Global hook: capture job return values for monitoring."""
    if result is not None:
        rc.log("info", f"[AUDIT] Job returned: {result}")


# --- Register hooks ---

# Access the hook registry from the app
# (In practice this is done inside a plugin __call__ or app bootstrap)

# Global hook fires BEFORE_JOB for every job
app.hook_app.hook_registry.register_global(HookEvent.BEFORE_JOB, audit_start)  # (4)!

# Global hook fires AFTER_SUCCESS for every job
app.hook_registry.register_global(HookEvent.AFTER_SUCCESS, capture_result)

# Job-scoped hook fires AFTER_FAILURE only for the "data_sync" job
app.hook_registry.register_for_job(  # (5)!
    "data_sync",
    HookEvent.AFTER_FAILURE,
    handle_data_sync_failure,
)
```

1. `BEFORE_JOB` handler with signature-adaptive `kwargs` — receives original call kwargs.
2. Job-scoped `AFTER_FAILURE` handler — receives `RunContext` and the `Exception`.
3. `AFTER_SUCCESS` handler with signature-adaptive `result` — receives the job's return value.
4. `register_global` makes this hook fire for all jobs.
5. `register_for_job` scopes this hook to the `"data_sync"` job only.

### What happens at runtime

When the `data_sync` job executes:

1. `audit_start` fires (global `BEFORE_JOB`) — receives kwargs
2. The job function runs
3. If the job raises an exception → `handle_data_sync_failure` fires (job-scoped `AFTER_FAILURE`)
4. If the job succeeds → `capture_result` fires (global `AFTER_SUCCESS`) — receives return value
5. `ON_TEARDOWN` hooks fire (none registered in this example)

When any other job executes:

1. `audit_start` fires (global `BEFORE_JOB`)
2. The job function runs
3. Only global `AFTER_SUCCESS` / `AFTER_FAILURE` / `ON_TEARDOWN` hooks would fire
