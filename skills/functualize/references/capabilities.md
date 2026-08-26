# Capabilities

Capabilities are injected by parameter type. Declare one in the signature and it
arrives; never construct one, never pass one by hand.

```python
from functualize.job import RunContext, Log, Shell, Stdout

def deploy(config: DeployConfig, rc: RunContext, log: Log, sh: Shell, out: Stdout) -> None:
    ...
```

Order is free — resolution is by type, not position. The conventional shape is
config first, then `rc`, then capabilities.

## The set

All are exported from `functualize.job`.

| Type | For | Key surface |
| --- | --- | --- |
| `RunContext` | The run itself | `rc.log(...)`, run metadata |
| `Log` | Structured logging | callable: `log("msg")`; also `.info` `.warning` `.error` `.debug` |
| `Stdout` | Program output | `.emit(value)`, `.write(data)` |
| `Shell` | Subprocesses | callable; `.cd(path)`, `.prefix(cmd)`, `.defer(cmd)`, `.run_deferred()`, `.sudo(...)` |
| `Invoke` | Calling other jobs | callable: `invoke("other-job", ...)`; `.parallel(...)`, `.schema(name)` |
| `Prompt` | Asking the user | `.confirm()`, `.choice()`, `.text()`, `.ask(request)` |
| `State` | Persistence across runs | `.get(key, default)`, `.set(key, value)`, `.delete(key)`, `.keys(prefix)` |
| `Perf` | Timing | `.mark(name)`, `.mark_start(name)`, `.mark_end(name)`, `.phases()` |
| `Live` | Live-updating display | `.suppress(name)`, handles with `.update()`, `.push()`, `.remove()` |
| `TTY` | Direct terminal control | `.run(app)`, `.ctx()` |
| `JobContext` | Metadata about this invocation | `.name`, `.trace_id`, `.deadline`, `.cwd`, `.job_directory`, `.invoke_depth`, `.scope_id`, `.metadata` |
| `JobConfigView` | Raw resolved config | key access with source tracking |

Confirm against the installed version rather than this table:

```python
import functualize.job as j; print(j.__all__)
```

## Log

`Log` is callable, which is the idiomatic form:

```python
log("deploying")            # info level
log("disk filling", "warning")
log.error("failed")
```

`rc.log(...)` routes through the job's own `Log`, so the two agree.

## Stdout — the output channel

Returning a value does not print it. See the main skill's contract 2.3.

```python
out.emit({"status": "ok"})   # serialized per --output: json | ndjson | raw | none
out.write("raw text")        # verbatim, no serialization, no newline
```

`emit(None)` writes nothing regardless of format, and `--output=none` suppresses
everything. `emit([a, b, c])` is one JSON array under `json` and one line per
item under `ndjson`; to stream rows explicitly, loop and emit each.

`Stdout` redacts known secret values from what it serializes. "Known" means
values that are genuinely `Secret` instances — see
[config-and-secrets.md](config-and-secrets.md), because a field marked secret by
declaration alone does not qualify.

## Shell

Callable for the common case, with context managers for scoping:

```python
sh("ls -la")
with sh.cd("/tmp"):
    sh("pwd")
with sh.prefix("docker exec web"):
    sh("ps aux")
```

`sh.defer(cmd)` queues cleanup; `sh.run_deferred()` runs it. Command output is
redacted against the job's secret values.

## Invoke

```python
result = invoke("other-job", some_field=1)
results = invoke.parallel([...])
descriptor = invoke.schema("other-job")   # JobDescriptor, no execution
```

This is the path where a job's **return value** matters — the thing `Stdout`
does not print. `invoke.schema()` is the programmatic mirror of
`func builtin info`.

## State

Persists across runs through the configured state backend.

```python
state.set("last_run", "2026-08-27")
state.get("last_run", default=None)
state.keys(prefix="cache:")
```

## Choosing

One capability per concern. If a job needs the terminal, it wants `TTY` or
`Live`, not `Stdout`. If it needs another job's result, it wants `Invoke`, not a
direct import — a direct call skips config resolution, hooks, and the event bus.
