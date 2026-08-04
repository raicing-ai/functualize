# Events Module (Internal)

The hook and event system now lives in the internal `functualize._events` package. End users interact with events through:

- **`functualize.plugin.EventBus`** — the public event bus for subscribing and emitting
- **`functualize.plugin.HookEvent`** — lifecycle event constants
- **`functualize.plugin.StructuredEvent`** — the event payload type

## Public API

```python
from functualize.plugin import EventBus, HookEvent, StructuredEvent
```

## Hook Events Reference

### Job Execution Events

| Constant | Fires | Signature |
|---|---|---|
| `HookEvent.BEFORE_JOB` | Immediately before job function runs | `hook(rc)` or `hook(rc, *, kwargs=dict)` |
| `HookEvent.AFTER_SUCCESS` | Job completed without exception | `hook(rc)` or `hook(rc, *, result=value)` |
| `HookEvent.AFTER_FAILURE` | Job raised an exception | `hook(rc, exception)` |
| `HookEvent.ON_TEARDOWN` | Always, after success or failure | `hook(rc)` |

### Application Events

| Constant | Fires | Signature |
|---|---|---|
| `HookEvent.APP_READY` | After all boot steps complete | `hook(app)` |
| `HookEvent.JOB_REGISTERED` | When a job is registered (including dynamic) | `hook(metadata: dict)` |
| `HookEvent.INVOKE_START` | Before nested `rc.invoke()` child begins | `hook(rc, child_job_name, kwargs, depth)` |
| `HookEvent.INVOKE_END` | After nested `rc.invoke()` child completes | `hook(rc, child_job_name, depth, result)` |

---

## EventBus Usage

The `EventBus` is the unified event system replacing the old HookRegistry signals API:

```python
from functualize.plugin import EventBus

# Subscribe to events
bus = app.event_bus
bus.subscribe("etl.extract.complete", my_handler)

# Emit events (typically from within jobs via rc.emit())
bus.emit("etl.extract.complete", resource="customers", record_count=1500)
```

## Signature-Adaptive Dispatch

Hook handlers use signature introspection:

- **`BEFORE_JOB`**: If the handler accepts a `kwargs` keyword parameter, it receives a shallow copy of the original call kwargs.
- **`AFTER_SUCCESS`**: If the handler accepts a `result` keyword parameter, it receives the job's return value.

```python
# Both styles work:
def old_style(rc: RunContext) -> None: ...
def new_style(rc: RunContext, *, kwargs: dict) -> None: ...
```

## Internal Location

- `_events/bus.py` — EventBus implementation (trie-based topic router)
- `_events/hooks.py` — HookRegistry (facade over EventBus for backward compat)
- `_events/tracing.py` — PropagationContext
- `_events/perf.py` — PerfTimeline

!!! warning "Internal API"
    Modules under `functualize._events` are implementation details. Import from `functualize.plugin` instead.
