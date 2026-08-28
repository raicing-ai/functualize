# Performance Reference

Consolidated performance budgets, targets, and measurement strategies for the framework.

## Cold Boot Target (NFR-1)

**Aspiration:** `FunctualizeApp` with zero jobs boots in ≤30ms.
**Enforced today:** 500ms (`BUDGET_TOTAL_BOOT_MS`).
**Measured today:** ~119ms median, ~152ms worst, over 10 cold boots in an empty CWD.

These three numbers are 16× apart at the extremes, and this document previously stated
only the first while implying it was enforced. It is not: no test asserts 30ms, and the
test this document used to name — `test_cold_boot_under_30ms` — does not exist.

Treat 30ms as the design goal it is. The gap is not mysterious; see **Where boot time
actually goes** below.

**Why this matters:** The framework supports cold-start scenarios (Mode B/C via `func` CLI), where boot time directly impacts user experience. Every 100ms of boot overhead makes the tool feel sluggish on repeat invocations — and boot is paid per CLI invocation, not once per session.

## Boot Phase Budgets

FunctualizeApp initialization executes in twelve ordered steps. Each phase has a CI-enforced time budget.

Measured in `tests/perf/test_startup_budget.py`:

| Phase | Budget | Median measured | Notes |
|-------|--------|-----------------|-------|
| `core_infra` | 50ms | 0.18ms | HookRegistry, DIRegistry, JobExecutionEngine instantiated |
| `provider_registry` | 10ms | 0.06ms | Built-in TOML format provider registered. `IniFormatProvider` is in-tree but must be registered by a plugin (ADR-007) |
| `observability` | 50ms | 0.00ms | EventBus, MiddlewareStack created (before plugins can subscribe) |
| `plugins` | 200ms | 13.43ms | Entry-point + file-based plugin loading via topological sort |
| `config_entry_points` | 50ms | 19.45ms | Format/remote provider entry point discovery |
| `config_resolution` | 300ms | 37.19ms | ResourceLocator + ResolutionChain built once |
| `job_registration` | 50ms | 0.00ms | Providers from JobSources wired (directories → CachedDirectoryScanProvider, functions → Static) |
| `children` | 50ms | 2.01ms | Child FunctualizeApp projects mounted |
| `domains` | **none** | **44.87ms** | Domain discovery + per-domain provider scan — **the second-largest phase, and unbudgeted** |
| **Total boot** | **500ms** | **118.62ms** | Cumulative budget for all phases |

Measured over 10 cold boots in an empty CWD, `boot.*` phases only.

Two corrections to what this table used to say:

- **`tui` (20ms) has been removed.** That phase no longer exists — `test_tui_budget`
  asserts `boot.tui` is *not* emitted, since TUI registration moved to `CliAdapter.run()`
  during the Phase 5 adapter extraction. Listing it as an enforced budget was wrong.
- **`config_resolution` is 300ms, not 100ms.** Raised in `cde4cb8` after the 100ms figure
  was found to be a standing breach rather than a flake: it measured min 93.4 / median
  127.5 / max 158.4ms, i.e. over budget more often than under, passing only on lucky runs.
  The phase has since been fixed (see below) and now runs ~37ms, so **this budget is now
  far too loose and should be brought down**.

Several other budgets are two to three orders of magnitude above their measured cost
(`observability` at 50ms against 0.00ms). They cannot catch a regression until it is
catastrophic. Tightening them is worthwhile but should be done from fresh measurements on
CI hardware, not from these workstation figures.

## Where boot time actually goes

As of 2026-08-20, two findings account for most of the gap between the 30ms goal and the
~119ms reality.

**Fixed — `discover_config_path` stat'd every file before reading its name** (`a8c02f9`).
The upward config-file search ran `entry.is_file() and regex.match(entry.name)` per
directory entry. `is_file()` is a syscall and the regex is pure string work, so every file
in every ancestor directory was stat'd before anything looked at it — 17,249 syscalls per
boot from a CWD under a busy `/tmp`. Reordering the pure predicates first took
`config_resolution` from 158.67ms to 41.02ms and total boot from 250.87ms to 125.00ms.
Recorded as pitfall #16.

**Open — one boot calls `importlib.metadata.entry_points()` seven times.** Each call scans
*all* installed distributions and reads every `entry_points.txt` from disk before applying
the group filter; the group argument narrows the result, not the scan. With 215
distributions installed that is 91.59ms across the seven calls where a memoised version
costs 13.08ms once — **~79ms recoverable**, most of what boot now spends. The behaviour is
identical in Python 3.11, 3.12 and 3.13, so no interpreter upgrade fixes it. The call
count is also not a constant: `scan_domain_providers` runs once per registered domain, so
installations with more domain plugins pay more, which is why `domains` is the
second-largest phase.

**Exceeding Budget:** If any phase exceeds its budget in CI, the test fails. This is a regression gate — performance improvements are welcome, but degradation blocks merges.

## Plugin Import Budget

**Hard constraint: Plugin import + instantiation must complete in <50ms.**

This applies to each individual plugin. The `func` CLI starts a new process for every invocation, and plugin loading happens on every boot. A single slow plugin kills interactivity for all users who have it installed — even if they never use it.

### The Rule: No Heavy Imports at Module Level

Your plugin's `__init__.py` and the entry-point class module must be importable in <50ms.

**❌ BAD — Top-level heavy imports:**
```python
# plugin.py
from fastmcp import FastMCP           # pulls in httpx, anyio, pydantic
from pydantic import BaseModel        # 200ms+ cold import
import httpx                          # async HTTP client machinery

class MCPPlugin:
    name = "mcp"
```

**✅ GOOD — Deferred imports:**
```python
# plugin.py
from typing import Any

class MCPPlugin:
    name = "mcp"
    version = "1.0.0"
    description = "MCP delivery adapter"

    def __call__(self, app: Any) -> None:
        """Register capabilities — still no heavy imports."""
        self._app = app
        app.register_plugin_command("mcp", self._start_server, "Start MCP server")

    def _start_server(self, port: int = 6789) -> None:
        """Heavy imports happen here — only when actually needed."""
        from fastmcp import FastMCP    # <-- deferred to first use
        from functualize_mcp._server import MCPServer

        server = MCPServer(self._app, FastMCP("functualize"))
        server.run(port=port)
```

### What's Allowed at Import Time

| Import Time (module level) | `__call__()` Time | First-Use Time |
|---|---|---|
| `typing`, `dataclasses`, `enum` | Lightweight app registration | Heavy SDK imports |
| `functualize.plugin` protocols | `app.event_bus.subscribe(...)` | Network clients |
| Metadata constants | `app.register_plugin_command(...)` | Database connections |
| Lightweight stdlib | DI bindings (lazy factories) | Pydantic model validation |

### Pattern: Lazy DI Factory

Bind a factory that defers the heavy import until first use:

```python
class MCPPlugin:
    name = "mcp"
    version = "1.0.0"

    def __call__(self, app: Any) -> None:
        # Bind a factory — import only happens when a job requests MCPServer
        app._di_registry.bind_factory("MCPServer", self._create_server)
        self._app = app

    def _create_server(self):
        from fastmcp import FastMCP
        from functualize_mcp._server import MCPServer
        return MCPServer(self._app, FastMCP("functualize"))
```

### Pattern: Lazy Module Exports

Keep `__init__.py` lightweight using `__getattr__`:

```python
# __init__.py
"""My Plugin — description."""

from my_plugin._plugin import MyPlugin

__all__ = ["MyPlugin", "MyHeavyClass"]

def __getattr__(name: str):
    """Lazy-load heavy symbols on first access."""
    if name == "MyHeavyClass":
        from my_plugin._heavy import MyHeavyClass
        return MyHeavyClass
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### Import Cost Reality

Python caches imported modules in `sys.modules`. Once a module is imported (during `__call__()` or first use), all subsequent accesses in the same process are effectively free (dict lookup). Cost breakdown:

- **First invocation:** full import cost (e.g., 861ms for `fastmcp`)
- **Same process, subsequent calls:** ~0ms (cached)

Since `func` is a CLI (new process per invocation), every `func` run pays the import cost for top-level imports. Deferring heavy imports to first use means most invocations pay zero cost.

### CI Enforcement

Add plugin load time validation to CI (example):

```bash
uv run func --perf-report json version 2>&1 | python -c "
import json, sys
data = json.load(sys.stdin)
for phase in data['phases']:
    if phase['name'].startswith('boot.plugins.load.') and phase['duration_ms'] > 50:
        print(f\"FAIL: {phase['name']} took {phase['duration_ms']:.0f}ms (budget: 50ms)\")
        sys.exit(1)
print('All plugins within budget.')
"
```

## Measurement and Verification

### Boot Phase Measurement

Location: `tests/perf/test_startup_budget.py`

The test runs with a minimal `FunctualizeApp` (zero jobs, explicit static sources) and measures time from construction through boot completion. Each phase reports its duration, and the total is validated against the 500ms budget.

To measure locally:

```bash
uv run pytest tests/perf/test_startup_budget.py -v
```

Output shows per-phase timings and passes/fails against budget.

### Plugin Load Time Measurement

Plugins are measured as part of the overall `plugins` phase budget (200ms total for all plugins). Individual plugin loads exceeding 50ms trigger warnings during boot:

```
WARNING: Plugin 'my-plugin' took 861ms to load (budget: 50ms).
Consider deferring heavy imports to __call__() or first use.
```

### Cold Boot Verification (NFR-1)

There is **no** `test_cold_boot_under_30ms`; this document used to name it. The total-boot
assertion is `TestStartupBudget::test_total_boot_time`, and it checks the 500ms budget, not
the 30ms goal:

```bash
uv run pytest tests/perf/test_startup_budget.py::TestStartupBudget::test_total_boot_time -v
```

This runs in CI and blocks merges if violated.

To measure the actual distribution rather than a single pass/fail — which is how the stale
`config_resolution` budget was found — boot repeatedly and read the phase report directly:

```python
import os, tempfile, statistics
from functualize._app.state import AppState
from functualize._events.perf import perf_timeline
from functualize.app.core import FunctualizeApp

rows: dict[str, list[float]] = {}
for _ in range(10):
    AppState.reset(); perf_timeline.reset()
    with tempfile.TemporaryDirectory() as d:
        cwd = os.getcwd(); os.chdir(d)
        try:
            FunctualizeApp(name="b")
            for p in perf_timeline.report().phases:
                rows.setdefault(p.name, []).append(p.duration_ms)
        finally:
            os.chdir(cwd)

for name, vals in sorted(rows.items(), key=lambda kv: -statistics.median(kv[1])):
    print(f"{name:28s} median={statistics.median(vals):7.2f}  max={max(vals):7.2f}")
```

A single-sample budget test cannot distinguish "slow under load" from "over budget
always". Check the median before concluding a perf test is flaky.

## Static vs Lazy Wiring Trade-offs

### Mode A: Eager Import (Full Boot)

- **Phase timing:** Layer 1 + Layer 2 combined (slower but complete)
- **Cost:** O(N modules) imports at boot
- **Benefit:** Full Click tree available for --help, TUI introspection
- **When to use:** Declared apps with pre-known job directories, where bootstrap time is acceptable
- **Budget:** Contributes to `job_registration` phase (50ms budget)

### Mode B/C: Cache + Lazy (Discovery Mode)

- **Phase timing:** Layer 1 (cached) + Layer 2 (lazy) separated (faster, deferred)
- **Cost:** O(new/stale) imports at Layer 1 discovery, O(1) at invocation
- **Benefit:** Cold start is faster, repeated invocations benefit from cache warmup
- **When to use:** `func` CLI, one-shot execution, unknown CWD
- **Budget:** Fits within overall 500ms boot budget

## References

- **Boot sequence:** See `contributor/architecture/boot-sequence.md` for detailed step-by-step initialization
- **Plugin development:** See `contributor/guides/plugin-development.md` for plugin creation and performance patterns
- **Developer modes:** See `contributor/architecture/developer-modes.md` for how different entry points interact with these budgets
