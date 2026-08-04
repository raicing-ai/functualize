# Performance Reference

Consolidated performance budgets, targets, and measurement strategies for the framework.

## Cold Boot Target (NFR-1)

**Target:** `FunctualizeApp` with zero jobs must boot in ≤30ms.

This target applies to the initialization time from app construction through `scan_and_register()` completion. The measurement is enforced in CI via `tests/perf/test_startup_budget.py`.

**Why this matters:** The framework supports cold-start scenarios (Mode B/C via `func` CLI), where boot time directly impacts user experience. Every 100ms of boot overhead makes the tool feel sluggish on repeat invocations.

## Boot Phase Budgets

FunctualizeApp initialization executes in twelve ordered steps. Each phase has a CI-enforced time budget.

Measured in `tests/perf/test_startup_budget.py`:

| Phase | Budget | Notes |
|-------|--------|-------|
| `core_infra` | 50ms | HookRegistry, DIRegistry, JobExecutionEngine instantiated |
| `provider_registry` | 10ms | Built-in TOML + INI format providers registered |
| `observability` | 50ms | EventBus, MiddlewareStack created (before plugins can subscribe) |
| `plugins` | 200ms | Entry-point + file-based plugin loading via topological sort |
| `config_entry_points` | 50ms | Format/remote provider entry point discovery |
| `config_resolution` | 100ms | ResourceLocator + ResolutionChain built once |
| `job_registration` | 50ms | Providers from JobSources wired (directories → CachedDirectoryScanProvider, functions → Static) |
| `children` | 50ms | Child FunctualizeApp projects mounted |
| `tui` | 20ms | Textual/TUI infrastructure (if enabled) |
| **Total boot** | **500ms** | Cumulative budget for all phases |

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

The cold boot test verifies that `FunctualizeApp(zero_jobs)` boots in ≤30ms:

```bash
uv run pytest tests/perf/test_startup_budget.py::test_cold_boot_under_30ms -v
```

This test runs in CI and blocks merges if violated.

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
