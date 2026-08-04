# Hooks vs Plugins

Functualize provides two extension mechanisms — hooks and plugins — that serve different purposes but work together. This guide clarifies when to use each and how to share reusable behavior with colleagues.

## At a Glance

| | Hooks | Plugins |
|---|---|---|
| **What it is** | A callback function registered against a lifecycle event | An installable Python package discovered via entry points |
| **Scope** | Reacts to lifecycle events (before/after job, config resolution) | Can do anything: register hooks, add CLI commands, inject config, declare dependencies |
| **Discovery** | Registered imperatively in code | Auto-discovered via `pyproject.toml` entry points |
| **Distribution** | Lives in your app code | Installable package (`pip install`, `uv add`) |
| **Versioning** | None (part of your app) | PEP 440 versioned, dependency-managed |
| **Config support** | None (read config yourself in the handler) | Automatic config resolution via `config_model` / `config_section` |
| **Dependency ordering** | Registration order only | Topological sort via `depends_on` |

## The Relationship

Plugins are the **delivery mechanism**; hooks are one of the **extension points** a plugin can use. A plugin often registers hooks as part of its setup:

```python
from functualize.plugin import HookEvent

class MetricsPlugin:
    name = "metrics"
    version = "1.0.0"
    description = "Emits timing metrics for every job"

    def __call__(self, app):
        app.hook_registry.register_global(HookEvent.BEFORE_JOB, self._start_timer)
        app.hook_registry.register_global(HookEvent.ON_TEARDOWN, self._emit_duration)

    def _start_timer(self, rc):
        import time
        rc.metadata["_metrics_start"] = time.perf_counter()

    def _emit_duration(self, rc):
        import time
        start = rc.metadata.get("_metrics_start")
        if start:
            duration = time.perf_counter() - start
            rc.log(f"[metrics] Job completed in {duration:.3f}s")
```

But plugins can also do things hooks cannot:

- Add CLI commands (via `app.cli_command`)
- Declare config schemas that get auto-resolved through the Resolution Chain
- Participate in dependency ordering (`depends_on`)
- Subscribe to custom signals on the `SignalBus`

## When to Use Which

### Use hooks directly when...

- The behavior lives in your own app and just reacts to lifecycle events
- You need a quick, one-off cross-cutting concern (logging, metrics, cleanup)
- You want job-scoped behavior for a single job

```python
# In your app bootstrap — simple and direct
app.hook_registry.register_global(HookEvent.BEFORE_JOB, log_job_start)
app.hook_registry.register_for_job("etl", HookEvent.AFTER_FAILURE, alert_on_etl_failure)
```

### Use a plugin when...

- The behavior needs to be shared across projects or with colleagues
- It adds CLI commands or modifies the app structure
- It needs its own config section (e.g., `[plugin.notifications]`)
- It depends on other plugins being loaded first
- It should be versioned and released independently

## Sharing With Colleagues

### The problem with raw hooks

Hooks alone are not portable. They're registered imperatively in code:

```python
# This lives in YOUR app — your colleague can't reuse it without copy-pasting
app.hook_registry.register_global(HookEvent.BEFORE_JOB, my_audit_hook)
```

If a colleague wants the same behavior, they either copy-paste the function into their app or you share a module they need to manually import and wire up.

### The solution: wrap reusable hooks in a plugin

The canonical way to share reusable behavior is to package it as a plugin. The entry point system makes this zero-config for consumers:

**You (the author):**

```python title="src/functualize_audit/__init__.py"
"""Reusable audit logging plugin."""

from functualize.plugin import HookEvent
from functualize.job import RunContext


class AuditPlugin:
    name = "audit-logger"
    version = "1.0.0"
    description = "Logs job lifecycle events for auditing"

    def __call__(self, app):
        app.hook_registry.register_global(HookEvent.BEFORE_JOB, self._on_start)
        app.hook_registry.register_global(HookEvent.AFTER_FAILURE, self._on_failure)

    def _on_start(self, rc: RunContext):
        rc.log(f"[audit] Job '{rc.name}' starting")

    def _on_failure(self, rc: RunContext, exc: Exception):
        rc.log(f"[audit] Job '{rc.name}' failed: {exc}")
```

```toml title="pyproject.toml"
[project]
name = "functualize-audit"
version = "1.0.0"
dependencies = ["functualize>=0.1.0"]

[project.entry-points."functualize.plugins"]
audit-logger = "functualize_audit:AuditPlugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**Your colleague (the consumer):**

```bash
uv add functualize-audit
# or: pip install functualize-audit
# or for local dev: uv pip install -e ../functualize-audit
```

Done. The plugin is auto-discovered on next app run — no code changes in the host app.

### Sharing without publishing to PyPI

You don't need to publish to a package index. Common approaches:

- **Editable install from a local path**: `uv pip install -e ../my-plugin`
- **Install from a Git repo**: `uv pip install git+https://github.com/yourorg/functualize-audit.git`
- **Monorepo with workspace**: add the plugin as a workspace member and declare it as a dependency

## Decision Flowchart

```
Is this behavior reusable across projects?
├── No → Register hooks directly in your app
└── Yes
    ├── Does it only react to lifecycle events?
    │   └── Yes → Wrap your hooks in a minimal plugin package
    └── Does it also add CLI commands, config, or dependencies?
        └── Yes → Full plugin with config_model, depends_on, etc.
```

## Summary

| Scenario | Approach |
|----------|----------|
| Quick logging/metrics in your own app | Hook directly |
| Job-specific error handling | `register_for_job` hook |
| Behavior shared with one colleague | Plugin (editable install) |
| Behavior shared across your org | Plugin (Git install or private index) |
| Open-source extension | Plugin (published to PyPI) |
| Adding a CLI command | Plugin (only plugins can modify the CLI command group) |
| Needs its own config section | Plugin with `config_model` / `config_section` |
