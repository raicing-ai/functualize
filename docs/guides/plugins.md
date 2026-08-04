# Plugins

Functualize supports extending your application with plugins discovered automatically via Python entry points. Plugins can add CLI commands, register hooks, modify configuration, or integrate third-party services — all without modifying the core application code.

## How Plugin Discovery Works

Functualize uses Python's [entry point](https://packaging.python.org/en/latest/specifications/entry-points/) mechanism to discover plugins at startup. When your `FunctualizeApp` initializes, the `PluginLoader` scans for installed packages that declare entry points under the `functualize.plugins` group.

```python
from functualize.app import FunctualizeApp, JobSources, PluginSources

app = FunctualizeApp(
    name="my-app",
    job_sources=JobSources(directories=["jobs"]),
    plugin_sources=PluginSources(group="functualize.plugins"),  # (1)!
)
```

1. The `plugin_sources` parameter defaults to `PluginSources(group="functualize.plugins")`. You can change this to use a custom entry point group name for your application.

The discovery process:

1. The `PluginLoader` queries all installed packages for entry points in the configured group
2. Each entry point is loaded (imported)
3. The loaded object is validated against the `PluginMetadata` protocol
4. If valid, the plugin is invoked with the application instance to complete registration

### Custom Entry Point Group

If you're building a framework on top of Functualize and want plugins scoped to your application, pass a custom group name:

```python
app = FunctualizeApp(
    name="my-framework",
    plugin_sources=PluginSources(group="my_framework.plugins"),  # Custom group
)
```

Plugins would then declare their entry points under `[project.entry-points."my_framework.plugins"]` instead.

## The PluginMetadata Protocol

Every plugin must satisfy the `PluginMetadata` protocol by exposing three attributes:

| Attribute     | Type   | Constraint                    |
|---------------|--------|-------------------------------|
| `name`        | `str`  | Maximum 64 characters         |
| `version`     | `str`  | Must conform to [PEP 440](https://peps.python.org/pep-0440/) |
| `description` | `str`  | Maximum 256 characters        |

The protocol is defined as a `typing.Protocol` with `runtime_checkable`:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class PluginMetadata(Protocol):
    """Protocol that plugins must satisfy to be loaded."""

    name: str
    version: str
    description: str
```

!!! note "PEP 440 Version Format"
    The `version` string must be a valid PEP 440 version. Examples of valid versions:

    - `"1.0.0"` — simple release
    - `"2.1.0b3"` — beta pre-release
    - `"1.0.0rc1"` — release candidate
    - `"1.0.0.post1"` — post-release
    - `"1.0.0.dev0"` — development release
    - `"1!1.0.0"` — epoch version

## Plugin Callable Requirement

In addition to metadata attributes, a plugin **must be callable**. The `PluginLoader` invokes the plugin object with the application instance as the sole argument; its CLI command surface is a Click `Group`, reached via `app.cli_command`. This is the registration step where your plugin hooks into the application.

```python
class MyPlugin:
    name = "my-plugin"
    version = "1.0.0"
    description = "Adds a greeting command"

    def __call__(self, app):  # (1)!
        """Register plugin functionality with the app."""
        @app.command()
        def greet(name: str = "World"):
            """Say hello."""
            print(f"Hello, {name}!")
```

1. The `app` parameter is the application instance. Use `app.cli_command` (a Click `Group`) to register commands, add callbacks, or access any Click API.

## Entry Point Configuration

To make your plugin discoverable, declare it as an entry point in your plugin package's `pyproject.toml`:

```toml
[project.entry-points."functualize.plugins"]
my-plugin = "my_plugin_package:MyPlugin"  # (1)!
```

1. The format is `entry-point-name = "module.path:PluginClass"`. The entry point name is used for logging; the plugin's `name` attribute is used for duplicate detection.

The entry point value follows the standard `module:attribute` format:

- **Module path**: The dotted import path to the module containing your plugin
- **Attribute**: The class or object in that module that satisfies `PluginMetadata` and is callable


## Error Handling

The `PluginLoader` is designed to be resilient. Individual plugin failures never crash the application — problematic plugins are skipped with a warning log message, and loading continues with the remaining plugins.

### Import Failures

If a plugin's entry point cannot be imported (e.g., missing dependency, syntax error), the plugin is skipped:

```
WARNING - Plugin 'my-plugin' failed to load: No module named 'missing_dep'
```

!!! info "Entry-point load failure resilience"

    `ImportError` during entry-point loading is treated as a graceful skip. The plugin is skipped with a warning, and loading continues with remaining plugins. This prevents a single broken plugin from crashing the entire application.

### Metadata Validation Failures

If a loaded plugin doesn't satisfy the `PluginMetadata` protocol (missing attributes, invalid types, constraint violations), it is skipped:

```
WARNING - Plugin entry point 'my-plugin' does not satisfy metadata protocol:
          'name' exceeds 64 characters (got 72); 'version' does not conform to PEP 440: 'bad'
```

### Duplicate Plugin Names

If two plugins share the same `name` attribute, the second one is skipped. The first plugin loaded wins:

```
WARNING - Duplicate plugin name 'my-plugin' from entry point 'ep2'
          (already loaded from 'ep1'). Skipping.
```

### Registration Errors

If a plugin raises an exception during the `__call__` registration step, it is skipped:

```
WARNING - Plugin 'my-plugin' (entry point 'my-ep') raised an error during
          registration: TypeError: ...
```

!!! tip "Debugging Plugin Issues"
    Set the log level to `DEBUG` to see successful plugin loads:

    ```
    DEBUG - Successfully loaded plugin 'health-check' (version 1.0.0)
    ```

## Inspecting Loaded Plugins

While `FunctualizeApp` handles plugin loading automatically, you can inspect loaded plugins through the app:

```python
# Inspect what was loaded
for plugin_name in app.get_plugin_commands():
    print(f"Plugin command: {plugin_name}")
```

---

## Plugin CLI Command Registration

Plugins can register their own CLI commands on the host application using `app.register_plugin_command()`:

```python
class MCPPlugin:
    name = "mcp-server"
    version = "1.0.0"
    description = "Adds MCP server commands"

    def __call__(self, app) -> None:
        def serve(port: int = 8080):
            """Start the MCP server."""
            print(f"Starting MCP server on port {port}")

        def stop():
            """Stop the MCP server."""
            print("Stopping MCP server")

        # Register under an "mcp" namespace
        app.register_plugin_command("serve", serve, namespace="mcp", help_text="Start the MCP server")
        app.register_plugin_command("stop", stop, namespace="mcp", help_text="Stop the MCP server")
```

This creates `my-app mcp serve` and `my-app mcp stop` commands.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Command name (1-64 chars, `^[a-z][a-z0-9-]{0,63}$`) |
| `callback` | `Callable` | The callable to invoke when the command runs |
| `group` | `str \| None` | Sub-group name (creates `app <group> <name>`) or `None` for top-level |
| `help_text` | `str` | Help text for the command (max 256 chars) |

!!! warning "Validation"

    - Invalid command names raise `ValueError`
    - Duplicate names within the same group raise `ValueError`
    - Non-callable callbacks raise `ValueError`

---

## Plugin Instance Registry

Plugins can look up other loaded plugins by name using `app.get_plugin(name)`:

```python
class DashboardPlugin:
    name = "dashboard"
    version = "1.0.0"
    description = "Web dashboard for monitoring"

    def __call__(self, app) -> None:
        # Get a reference to the execution-state plugin
        try:
            state_plugin = app.get_plugin("execution-state")
            self._db = state_plugin.get_connection()
        except KeyError:
            # Plugin not installed — use fallback
            self._db = None
```

Raises `KeyError` with a helpful message listing registered plugin names if the plugin isn't found.

---

## Dynamic Job Registration

Plugins can register new jobs at runtime using `app.register_dynamic_job()`:

```python
from pydantic import BaseModel, Field

class HealthCheckConfig(BaseModel):
    endpoint: str = Field(description="URL to check")
    timeout: int = Field(default=5, description="Timeout in seconds")

class HealthPlugin:
    name = "health-monitor"
    version = "1.0.0"
    description = "Registers health check jobs dynamically"

    def __call__(self, app) -> None:
        def check_health(config: HealthCheckConfig, rc) -> dict:
            """Check endpoint health."""
            import httpx
            resp = httpx.get(config.endpoint, timeout=config.timeout)
            return {"status": resp.status_code}

        app.register_dynamic_job(
            name="health-check",
            function=check_health,
            config_class=HealthCheckConfig,
            group="monitoring",
        )
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Unique job name |
| `function` | `Callable` | The job function to execute |
| `config_class` | `type \| None` | Optional Pydantic BaseModel for config validation |
| `group` | `str \| None` | Optional group name |

Dynamic jobs are fully functional — invocable via `rc.invoke()`, visible in the TUI, and trigger `JOB_REGISTERED` hooks.

---

## Interactivity Plugin Registration

Plugins providing rendering or input capabilities should register using `app.register_surface()`:

```python
from functualize.plugin import PromptRequest, PromptResponse, StructuredEvent


class MyRendererPlugin:
    name = "my-renderer"
    version = "1.0.0"
    description = "Custom output renderer"

    def __call__(self, app) -> None:
        app.register_surface(self)

    # Surface protocol — receives the event fan-out:
    def handle_event(self, event: StructuredEvent) -> None:
        ...

    # Optional PromptCollector protocol — answer rc.prompt_*():
    def collect(self, request: PromptRequest) -> PromptResponse:
        ...
```

`register_surface` validates protocol conformance and raises `TypeError` if the object satisfies neither `Surface` (`handle_event`) nor `PromptCollector` (`collect`). The full contract is detailed under [Interactivity: Surfaces and Prompt Collectors](#interactivity-surfaces-and-prompt-collectors).

---

## PluginWithShutdown Protocol

Plugins that manage long-lived resources (database connections, servers, file handles) can implement the `PluginWithShutdown` protocol for graceful cleanup:

```python
class WebSocketPlugin:
    name = "ws-relay"
    version = "1.0.0"
    description = "WebSocket relay for job events"

    def __call__(self, app) -> None:
        self._server = start_ws_server()

    def on_shutdown(self, app) -> None:  # (1)!
        """Called during application shutdown."""
        self._server.close()
```

1. Shutdown methods are called in **reverse loading order** with a **5-second per-plugin timeout**. If `on_shutdown` exceeds 5 seconds, the call is abandoned and the next plugin is processed.

---

## Monorepo Workspace Structure

For projects maintaining multiple plugins alongside the core framework, a `plugins/` directory provides monorepo-style organization:

```
functualize/
├── src/functualize/        # Core framework
├── plugins/
│   ├── functualize-state-sqlite/       # SQLite-backed state persistence
│   ├── functualize-inline/             # Textual inline PromptCollector
│   └── functualize-flow-viz/           # Inline flow tree Surface
└── pyproject.toml
```

Each plugin directory contains its own `pyproject.toml` with entry point declarations and can be installed independently.

### Official Plugins

| Plugin | Description |
|--------|-------------|
| `functualize-ai` | AI Domain SDK for functualize — LLM interaction capabilities |
| `functualize-ai-pydantic` | PydanticAI-backed AI implementation plugin for functualize |
| `functualize-http` | HTTP delivery adapter plugin for functualize using asyncio |
| `functualize-lambda` | AWS Lambda adapter plugin for functualize - supports fat and thin Lambda deployment patterns |
| `functualize-mcp` | MCP delivery adapter plugin for functualize — exposes jobs as MCP tools via FastMCP |
| `functualize-state` | State Domain SDK providing protocols for state persistence and execution tracking |
| `functualize-tasks` | Tasks Domain SDK for functualize — task management capabilities |
| `functualize-tasks-local` | Local state-backed task storage plugin for functualize |
| `functualize-flow-viz` | Inline flow visualization plugin for functualize job execution |
| `functualize-inline` | Textual inline interactivity plugin for functualize prompts (full-screen support is now in `functualize[cli]` via `functualize.ui.TextualApp`) |
| `functualize-state-sqlite` | SQLite-backed state persistence and execution tracking plugin for functualize |

---

## Interactivity: Surfaces and Prompt Collectors

A plugin can join a job's live conversation with the user through two
independent, single-method protocols (both re-exported from
`functualize.plugin`):

- **`Surface`** — *engine → UI*. Receives a 1:N fan-out of every structured
  event a job emits. This is how the inline TUI, flow-viz, a log writer, or your
  own web dashboard render live progress.
- **`PromptCollector`** — *UI → engine*. Answers a job's `rc.prompt_*()`
  questions. Exactly one collector is active at a time — whoever owns the
  terminal or modal right now.

They are independent capabilities: a render-only surface has no `collect`; the
stdin fallback collects but renders nothing; a full-screen app satisfies both.
An object may register as either or both.

A job never touches these. Its whole conversational API is the `RunContext`
(`rc.log` / `rc.emit` / `rc.prompt_*`); the engine turns those into
`StructuredEvent`s and `PromptRequest`s and routes them. That ignorance is what
lets one unmodified job render in a TUI panel, in plain stdout, in a job-owned
app, as MCP gate checkpoints, or under a test double. The full architecture is
documented in `contributor/architecture/interactivity-model.md`.

### The `Surface` protocol

```python
@runtime_checkable
class Surface(Protocol):            # engine → UI, 1:N fan-out
    def handle_event(self, event: StructuredEvent) -> None: ...
```

`StructuredEvent` carries `event_name` (a `{domain}.{resource}.{action}` string
such as `job.execute.start`), `resource`, and a `payload` dict.

!!! danger "Threading contract"
    `handle_event` is called on the **job's worker thread** whenever a host owns
    the terminal. A surface that touches a UI must marshal onto its own loop
    (Textual: `post_message` / `call_from_thread`). Writing to a widget directly
    from `handle_event` freezes the app silently — no exception, no traceback.

    A surface that draws on the terminal is suspended while a job owns the screen
    (`tty: TTY`). Headless surfaces — log files, MCP progress, telemetry, test
    recorders — set `needs_terminal = False` on themselves and keep receiving
    events throughout, so a run stays observable even then.

Exceptions raised inside `handle_event` are logged and swallowed — one
misbehaving surface never interrupts a job or starves its peers.

### The `PromptCollector` protocol

```python
@runtime_checkable
class PromptCollector(Protocol):    # UI → engine, one active collector
    def collect(self, request: PromptRequest) -> PromptResponse: ...
```

`collect` blocks until the user answers, the prompt times out, or it is
cancelled, returning a `PromptResponse(value, source)` where `source` is one of
`"user" | "default" | "timeout" | "cancelled"`.

### Registering a surface

Register in your plugin's `__call__(app)` with `app.register_surface(obj)`. The
object must satisfy `Surface`, `PromptCollector`, or both — registering
something that satisfies neither raises `TypeError`. Registration is explicit;
there is no auto-detection.

```python
# src/my_monitor/__init__.py
from functualize.plugin import StructuredEvent


class ConsoleMonitor:
    """A render-only Surface that prints job events to stdout."""

    name = "console-monitor"
    version = "1.0.0"
    description = "Prints job lifecycle events"
    # Headless: keep receiving events even while a job owns the terminal.
    needs_terminal = False

    def __call__(self, app) -> None:
        app.register_surface(self)

    def handle_event(self, event: StructuredEvent) -> None:
        print(f"[{event.event_name}] {event.resource} {event.payload}")
```

Register the plugin via entry point as usual:

```toml
# pyproject.toml
[project.entry-points."functualize.plugins"]
console-monitor = "my_monitor:ConsoleMonitor"
```

The reference `Surface` is the inline TUI (`FunctualizeInlineTUI`,
`_cli/tui/app.py`), which renders events into its panels;
`functualize.ui.StdoutSurface` renders to scrollback plus a `rich.live` zone.
Use either as a template for a richer backend.

### Submitting Jobs from a Backend

Any interactivity backend can trigger job execution without touching `JobExecutionEngine` directly. Instead, emit the `interactivity.job.submit` event on the `EventBus`:

```python
app.event_bus.emit(
    "interactivity.job.submit",
    resource=job_name,
    job_name=job_name,
    kwargs={},          # CLI kwargs forwarded to the job function
)
```

`FunctualizeApp` subscribes `_on_job_submit_event` to this topic at boot. When the event arrives the handler resolves the job and delegates to `JobExecutionEngine.execute()`.

**Why use the event instead of calling `engine.execute()` directly?**

- **Decoupling** — Your backend does not need a reference to the engine or the job registry.
- **Thread safety** — The EventBus handles dispatch; the engine serializes execution internally.
- **Testability** — In tests, subscribe a handler to `interactivity.job.submit` to assert that jobs are triggered without running real jobs.

```python
# Example: trigger a job from a Textual button press
from textual.widgets import Button


class RunButton(Button):
    def on_button_pressed(self) -> None:
        self.app.functualize_app.event_bus.emit(
            "interactivity.job.submit",
            resource="my-job",
            job_name="my-job",
            kwargs={"verbose": True},
        )
```
