# Job Module — RunContext

::: functualize.job
    options:
      show_root_heading: true
      members_order: source

---

## RunContext API Reference

`functualize.job.RunContext` is a thin facade (a 32-line re-export module) over
the ~780-LOC capability class in `functualize._engine.capabilities.runcontext`,
which delegates work to per-capability classes (`Log`, `Invoke`, `Perf`,
`WorkflowTracker`, ...). It provides configuration access, logging, metadata tracking, phase tracking, job invocation, event emission, and prompting.

**Module location:** `src/functualize/job/context.py`

```python
from functualize.job import (
    RunContext, Log, Invoke, Prompt, Perf, State, Sources, JobContext, JobConfigView,
)
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

#### `rc.events.set_run_status(status, message="")`

Transition the execution status. Terminal states cannot be transitioned from.

```python
from functualize.types import RunStatus

rc.events.set_run_status(RunStatus.SUCCESS, "All records processed")
```

---

### Job Phases

#### `rc.events.track_phase(phase_name, message, status=None)`

Create or update a named job phase. Delegates to the `WorkflowTracker` capability class.

```python
from functualize.types import RunStatus

rc.events.track_phase("extract", "Fetching from API")
rc.events.track_phase("extract", "Got 1000 records", RunStatus.SUCCESS)
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

The result is **unchecked**: a failed child is a value, and the parent carries
on unless it looks. To stop the parent when the child did not do its work,
check the result where you bind it:

```python
result = rc.invoke("build").raise_for_status()
```

`raise_for_status()` returns the same result when its status is `SUCCESS`,
`SKIPPED` or `BLOCKED` — the statuses `invoke.parallel` does not raise for —
and otherwise raises `JobFailedError` (from `functualize.types`). The error
carries the child's `job_name`, `status` and `exception`, and the whole
`result`, so `err.result.metadata` is there too. It is raised *from* the
child's exception, so the child's frames stay attached. Uncaught, it fails the
parent: the parent's status is `FAILURE`, `func` exits 1, and stderr reads
`Error: JobFailedError: job 'build' did not succeed (Failure): RuntimeError: …`
(`--log-level DEBUG` prints the full chained traceback instead). Every
`JobResult` has the method, including the one `app.execute(...)` returns and
each item of `invoke.parallel(..., raise_on_failure=False)`.

**Capturing a child's output.** By default a child's `out.emit()` and
`out.write()` reach the caller's stdout, one document per call, and only its
return value comes back as data. `capture=True` takes them back instead:

```python
report = rc.invoke("report", capture=True)
rows = report.metadata["emitted"]    # the values passed to out.emit()
chunks = report.metadata["writes"]   # the payloads passed to out.write()
```

- Both keys are tuples, in call order, and always present under capture —
  empty when the child emitted nothing or declares no `Stdout`. Without
  capture neither key exists.
- Values are recorded **as passed**, `None` included. Nothing is serialized,
  re-parsed or redacted, so an object no format could render comes back as
  itself.
- Captured output is recorded **instead of** written: none of it reaches
  stdout, and the parent decides what to emit. This holds at every
  `--emit-format`, `none` included — the format governs rendering to the
  stream, and capture bypasses the stream.
- Capture is not transitive. A grandchild the child invokes without
  `capture=True` writes to stdout as usual; one invoked with it is captured
  into the child's result. Dependency runs and workflow steps the child
  triggers are never captured.
- A captured child that times out returns `TIMEOUT` with what it emitted up to
  the deadline. Its thread cannot be interrupted and may keep running; anything
  it emits after the deadline is discarded, not written.
- Captured values are held by reference in the result for as long as the
  parent keeps it. There is no cap.
- `capture` is a control input, like `timeout`: it never reaches the child as
  an argument. `invoke.parallel` does not accept it.

The two compose: `rc.invoke("report", capture=True).raise_for_status()` raises
for a failed `report`, and `err.result.metadata["emitted"]` still holds what it
emitted before it failed.

#### `rc.invoke_parallel(jobs)`

Invoke multiple jobs concurrently through `Invoke.parallel()`.

```python
jobs = [
    ("process-shard", {"shard_id": 0}),
    ("process-shard", {"shard_id": 1}),
    ("process-shard", {"shard_id": 2}),
]
results = rc.invoke_parallel(jobs)
```

The default raises `RuntimeError` after collecting the batch if a child fails.
The error names every failed input position, job, and status, and chains the first
failed child's exception when one exists. A parent that ignores the call's return
value therefore still fails. When all children finish without a failure, it
returns `list[JobResult]` in input order.

#### `invoke.parallel`

Signature: `invoke.parallel(jobs, *, timeout=None, raise_on_failure=True)`.
This is the batch API on an injected `Invoke`. Set `raise_on_failure=False` when
the parent needs to inspect every result and decide how to handle failures:

```python
from functualize.job import Invoke

def fan_out(invoke: Invoke):
    jobs = [("process-shard", {"shard_id": i}) for i in range(3)]
    results = invoke.parallel(jobs, raise_on_failure=False)
    for result in results:
        print(f"{result.job_name}: {result.status.value}")
    return results
```

The returned list always follows input order, even when children finish in a
different order. Empty input returns an empty list; more than 32 jobs raises
`ValueError`. `SUCCESS`, `SKIPPED`, and `BLOCKED` do not trigger the default
raise. Other terminal statuses, including `FAILURE` and `TIMEOUT`, do.

`timeout=None` gives the batch 300 seconds; a nonpositive timeout waits without
a deadline. At the deadline, unfinished jobs receive `TIMEOUT` results. The
default raises for those results; the opt-out returns them. Running threads
cannot be interrupted and may finish after the batch call returns.

`raise_on_failure` belongs to `Invoke.parallel` only. `rc.invoke_parallel(jobs)`
uses the safe default and does not accept the option; `Invoke.__call__` invokes
one child and returns its `JobResult` unchecked. Check that one with
`.raise_for_status()`, which raises for exactly the statuses this method's
default raises for.

---

### Event Emission

#### `rc.events.emit(event_name, resource="", **payload)`

Emit a custom structured event. Delegates directly to `EventBus.emit()`.

```python
rc.events.emit("etl.extract.complete", resource="customers", record_count=1500)
```

---

### Prompting

#### `rc.prompts.ask(request)`

Present a structured prompt to the user via the active `PromptCollector`.

```python
from functualize.plugin import PromptRequest

response = rc.prompts.ask(PromptRequest(
    question="Select environment",
    choices=[...],
))
```

#### Convenience Methods

- `rc.prompts.confirm(question, *, destructive=False, default=None)` — Yes/no confirmation
- `rc.prompts.choice(question, choices, *, default=None)` — Single selection
- `rc.prompts.text(question, *, default=None, secret=False)` — Text input

---

### Performance Instrumentation

#### `rc.events.perf_mark(name)` / `rc.events.perf_mark_start(name)` / `rc.events.perf_mark_end(name)`

Record performance marks. Delegates to the `Perf` capability class.

---

### DI Access

#### `rc[SomeType]` / `SomeType in rc`

Access dependency-injected services via subscript notation.

```python
db = rc[DatabaseConnection]
```

---

### Shell Capability — Errors and Responders

The `Shell` capability (`sh: Shell`) and its `ShellResult`/`Responder` types are covered in the [Shell Capability guide](../guides/shell.md). Two of its vocabulary types are documented here.

#### `ShellError`

Raised when a command exits non-zero under `check=True` — also on timeout, and when a `FailingResponder` sentinel appears in the live output.

```python
class ShellError(Exception):
    def __init__(self, result: ShellResult) -> None: ...
```

| Attribute | Type | Description |
|---|---|---|
| `result` | `ShellResult` | The full result of the failed command, so callers can inspect `stdout`/`stderr`/`returncode`. |

```python
from functualize.job import Shell, ShellError

def deploy(sh: Shell) -> None:
    try:
        sh(["docker", "build", "-t", "app", "."])
    except ShellError as e:
        print(e.result.stderr)
```

#### `FailingResponder`

A `Responder` that also aborts on a failure sentinel. Responds like `Responder` — writing `response` to the child's stdin whenever `pattern` matches new output — but if `sentinel` appears the command is killed and a `ShellError` is raised. This is how a `sudo` password responder aborts on `Sorry, try again` instead of answering the re-prompt forever.

```python
from functualize.job import FailingResponder

FailingResponder(
    pattern=r"\[sudo\] password.*:",
    response="s3cr3t\n",
    sentinel="Sorry, try again",
)
```

| Attribute | Type | Description |
|---|---|---|
| `pattern` | `str \| re.Pattern[str]` | Regex whose match in live output triggers `response` (inherited from `Responder`). |
| `response` | `str` | Text written to the child's stdin on each match (inherited from `Responder`). |
| `sentinel` | `str \| re.Pattern[str]` | Regex whose appearance aborts the command with `ShellError`. |

Subclasses `Responder`, so it is accepted anywhere a `watchers=` sequence is.

---

### Freshness Capability

#### `FreshnessVerdict`

The verdict `functualize.job.Freshness` exposes to a job whose `@job(cache=Fingerprint(..., decides=True))` opted in to seeing its own freshness decision, instead of the engine silently returning before the body ran.

```python
@dataclass(frozen=True)
class FreshnessVerdict:
    state: GuardState
    key: str
    recorded_value: Any | None
    declared_sources: tuple[str, ...]
    declared_generates: tuple[str, ...]
    source_map: Mapping[str, Mapping[str, Any]]
```

| Attribute | Type | Description |
|---|---|---|
| `state` | `GuardState` | The pipeline outcome — `SKIP_FRESH` when the job's declared inputs are current, `RUN` otherwise. |
| `key` | `str` | The fingerprint key the decision was computed under. |
| `recorded_value` | `Any \| None` | What the previous run recorded, when the pre-flight read a record and the verdict was a skip. |
| `declared_sources` | `tuple[str, ...]` | The input patterns as the job's own `Fingerprint` declared them. |
| `declared_generates` | `tuple[str, ...]` | The output patterns as the job's own `Fingerprint` declared them. |
| `source_map` | `Mapping[str, Mapping[str, Any]]` | `{path: {mtime, size, sha256}}` for every match of the declared inputs. |
| `is_fresh` (property) | `bool` | `True` only when `state is GuardState.SKIP_FRESH`. Deliberately does **not** fold in a satisfied `status` guard — "already done" is a different claim from "declared inputs are current". |

```python
from functualize.job import Freshness
from functualize.job.decorators import job, Fingerprint

@job(cache=Fingerprint(sources=["src/**/*.py"], decides=True))
def build(fresh: Freshness) -> str:
    verdict = fresh.verdict()
    if verdict is not None and verdict.is_fresh:
        return "artifact already current"
    return rebuild()
```

`decides=True` is what makes the branch above reachable — without it the engine skips the job *for* you and returns before the body runs, so `is_fresh` is the one value that branch could never see.
