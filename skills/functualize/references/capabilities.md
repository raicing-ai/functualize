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
| `State` | Scratch space for **this invocation** | `.get(key, default)`, `.set(key, value)`, `.delete(key)`, `.keys(prefix)` |
| `Perf` | Timing | `.mark(name)`, `.mark_start(name)`, `.mark_end(name)`, `.phases()` |
| `Live` | Live-updating display | `.add(construct)` / `.panel(construct)` → a handle with `.update()`, `.push()`, `.remove()`; `.suppress(name)` |
| `TTY` | Direct terminal control | `.run(app)`, `.ctx()` |
| `Sources` | The files this job's own `Fingerprint(sources=...)` resolved to | mapping of project-relative path → `{mtime, size, sha256}`: `.keys()`, `.items()`, `.get(path)`, `in`, `len()`; plus `.declared`, `.generates` |
| `JobContext` | Metadata about this invocation | `.name`, `.trace_id`, `.deadline`, `.cwd`, `.job_directory`, `.invoke_depth`, `.scope_id`, `.metadata` |
| `JobConfigView` | Raw resolved config | key access with source tracking |

Confirm against the installed version rather than this table:

```python
import functualize.job as j; print(j.__all__)
```

## Not capabilities: `Exec`, `Retry`, `Fingerprint`, `Deps`

These are exported from `functualize.job` alongside the capabilities and read
like more of them, so the mistake is to look for `Retry` in the signature, not
find it, and conclude functualize cannot retry.

**They are job *declaration* options, passed to `@job`, not injected
parameters.** The keyword is not always the type's name — `Fingerprint` goes to
`cache=`, which is the one that costs turns to guess:

| Type | `@job` keyword |
| --- | --- |
| `Deps` | `deps=` |
| `Fingerprint` | `cache=` |
| `Guards` | `guards=` |
| `Exec` (holds `Retry`) | `exec=` |

Retry in particular is real and implemented — reach for it rather than
hand-rolling a loop:

```python
from functualize.job import Exec, Retry, job

@job(exec=Exec(retry=Retry(attempts=3, backoff="exponential")))
def flaky() -> str:
    ...
```

```python
Exec(retry=None, platforms=None, run="always", silent=False)
Retry(attempts, backoff="exponential", on=(), on_exit_codes=())
#     backoff: "exponential" | "linear" | "constant"
#     run:     "always" | "once" | "when_changed"   (session-scoped dedup)
```

There is **no job-level timeout**, deliberately: Python cannot preempt a
running function, so a reported timeout would leave the work running. Bound
work where the OS can enforce it — `sh(..., timeout=N)`.

If you are asked for something that is not in either list, check `j.__all__`
before concluding it does not exist. If it genuinely does not, **say so** —
implementing a lookalike under the requested name is the worse answer, because
the caller has no way to tell it apart from the real thing.

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

## State — per-invocation, and the name misleads

`State` is a dict-backed store scoped to **one job invocation**. It is shared
down an `Invoke` chain within that invocation, and it is gone when the process
exits.

```python
state.set("parsed_count", 42)
state.get("parsed_count", default=0)
state.keys(prefix="cache:")
```

Three different things in this project are called "state", and only one of them
survives a process:

| Name | Reached by | Scope | Survives the process? |
| --- | --- | --- | --- |
| `State` (capability) | a job parameter | one invocation | **no** |
| `StateStore` (runtime) | `functualize.app.utils` | the project | **yes** — `.functualize/state.json` |
| The discovery cache | `func builtin cache` | the project | yes, but it is not yours |

For a value that must outlive the run, write a file you own, or use the runtime
store — never `State`. `func builtin state show` prints where the runtime store
lives; see [config-and-secrets.md](config-and-secrets.md) for the two modes it
resolves between.

## Sources — `declared` is not "non-empty"

A job that declares `Fingerprint(sources=...)` has already expanded that glob
before the body runs, to decide freshness. `Sources` hands the body the result
instead of making it restate the glob — two statements of one intent, free to
drift.

```python
@job(cache=Fingerprint(sources=["src/**/*.yaml"]))
def parse(sources: Sources) -> Parsed:
    for path in sources.keys():
        ...
```

Empty and undeclared are different questions, and conflating them is the bug
this sits next to:

| Declaration | `.declared` | `len()` |
| --- | --- | --- |
| `sources=["src/*.yaml"]`, files present | **yes** | populated |
| `sources=["absent/*.yaml"]`, no match | **yes** | **0** |
| no `Fingerprint`, or no `sources` | **no** | 0 |

So test `.declared` to ask "did this job declare inputs?" and `len()` /
truthiness to ask "did any file match?". A bare `if not sources:` treats a glob
that matched nothing as a job that never declared one.

## `Stdin` is not a capability

`functualize.job` also exports `Stdin`, which is an **annotation marker**, not
an injected type. It makes one parameter fall back to piped stdin when no flag
was given:

```python
from typing import Annotated
from functualize.job import Stdin

def transform(data: Annotated[str, Stdin(flag="--data")]) -> None: ...
```

```bash
echo "hello" | func transform          # reads stdin
func transform --data hello            # explicit flag wins
```

Declaring it as a bare parameter type (`def transform(stdin: Stdin)`) does not
work — it is `Annotated[...]` or nothing.

## Choosing

One capability per concern. If a job needs the terminal, it wants `TTY` or
`Live`, not `Stdout`. If it needs another job's result, it wants `Invoke`, not a
direct import — a direct call skips config resolution, hooks, and the event bus.
