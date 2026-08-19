# Job Module — RunContext

::: functualize.job
    options:
      show_root_heading: true
      members_order: source

---

## RunContext API Reference

The `RunContext` is a thin facade (~870 LOC) that delegates to capability classes. It provides configuration access, logging, metadata tracking, phase tracking, job invocation, event emission, and prompting.

**Module location:** `src/functualize/job/context.py`

```python
from functualize.job import RunContext, Log, Invoke, Prompt, Perf, State, JobContext, JobConfigView
```

### Core Properties

| Property | Type | Description |
|---|---|---|
| `name` | `str` | The job name for this execution. |
| `metadata` | `dict[str, Any]` | Execution metadata (run_type, run_status, start_time, end_time, duration). |
| `result_metadata` | `dict[str, Any]` | Mutable metadata dict carried to `JobResult` (64-key max). |
| `config` | `JobConfigView` | The resolved configuration view for this job. |
| `job_config` | `Any` | The Pydantic config model instance (settable). |
| `phases` | `list[JobPhase]` | All tracked job phases in this execution. |
| `cwd` | `Path` | The working directory for this execution. |
| `job_directory` | `Path \| None` | The directory containing the job module. |
| `run_status` | `RunStatus` | Current execution status. |
| `run_duration` | `float` | Elapsed time in seconds since execution started. |

---

### Logging

#### `rc.log(message, level="info")`

Emit a log message through the job's own [`Log`](../guides/run-context.md#logging)
capability when the job declares one, so both routes share a sink; otherwise it
writes to the job's `functualize.job.<name>` logger, which is where `Log` would
have written too.

`level` must be one of `debug`, `info`, `warning`, `error`, `critical` — anything
else raises `ValueError`.

```python
from functualize.job import Log, RunContext

def my_job(rc: RunContext) -> None:
    rc.log("Starting processing")                # info (default)
    rc.log("Connecting to DB", level="debug")
    rc.log("Retrying request", level="warning")


def either_way(rc: RunContext, log: Log) -> None:
    log("same sink")                             # the injected capability
    rc.log("same sink")                          # routed to that same instance
```

---

### Status Tracking

#### `rc.set_run_status(status, message="")`

Transition the execution status. Terminal states cannot be transitioned from.

```python
from functualize.types import RunStatus

rc.set_run_status(RunStatus.SUCCESS, "All records processed")
```

---

### Job Phases

#### `rc.track_phase(phase_name, message, status=None)`

Create or update a named job phase. Delegates to the `WorkflowTracker` capability class.

```python
from functualize.types import RunStatus

rc.track_phase("extract", "Fetching from API")
rc.track_phase("extract", "Got 1000 records", RunStatus.SUCCESS)
```

---

### Job Invocation

#### `rc.invoke(job_name, *, timeout=None, **kwargs)`

Invoke a sibling job as a child execution. Delegates to the `Invoke` capability class.

```python
result = rc.invoke("validate-data", source="api")
result = rc.invoke("slow-job", timeout=30.0, batch_size=100)
```

**Returns:** `JobResult` with status, duration, return_value, and exception.

#### `rc.invoke_parallel(jobs)`

Invoke multiple jobs concurrently. Delegates to `Invoke.parallel()`.

```python
jobs = [
    ("process-shard", {"shard_id": 0}),
    ("process-shard", {"shard_id": 1}),
    ("process-shard", {"shard_id": 2}),
]
results = rc.invoke_parallel(jobs)
```

**Returns:** `list[JobResult]` in the same positional order as the input.

---

### Event Emission

#### `rc.emit(event_name, resource="", **payload)`

Emit a custom structured event. Delegates directly to `EventBus.emit()`.

```python
rc.emit("etl.extract.complete", resource="customers", record_count=1500)
```

---

### Prompting

#### `rc.prompt(request)`

Present a structured prompt to the user via the active `PromptCollector`.

```python
from functualize.plugin import PromptRequest

response = rc.prompt(PromptRequest(
    question="Select environment",
    choices=[...],
))
```

#### Convenience Methods

- `rc.prompt_confirm(question, *, destructive=False, default=None)` — Yes/no confirmation
- `rc.prompt_choice(question, choices, *, default=None)` — Single selection
- `rc.prompt_text(question, *, default=None, secret=False)` — Text input

---

### Performance Instrumentation

#### `rc.perf_mark(name)` / `rc.perf_mark_start(name)` / `rc.perf_mark_end(name)`

Record performance marks. Delegates to the `Perf` capability class.

---

### DI Access

#### `rc[SomeType]` / `SomeType in rc`

Access dependency-injected services via subscript notation.

```python
db = rc[DatabaseConnection]
```
