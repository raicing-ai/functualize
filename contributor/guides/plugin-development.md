# Guide: Developing Official Plugins

Official plugins live in the monorepo under `plugins/` and are published as separate PyPI packages.

## Creating a New Plugin

### 1. Create the package structure

```
plugins/functualize-my-plugin/
├── pyproject.toml
├── src/
│   └── functualize_my_plugin/
│       ├── __init__.py      # PluginMetadata + re-exports
│       └── plugin.py        # Plugin implementation
└── tests/
    └── test_my_plugin.py
```

### 2. Write pyproject.toml

```toml
[project]
name = "functualize-my-plugin"
version = "0.1.0"
description = "What this plugin does"
requires-python = ">=3.11"
dependencies = [
    "functualize>=0.1.0",
    # Add plugin-specific deps here
]

[project.entry-points."functualize.plugins"]
my-plugin = "functualize_my_plugin:MyPlugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/functualize_my_plugin"]
```

### 3. Implement the plugin

```python
# src/functualize_my_plugin/__init__.py
from functualize_my_plugin.plugin import MyPlugin

__all__ = ["MyPlugin"]

# src/functualize_my_plugin/plugin.py
from typing import Any


class MyPlugin:
    """Plugin metadata (satisfies PluginMetadata protocol)."""
    name = "my-plugin"
    version = "0.1.0"
    description = "What this plugin does"

    # Optional: declare dependencies on other plugins
    # depends_on: list[str] = ["observability"]

    # Optional: declare config requirements
    # config_model = MyPluginConfig
    # config_section = "my_plugin"

    def __call__(self, app: Any) -> None:
        """Called during boot. Register hooks, middleware, etc."""
        # Examples:
        # app.provide(MyService, MyServiceImpl())
        # app.register_plugin_command("my-cmd", self._handle, "Help text")
        # app.event_bus.subscribe("job.execute.*", self._on_job)
        pass
```

### 4. Add to workspace

In the root `pyproject.toml`:

```toml
[tool.uv.workspace]
members = ["plugins/*"]  # Already a glob — your plugin is auto-included

[tool.uv.sources]
functualize-my-plugin = { workspace = true }
```

### 5. Install locally for development

```bash
uv sync
```

The workspace setup makes your plugin available in the dev environment immediately.

### 6. Test it

```python
# plugins/functualize-my-plugin/tests/test_my_plugin.py
from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize_my_plugin import MyPlugin


def test_plugin_loads():
    app = FunctualizeApp(
        "test",
        job_sources=JobSources(),
        plugin_sources=PluginSources(explicit_plugins=[MyPlugin()]),
    )
    # Assert your plugin's effects
```

## Plugin Patterns

### Capability Plugin (registers a CLI command)

```python
class HttpServerPlugin:
    name = "http-server"
    version = "1.0.0"
    description = "HTTP server for job execution"

    def __call__(self, app):
        app.register_plugin_command("serve", self._start_server, "Start HTTP server")

    def _start_server(self, port: int = 8000):
        # Start server using app reference
        ...
```

### Adapter Plugin (delivery surface)

```python
class LambdaAdapter:
    name = "lambda"
    version = "1.0.0"
    description = "AWS Lambda adapter"
    adapter_type = "lambda"

    def __call__(self, app):
        self._app = app

    def run(self, event, context):
        job_name = event["job"]
        kwargs = event.get("kwargs", {})
        result = self._app.execute(job_name, **kwargs)
        return {"statusCode": 200, "body": result.return_value}

    def shutdown(self):
        pass
```

### Observer Plugin (subscribes to events)

```python
class SlackNotifier:
    name = "slack-notifier"
    version = "1.0.0"
    description = "Notify Slack on job completion"

    def __call__(self, app):
        app.event_bus.subscribe("job.execute.success", self._on_success)
        app.event_bus.subscribe("job.execute.failure", self._on_failure)

    def _on_success(self, event):
        # Post to Slack
        ...
```

### Interactivity Plugin (output + input)

```python
class InlinePromptPlugin:
    name = "inline-prompt"
    version = "1.0.0"
    description = "Inline Textual prompts"

    def __call__(self, app):
        app.register_surface(self)

    # Surface method — receives the StructuredEvent fan-out:
    def handle_event(self, event) -> None: ...

    # PromptCollector method — answers rc.prompt_*():
    def collect(self, request) -> PromptResponse: ...
```

## Examples

Every plugin ships runnable examples in `plugins/<name>/examples/`:

```
plugins/functualize-my-plugin/
├── examples/
│   ├── README.md              ← Table of scenarios + how to run them
│   └── <scenario>/            ← One focused scenario (jobs + optional test)
│       ├── <scenario>.py
│       └── test_<scenario>.py
├── src/...
└── tests/...
```

Rules:

- **One focused scenario** demonstrating the plugin's core capability — not a feature tour. Keep tiny plugins' examples tiny.
- **Runnable without secrets where possible** — use the domain's testing double (`MockAI`, `InMemoryState`, `AutoPrompt`, `MockTasks`). If the plugin's whole point is a real external service (e.g. `functualize-ai-pydantic`), document the required env vars in the README and skip the automated test.
- **Interactive plugins** (inline widgets, fullscreen TUI) get a README with manual verification steps instead of a pytest file.
- Example tests are **not collected by root pytest** (same isolation rule as `plugins/<name>/tests/`) — run them explicitly: `uv run pytest plugins/<name>/examples/ -v`.
- Larger examples that are full projects (own `pyproject.toml`) pin workspace deps with relative `[tool.uv.sources]` paths — see `plugins/functualize-http/examples/http_service/`.

## Key Rules

1. **Never import from `functualize._*`** — plugins use only the public API
2. **Declare all heavy deps in your pyproject.toml** — don't bloat the core
3. **Use entry points for auto-discovery** — users shouldn't need to configure anything
4. **Satisfy protocols structurally** — no need to inherit from framework classes
5. **Handle absence gracefully** — if your plugin can't find what it needs, log a warning, don't crash boot
6. **Respect the 50ms import budget** — see Performance Rules below

## Performance Rules

**See `contributor/reference/performance.md` for the complete plugin import budget reference.**

Quick summary: Plugin import + instantiation must complete in <50ms. This is a hard constraint because the `func` CLI starts a new process for every invocation, and slow plugin imports impact all users who have the plugin installed — even if they never use it.

### Key Guidelines

**No heavy imports at module level.** Your plugin's `__init__.py` and entry-point class must be importable in <50ms.

Defer heavy SDK imports to `__call__()` or first-use methods (they're cached per process anyway).

Use lazy DI factories and `__getattr__` patterns for deferred initialization.

For detailed patterns and CI enforcement, see `contributor/reference/performance.md` (sections: "Plugin Import Budget", "The Rule: No Heavy Imports at Module Level", "Lazy DI Factory", "Lazy Module Exports").
