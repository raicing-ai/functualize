# Execution Flow

## Job Execution Lifecycle

All invocation modes converge to a single path: `JobExecutionEngine.execute()`.

```
Trigger (any of):
  CLI command → CliAdapter → app.execute()
  rc.invoke() → engine.execute()
  func standalone → app.execute()
  HTTP POST → HttpAdapter → app.execute()
  Lambda event → LambdaAdapter → app.execute()
       │
       ▼
  JobExecutionEngine._execute_lifecycle  — twenty steps
       │
       ▼
  _execute_with_lifecycle  — hooks and middleware around the body
```

**The twenty steps, and the constraint that fixes each one's position, are in
[`contributor/reference/execution-lifecycle.md`](../reference/execution-lifecycle.md).**

A twelve-step summary used to live here. It omitted `Deps`, the pre-flight,
`FromJob`, `Sources` and the fingerprint record — five of the things a reader
comes to this page to ask about — so it was not a simplification but a stale
list, and it is replaced by the link rather than re-summarized.

What follows below is the part that page does not cover: what happens *inside*
step 17, once the body is committed to running.

## DI Resolution

The engine resolves function parameters via a `ResolutionPlan`:

```python
def deploy(rc: RunContext, log: Log, config: DeployConfig):
    ...

# ResolutionPlan for this function:
# - rc → source: "runcontext" (construct RunContext facade)
# - log → source: "di" (resolve Log from DIRegistry, per-invocation)
# - config → source: "config" (resolve from ResolutionChain + Pydantic)
```

Resolution plans are computed once at boot (during discovery phase) and cached by `id(function)`. Subsequent invocations skip `inspect.signature()` entirely.

**Resolution priority**: DI > RunContext > Config > Default value > Skip (let caller supply)

## RunContext as Facade

RunContext is a thin facade (~500 LOC). Every method is a one-liner delegating to a capability:

```python
class RunContext:
    def invoke(self, job_name, **kwargs):
        return self._capabilities[Invoke](job_name, **kwargs)

    def log(self, message, *, level="info"):
        return self._capabilities[Log](message, level=level)

    def emit(self, event_name, **payload):
        return self._event_bus.emit(event_name, **payload)
```

The actual logic lives in capability classes under `_engine/capabilities/`.

## Middleware Chain

Middleware uses a yield-based generator pattern:

```python
def timing_middleware(rc: RunContext):
    start = time.time()
    yield                          # ← pre-phase ends, job runs
    duration = time.time() - start # ← post-phase begins
    rc.log(f"Took {duration:.2f}s")
```

- **Priority**: Lower number = outermost (executes first pre, last post)
- **Exception propagation**: If the job raises, each generator receives the exception via `.throw()` in reverse order
- **Zero-cost bypass**: When no middleware is registered, the job function is called directly

## Three-Layer Caching

```
Layer 1: Provider Persistence (disk)
  CachedDirectoryScanProvider → .functualize/cache.json
  Invalidation: mtime → sha256 → first-level dep hash

Layer 2: Kernel Facade Memo (in-memory)
  app.get_jobs() memoized
  Invalidation: explicit (app.add_job_provider() clears it)

Layer 3: Engine Resolution Plan (in-memory)
  ResolutionPlan cached by id(function)
  Invalidation: never (function signatures are immutable in-process)
```

Static wiring (`JobSources(functions=[...])`) bypasses Layers 1 and 2 entirely.

## Hook Events (Lifecycle)

| Event | When | Can modify? |
|-------|------|-------------|
| `JOB_REGISTERED` | After discovery adds a job | No |
| `APP_READY` | Boot complete, before freeze | Last chance for DI registration |
| `REGISTRY_FROZEN` | After DI freeze | No |
| `PRE_EXECUTE` | After config resolved, before job runs | Yes — can BLOCK or MODIFY kwargs |
| `BEFORE_JOB` | Just before function call | No (observe only) |
| `AFTER_SUCCESS` | Job returned without exception | No (receives result value) |
| `AFTER_FAILURE` | Job raised exception | No (receives exception) |
| `ON_TEARDOWN` | Always, after success or failure | No |
| `INVOKE_START` | Before rc.invoke() child execution | No |
| `INVOKE_END` | After rc.invoke() child completes | No |
| `ON_SCOPE_CREATED` | WorkflowScope created | No |
| `TUI_STARTED` | TUI app launches | No |
