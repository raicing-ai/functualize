# Testing Module

::: functualize.testing
    options:
      show_root_heading: true
      members_order: source

---

## Overview

`functualize.testing` provides test doubles and builders for unit testing jobs without spawning processes, hitting the filesystem, or standing up a live app.

**Module location:** `src/functualize/testing/`

### Public API

```python
from functualize.testing import (
    TestRunContext,
    CapturingLog,
    MockInvoke,
    AutoPrompt,
    NoopPerf,
    FakeShell,
    FakeShellCall,
    FakeStdout,
)
```

`TestRunContext`, `CapturingLog`, `MockInvoke`, `AutoPrompt`, `NoopPerf`, and `FakeShell` are covered in the [Composing Capabilities](../guides/composition.md) and [Shell Capability](../guides/shell.md) guides. `FakeShellCall` and `FakeStdout` are documented here.

---

## `FakeShellCall`

A single recorded `FakeShell` invocation. `FakeShell` (the `Shell` capability's test double) appends one of these to `fake.calls` for every command it resolves, whether or not the command was actually mapped to a result.

```python
@dataclass(frozen=True)
class FakeShellCall:
    argv: list[str]
    command: str
    kwargs: dict[str, Any] = field(default_factory=dict)
```

| Attribute | Type | Description |
|---|---|---|
| `argv` | `list[str]` | The resolved argument vector — the list form, or the display string split back apart. |
| `command` | `str` | The display string the command resolved to (what a mapping key matches against). |
| `kwargs` | `dict[str, Any]` | The keyword options passed to the call — includes an effective `cwd` when the call ran inside a `sh.cd(...)` block. |

```python
from functualize.testing import FakeShell

fake = FakeShell({"git status": ShellResult(0, "clean\n", "", "git status", 12.0, None)})
deploy(sh=fake)

assert fake.calls[0].argv == ["git", "status"]
assert fake.calls[0].command == "git status"
```

---

## `FakeStdout`

An in-memory double for the `Stdout` capability (`out: Stdout`). Records what a job emits so pipeline behavior can be asserted without capturing a real process's stdout.

```python
class FakeStdout:
    def __init__(self, output_format: str = "auto") -> None: ...

    emitted: list[Any]      # objects passed to emit(), in order
    writes: list[str | bytes]  # raw payloads passed to write(), in order

    @property
    def text(self) -> str: ...  # everything written so far, as a pipe consumer would see it

    def emit(self, value: Any) -> None: ...
    def write(self, data: str | bytes) -> None: ...
```

| Member | Type | Description |
|---|---|---|
| `output_format` (constructor arg) | `str` | The format `emit` renders with — `"auto"` (default, dispatch by value type), `"json"`, `"ndjson"`, `"raw"`, or `"none"`. Mirrors the `--emit-format` flag so a test can pin the wire shape a caller would get. |
| `emitted` | `list[Any]` | The *objects* handed to `emit()`, in order — assert on data, not on formatting. |
| `writes` | `list[str \| bytes]` | Raw `write()` payloads, in order. |
| `text` (property) | `str` | The rendered stream exactly as a pipe would see it — assert on the wire format. |

```python
from functualize.testing import FakeStdout

fake = FakeStdout()
run_job(export, out=fake)

assert fake.emitted == [{"id": 1}, {"id": 2}]
assert fake.text.splitlines() == ['{"id":1}', '{"id":2}']
```
