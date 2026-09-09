# Contracts — run-outcome-authority

External interfaces only.

---

## 1. `functualize.types` — the outcome module

New `src/functualize/_types/outcome.py`, re-exported from `functualize.types` and
`functualize.app.utils`. Stdlib-only.

```python
from enum import Enum

class Family(str, Enum):
    PROCESS = "process"   # an exit code a shell sees
    PANEL   = "panel"     # a rendered outcome inside a live surface
    TOOL    = "tool"      # a status string in a tool response
    WIRE    = "wire"      # an HTTP status

def exit_code_for_status(status: RunStatus) -> ExitCode: ...      # moved, unchanged
def http_status_for_status(status: RunStatus) -> int: ...          # moved, unchanged
def is_failure(status: RunStatus, *, family: Family) -> bool: ...  # NEW — the rule
def report_line(status: RunStatus) -> str | None: ...              # NEW — BLOCKED/REFUSED text
def status_from_wire(value: str) -> RunStatus | None: ...          # NEW — kills _resume_exit's fallback
def wire_value(status: RunStatus) -> str: ...                      # NEW — the inverse
```

`exit_code_for_status` and `http_status_for_status` keep their names and behaviour and stay
importable from `functualize.types` — every existing caller continues to work.

> **`is_failure` takes the family, and that is the whole design.** `is_failure(BLOCKED,
> family=PROCESS)` is `True`; `is_failure(BLOCKED, family=PANEL)` is `False`. The difference
> that lives in a comment today becomes an argument.

## 2. `functualize.types` — the flag grammar

New `src/functualize/_types/flag_grammar.py`, stdlib-only.

```python
VALUE_FLAGS: frozenset[str]              # from _cli/dispatch.py:81
OPTIONAL_VALUE_FLAGS: frozenset[str]     # from dispatch.py:90-101
BOOL_FLAGS: frozenset[str]               # from dispatch.py:121

def negative_flag_for(name: str) -> str: ...   # re-homed from _types/naming.py:100
def flag_aliases(name: str) -> tuple[str, ...]: ...        # from dispatch.py:703
def negative_aliases(name: str) -> tuple[str, ...]: ...    # from dispatch.py:736
def match_group_flag(token: str, ...) -> ... : ...         # from dispatch.py:750-767
```

`negative_flag_for` keeps its public name and import path
(`functualize.types`, `functualize.app.utils`) — it moves module, not identity.

### Deliberately excluded

`--perf-report`'s optional-value **lookahead** stays in `_cli/dispatch.py`, with a comment in
both files naming the reason: it is about *reaching the program*, not about the run, and
pre-boot is the only place it can be answered.

## 3. Delivery surfaces — the family declaration

Each surface names its family once:

| Surface | Family | Where |
|---|---|---|
| `deliver_job_result` | `PROCESS` | `app/adapters/click_params.py` |
| `func builtin parallel` | `PROCESS` | `_cli/builtins.py` |
| `func builtin workflow resume` | `PROCESS` | `_cli/builtins.py` |
| inline TUI — **panel render** | `PANEL` | `_cli/tui/job_execution.py` |
| inline TUI — **process exit** | `PROCESS` | `_cli/tui/job_execution.py` |
| MCP | `TOOL` | `plugins/functualize-mcp/.../_tools.py` |
| HTTP, Lambda | `WIRE` | both plugin `__init__.py` |

The TUI appears twice, and that is the point of §3.3: one surface, two questions.

## 4. Removed

- `src/functualize/_types/http_status.py` — contents move into `outcome.py`; the module
  re-exports for one release-free cutover, or is deleted outright (pre-release).
- `_cli/builtins.py::_resume_exit`'s hand-rolled `0 if status in {"answered", "drafted"}
  else 1` fallback.
- `_cli/tui/job_execution.py`'s literal success tuple.
- `_cli/builtins.py`'s `func builtin parallel` success tuple.

## 5. Unchanged

- Every exit code and HTTP status **value**.
- Every flag spelling, including `--no-*`.
- `RunStatus`'s members, `.resumable` and `.ran`. (It has no `.ok` — that is on `WalkReport`.)
