# Shell Capability

The `Shell` capability lets you run external commands from within your jobs — with proper lifecycle management, secret redaction, and testing support.

## Quick Start

```python
from functualize.job import RunContext
from functualize.job.capabilities import Shell

def deploy(sh: Shell, rc: RunContext):
    """Deploy the application."""
    rc.log("Building...")
    sh(["uv", "build"])

    rc.log("Syncing dependencies...")
    sh(["uv", "sync"])

    rc.log("Running tests...")
    result = sh(["pytest", "-q"], check=False)
    if not result.ok:
        rc.log(f"Tests failed: {result.stderr}")
```

## Command Forms

Three ways to invoke commands, from safest to most flexible:

### List form (recommended)

```python
sh(["git", "commit", "-m", "Release v1.0"])
sh(["pip", "install", package_name])
```

No shell injection risk. Each argument is a separate list element. This is the default idiom.

### Template form

```python
sh("git commit -m {message}", message="Release v1.0")
```

Values are auto-quoted with `shlex.quote()`. Uses `/bin/sh -c` for template substitution on POSIX.

### Raw form

```python
sh("docker ps | grep nginx", shell=True)
```

Raw shell string. Only when the other forms cannot express what you need. `shell=True` must be explicit.

## Execution Options

```python
result = sh(
    ["pytest", "-q"],
    stream=None,        # or a callable receiving output chunks
    check=True,         # raise on non-zero exit (default)
    cwd="/tmp",
    env={"DEBUG": "1"},
    in_stream="data",   # str piped to stdin
    timeout=30.0,
    pty=False,
    retry=None,
    label="tests",
)
```

## Context Managers

### `sh.cd()` — change directory

```python
with sh.cd("/tmp"):
    sh(["pwd"])  # /tmp
```

Thread-local. Nestable.

### `sh.prefix()` — prepend commands

```python
with sh.prefix("source venv/bin/activate"):
    sh(["pip", "list"])
```

Virtualenv activation, environment setup, etc. Thread-local, nestable.

## `sh.sudo()`

```python
result = sh.sudo(["systemctl", "restart", "nginx"])
```

Password from config (`[shell] sudo_password` or `FUNCTUALIZE_SUDO_PASSWORD`). Falls back to interactive prompt when no config password is present.

## `sh.defer()` — cleanup on exit

```python
cid = sh(["docker", "run", "-d", "nginx"], background=True).stdout.strip()
sh.defer(["docker", "stop", cid])
# ... on job exit (success, failure, Ctrl+C, timeout), the command runs automatically
```

LIFO order (most recent deferred runs first). Signal-aware — `SIGINT`/`SIGTERM` triggers the defer stack. `sh.defer` takes a command (list or str), not a callable.

## ShellResult

```python
result = sh(["git", "status"])
print(result.stdout)      # "clean\n"
print(result.returncode)  # 0
print(result.ok)          # True
print(result.duration_ms) # 12.0
```

When `Secret` values are passed as arguments, `result.command` is redacted to `None` — so logs never leak sensitive data.

## Observability

Shell invocations emit events and appear in the PerfTimeline:

```
shell.tests.start  →  shell.tests.end (128ms)
```

In the TUI, these appear in the execution tree with timing data.

## Testing with FakeShell

```python
from functualize.testing import FakeShell
from functualize._types.shell import ShellResult

fake = FakeShell({
    "git status": ShellResult(0, "clean\n", "", "git status", 12.0, None),
})
deploy(sh=fake)                 # inject the double for the Shell parameter
assert fake.calls[0].argv == ["git", "status"]
assert fake.calls[0].command == "git status"
```

`FakeShell` is loud on unexpected commands — it raises with the full args list so you see exactly what went wrong.

## See Also

- [Composing Capabilities](composition.md) — how this fits with the other capabilities: a combination matrix of what happens at each intersection, and the traps between them
- [Task Runner Guide](task-runner.md) — `@job` with `deps`, `fingerprint`, `guards`
