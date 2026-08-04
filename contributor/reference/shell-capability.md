# Shell Capability Reference

**Audience:** contributors working on the `Shell` capability or engine integration.
**Status:** shipped (S0–S5). S6 (shell output channel + `stream=True` default sink +
`silent`) is ~90% done.

## 1. Layer Placement

| Layer | Location | Purpose |
|-------|----------|---------|
| Protocol | `_types/shell.py` | `ShellProtocol` — all surface-independent contracts |
| Implementation | `_engine/capabilities/shell.py` | DI-registered capability, subprocess lifecycle |
| Public API | `functualize.job` | Re-exported for job authors |
| Testing | `functualize.testing` | `FakeShell` with pattern→result table |
| Redaction | `_types/redaction.py` | `Secret[T]` wrapper, shared secret masking |

## 2. Command Forms

Three forms, in order of preference:

### List form (safe default)

```python
result = sh(["git", "commit", "-m", msg], capture=True)
```

Preferred idiom. No shell injection risk. Each argument is a separate list element.

### Template form (auto-quoting)

```python
result = sh("git commit -m {msg}", msg="Release {version}")
```

Uses `shlex.quote()` on each value. Safer than raw strings but still involves shell parsing
on POSIX (uses `/bin/sh -c` for template substitution).

### Raw form (`shell=True`)

```python
result = sh("git commit -m '$MSG' | gpg --sign", shell=True)
```

Raw shell string. Only when the other forms cannot express the pipeline. `shell=True`
must be explicit.

### Per-platform shell selection

POSIX: `/bin/sh`. Windows: `pwsh` → `cmd` fallback. Template/string quoting is per-platform
(`shlex` on POSIX, subprocess argv rules on Windows).

## 3. Execution Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `capture` | `bool` | `False` | Capture stdout/stderr into `ShellResult` |
| `stream` | `bool` | `False` | Stream stdout/stderr to the surface's output channel |
| `check` | `bool` | `True` | Raise on non-zero exit |
| `pty` | `bool` | `False` | Use pseudo-terminal allocation |
| `env` | `dict` | `None` | Additional environment variables (merged with `os.environ`) |
| `replace_env` | `bool` | `False` | Replace entire environment with `env` |
| `cwd` | `str \| Path` | `None` | Working directory |
| `timeout` | `float` | `None` | Subprocess timeout (enforceable — subprocess is killed) |
| `retry` | `Retry` | `None` | Retry config for this command |
| `watchers` | `list[Responder]` | `None` | Stdout/stderr pattern responders |
| `in_stream` | `bytes \| str` | `None` | Data piped to stdin |
| `label` | `str` | `None` | Perf/EventBus label for this invocation |
| `shell` | `bool` | `False` | Use raw shell string (must be explicit) |

## 4. `ShellResult`

```python
@dataclass
class ShellResult:
    command: str | None  # Redacted if Secret was used (set to None)
    stdout: str
    stderr: str
    returncode: int
    duration_ms: float
    timed_out: bool
    ok: bool  # returncode == 0
```

`command` is redacted to `None` when `Secret[T]` values were passed, so logs/telemetry
never leak secrets.

## 5. Context Managers

### `sh.cd(path)`

```python
with sh.cd("/tmp"):
    sh(["pwd"])  # /tmp
```

Thread-local directory change. Nestable.

### `sh.prefix(prefix)`

```python
with sh.prefix("source venv/bin/activate"):
    sh(["pip", "list"])
```

Prepends a shell prefix command (e.g. virtualenv activation). Thread-local, nestable.
Uses semicolons to chain nested prefixes.

## 6. `sh.sudo()`

```python
result = sh.sudo(["systemctl", "restart", "nginx"])
```

- Password from config (`[shell] sudo_password` or `FUNCTUALIZE_SUDO_PASSWORD`)
- Interactive fallback when no config password and surface is interactive
- `--preserve-env` by default (controlled by `preserve_env=True/False`)

## 7. `sh.defer(callable, *, background=False)`

```python
sh.defer(lambda: sh(["docker", "stop", cid]))
```

- LIFO execution order (most recent deferred runs first)
- Signal-aware (SIGINT/SIGTERM triggers defer stack)
- Engine-owned unwind (runs in the engine's cleanup hook, not the job's exception handler)
- `background=True`: run the deferred callable in a daemon thread (non-blocking)

## 8. Secret Masking

```python
from functualize._types.redaction import Secret

password = Secret("s3cret")
sh(["curl", "-u", f"admin:{password}", url])
```

- `Secret[T]` wraps any value for redaction
- `ShellResult.command` is set to `None` when secrets are present
- Redaction module (`_types/redaction.py`) is shared across shell, logging, and EventBus

**Wired sinks:** logs, shell result, EventBus payloads, PerfTimeline labels.
**Deferred sinks:** TUI display, JSON serialization, child-app passthrough.

## 9. Perf + EventBus Integration

Shell invocations emit:
- `shell.command.start` / `shell.command.end` events
- PerfTimeline phases named `shell.<label>`
- `ShellResult` is attached to the event payload

## 10. Testing with `FakeShell`

```python
from functualize.testing import FakeShell

fake = FakeShell()
fake.register("git status", ShellResult("git status", "clean\n", "", 0, 12.0, False, True))

with fake:
    sh = DI.resolve(Shell)
    r = sh(["git", "status"])
    assert r.stdout == "clean\n"
    assert r.ok
```

- **Pattern→result table:** register expected commands and their `ShellResult`.
- **`.calls`:** list of `(cmd, kwargs)` for every invocation.
- **Loud on unexpected:** unregistered commands raise with a clear message and the
  full args list.
- **`Secret` in list form:** detects the `Secret` wrapper and redacts it
  from the recorded command list (matching production behavior).
