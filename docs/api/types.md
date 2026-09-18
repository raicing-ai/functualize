# Types Module — Run Model Vocabulary

::: functualize.types
    options:
      show_root_heading: true
      members_order: source

---

## Overview

`functualize.types` is the shared type vocabulary for job authors, plugin authors, and app constructors. This page documents the **run-model** slice of that vocabulary — the door a run entered through, and how a finished run's status translates into what a delivery surface actually reports. It is the largest addition to `functualize.types` in this release; see [Discovery (Internal)](discovery.md) for `JobDescriptor`/`FieldDescriptor` and [Config (Internal)](config.md) for the config-file and environment vocabulary.

**Module location:** `src/functualize/_types/run_request.py` (surface vocabulary) and `src/functualize/_types/outcome.py` (status translation).

### Public API

```python
from functualize.types import (
    RunSurface,
    RUN_SURFACES,
    request_from_envelope,
    wire_value,
    status_from_wire,
    report_line,
)
```

---

## `RunSurface` and `RUN_SURFACES`

`RunSurface` is a `Literal` naming every door a run can enter through — the one field every `RunRequest` (`functualize.types.RunRequest`, the frozen dataclass every entry surface builds and `JobExecutionEngine.run` consumes) must set, with no default, because a door must name itself:

```python
RunSurface = Literal[
    "func.job", "func.group", "func.single-file",
    "app.cli", "app.execute", "func.builtin",
    "tui.inline", "tui.shell",
    "mcp.tool", "mcp.run-job", "mcp.async",
    "http", "lambda",
    "invoke", "invoke.parallel", "app.parallel",
    "event.job-submit", "engine.step", "engine.dependency",
]
```

`RUN_SURFACES` is the `frozenset[str]` of those same 19 values, **derived from the `Literal` via `get_args()`** rather than typed out a second time, so the two vocabularies cannot drift:

```python
from functualize.types import RUN_SURFACES, RunSurface

def build_request(surface: RunSurface) -> None:
    if surface not in RUN_SURFACES:
        raise ValueError(f"unknown surface {surface!r}")
```

A `RunRequest` constructed with a surface outside `RUN_SURFACES` raises `ValueError` naming the offender and the closed set, so a door that mistypes its own name is caught at construction rather than traveling all the way to the run record.

---

## `request_from_envelope`

```python
def request_from_envelope(
    payload: Mapping[str, Any],
    *,
    job_name: str,
    surface: RunSurface,
) -> RunRequest: ...
```

Parses a wire payload into a `RunRequest` — the one shared implementation for every out-of-process door (HTTP, Lambda, and MCP's two doors), which previously carried byte-identical copies of this parsing differing only in the `surface` literal.

The payload is an **envelope**: a job's own parameters live under a nested `"arguments"` key, and control inputs sit beside it, never inside:

```python
{
    "arguments": {"target": "prod"},
    "group_option_values": {"env": "staging"},
    "scope_id": "run-42",
    "force": True,
}
```

This nesting is deliberate, not decoration — a flat body let a caller's own argument name collide with a control field (sending `{"scope_id": "x"}` silently chose the workflow scope a run joined instead of passing an argument). `scope_id` is also what makes a gated workflow **resumable over the wire**: start it, read the scope id back from the result metadata, answer the gate, send the same id again.

```python
from functualize.types import request_from_envelope

request = request_from_envelope(
    {"arguments": {"target": "prod"}, "force": True},
    job_name="deploy",
    surface="http",
)
```

**Breaking, deliberately.** Job parameters used to be the whole request body; they are now nested under `"arguments"`.

**Raises:** `ValueError` — a field is present with the wrong JSON type (`arguments` not an object, `group_option_values` not an object, `scope_id` not a string). Each case is reported by name.

---

## `wire_value` and `status_from_wire`

The inverse pair that turns a `RunStatus` into the status string a tool or HTTP response carries, and reads one back:

```python
def wire_value(status: RunStatus) -> str: ...
def status_from_wire(value: str) -> RunStatus | None: ...
```

```python
from functualize.types import RunStatus, status_from_wire, wire_value

wire_value(RunStatus.BLOCKED)        # "blocked"
status_from_wire("blocked")          # RunStatus.BLOCKED
status_from_wire("not-a-status")     # None
```

`wire_value` is `status.value.lower()` — lowercase, stable, and an interface callers branch on rather than a rendering choice. `status_from_wire` does the reverse lookup and returns `None` when the string names no status, handing the "this was unrecognised" fact back to the caller instead of guessing a fallback outcome.

---

## `report_line`

```python
def report_line(status: RunStatus) -> str | None: ...
```

The one line a status owes the caller before its exit code, HTTP status, or tool string is delivered. Only two statuses have something to say first:

```python
from functualize.types import RunStatus, report_line

report_line(RunStatus.BLOCKED)
# "Blocked: the run paused at a declared gate and is resumable."
report_line(RunStatus.REFUSED)
# "Refused: a declared precondition for running this job was not met."
report_line(RunStatus.SUCCESS)
# None
```

Returns `None` for every status that owes nothing, so a caller can write `if (line := report_line(status)):` without a second table. The *detail* — which gate, which scope, the resume incantation — stays with the surface that holds the result object; this is the sentence, not the report.

!!! note "Why this exists"
    Nine call sites used to translate a `RunStatus` into something a caller could act on, each with its own copy of the rules, and two of them disagreed about whether a paused (`BLOCKED`) run counts as a failure. `functualize.types` is now the single authority: a delivery surface asks, it does not decide. See `report_line`'s sibling `is_failure(status, *, family=...)` for the family-scoped failure question (not part of this page's public surface).
