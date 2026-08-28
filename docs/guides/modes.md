# Usage Modes

Functualize supports four interaction modes, each suited to a different stage of project maturity. This guide explains when to use each mode, how to scaffold it, and what trade-offs to expect.

---

## Single-File Mode

**Command:** `func file.py function_name`

Run a single Python file as a job without any project setup. Ideal for scripts, one-offs, and quick experiments.

### When to use

- You have a standalone script and want structured execution (logging, config, lifecycle hooks)
- You're prototyping a job before committing to a full project
- You want to run a colleague's job file without installing their project

### How to scaffold

No scaffolding needed. Write a Python file with a public function:

```python title="deploy.py"
def run(target: str, dry_run: bool = False):
    """Deploy to the given target."""
    print(f"Deploying to {target}")
    if dry_run:
        print("Dry run — no changes made")
```

Run it directly:

```bash
func deploy.py run --target production --dry-run
```

If the file has only one public function, you can omit the function name:

```bash
func deploy.py --target production
```

### Example with RunContext

```python title="sync.py"
from functualize.job import RunContext

def sync(rc: RunContext, source: str, dest: str):
    """Sync files between locations."""
    rc.log(f"Syncing {source} → {dest}")
    # ... sync logic ...
    rc.log("Done")
```

```bash
func sync.py sync --source /data --dest /backup
```

### Limitations

- No auto-discovery — you must specify the file and function explicitly
- No config file resolution (environment variables and CLI args still work)
- No plugin loading from `pyproject.toml` entry points
- No child project composition
- No cache — the module is imported fresh every time

---

## Directory Mode

**Command:** `func` in a project directory with a `jobs/` folder

The standard mode for multi-job projects. Functualize discovers all job modules automatically, builds a CLI command tree, and provides the full feature set including config files, plugins, and caching.

### When to use

- You have 3+ related jobs that share configuration
- You want auto-discovery to build the CLI for you
- You need config file resolution (TOML, `.env`)
- You want the TUI for interactive exploration

### How to scaffold

```bash
func builtin scaffold init my-project
cd my-project
uv sync
```

This generates:

```
my-project/
├── pyproject.toml          # Entry point + functualize dependency
├── src/my_project/
│   ├── __init__.py
│   ├── main.py             # FunctualizeApp construction
│   └── jobs/
│       └── sample_job.py   # Auto-discovered job
└── config.base.toml        # Default configuration
```

Add jobs by creating files in the `jobs/` directory:

```bash
func builtin scaffold add job deploy
```

### Example

```python title="src/my_project/jobs/deploy.py"
JOB_NAME = "deploy"

def run(target: str, env: str = "staging", dry_run: bool = False):
    """Deploy the application."""
    print(f"Deploying to {target} ({env})")

def rollback(target: str):
    """Rollback the last deployment."""
    print(f"Rolling back {target}")
```

```bash
# Auto-discovered commands
my-project deploy run --target api --env production
my-project deploy rollback --target api

# Browse with TUI
my-project tui

# Or use func in the project directory
func deploy run --target api
```

### Project structure conventions

Functualize discovers jobs through these conventions (checked in order):

1. `jobs/` directory in the project root
2. `[tool.functualize] job_directories` in `pyproject.toml`
3. Python files with `JOB_NAME = "..."` markers

### Limitations

- Requires a project directory with recognizable structure
- Jobs must follow naming conventions (public functions, no underscore prefix)
- CLI entry point needs to be installed (`uv sync` or `pip install -e .`)

---

## Library Mode

**Command:** `FunctualizeApp(...)` in your own CLI module

Embed functualize as a library inside your own application. You control the CLI entry point, boot configuration, plugin selection, and delivery adapter. This is the mode used by production tools and frameworks.

### When to use

- You need custom CLI behavior beyond what auto-discovery provides
- You want programmatic control over plugins, config presets, and execution
- You're building a framework or internal tool that uses functualize as infrastructure
- You need multiple `FunctualizeApp` instances (e.g., for testing)

### How to scaffold

```bash
func builtin scaffold init my-tool
cd my-tool
uv sync
```

Then customize `main.py` to wire your specific configuration:

```python title="src/my_tool/main.py"
from functualize.app import (
    FunctualizeApp,
    JobSources,
    ConfigSources,
    PluginSources,
    twelve_factor,
)
from functualize.app.adapters import CliAdapter

def main():
    app = FunctualizeApp(
        name="my-tool",
        job_sources=JobSources(directories=["src/my_tool/jobs"]),
        config_sources=twelve_factor(dotenv=True),
        plugin_sources=PluginSources(entry_point_group="my_tool.plugins"),
    )

    adapter = CliAdapter(app)
    adapter.run()
```

Register as a CLI entry point in `pyproject.toml`:

```toml
[project.scripts]
my-tool = "my_tool.main:main"
```

### Example with custom presets

```python title="src/my_tool/main.py"
from functualize.app import (
    FunctualizeApp,
    ConfigSources,
    JobSources,
    classic,
    env_only,
)
from functualize.app.adapters import CliAdapter
import os

def main():
    # Choose preset based on environment
    if os.getenv("DEPLOYMENT") == "production":
        config = env_only(dotenv=False)
    else:
        config = classic(file_pattern=r"^config\.(\w+)\.toml$")

    app = FunctualizeApp(
        name="my-tool",
        job_sources=JobSources(directories=["src/my_tool/jobs"]),
        config_sources=config,
    )

    adapter = CliAdapter(app)
    adapter.run()
```

### Example with DI and plugins

```python title="src/my_tool/main.py"
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter
from my_tool.services import DatabasePool, MetricsClient

def main():
    app = FunctualizeApp(
        name="my-tool",
        job_sources=JobSources(directories=["src/my_tool/jobs"]),
    )

    # Register services for DI injection into jobs
    app.provide(DatabasePool, DatabasePool(url=os.getenv("DB_URL")))
    app.provide(MetricsClient, MetricsClient())

    adapter = CliAdapter(app)
    adapter.run()
```

Jobs access DI services via `RunContext`:

```python title="src/my_tool/jobs/migrate.py"
from functualize.job import RunContext
from my_tool.services import DatabasePool

JOB_NAME = "db"

def migrate(rc: RunContext):
    """Run database migrations."""
    pool = rc[DatabasePool]
    pool.execute("SELECT 1")
    rc.log("Migrations complete")
```

### Limitations

- More boilerplate than directory mode (you write the wiring code)
- You're responsible for adapter selection and boot configuration
- Changes to job sources require updating `main.py`

---

## Adapter Mode

**Delivery:** HTTP, Lambda, or TUI adapter instead of CLI

Deliver your functualize jobs through non-CLI surfaces. The same `FunctualizeApp` instance powers all adapters — you only swap the delivery layer.

### When to use

- You need an HTTP API to trigger jobs (internal tooling dashboards, webhooks)
- You're deploying to AWS Lambda or similar serverless environments
- You want the interactive TUI for exploring and running jobs
- You need multiple delivery surfaces for the same job set

### HTTP Adapter

Install the HTTP adapter plugin:

```bash
uv add functualize-http
```

```python title="src/my_tool/server.py"
from functualize.app import FunctualizeApp, JobSources, twelve_factor
from functualize_http import HttpAdapter

app = FunctualizeApp(
    name="my-tool",
    job_sources=JobSources(directories=["src/my_tool/jobs"]),
    config_sources=twelve_factor(),
)

adapter = HttpAdapter(app, host="0.0.0.0", port=8080)
adapter.run()
```

Jobs are exposed as HTTP endpoints:

```bash
curl -X POST http://localhost:8080/jobs/deploy/run \
  -H "Content-Type: application/json" \
  -d '{"target": "production", "env": "prod"}'
```

### Lambda Adapter

Install the Lambda adapter plugin:

```bash
uv add functualize-lambda
```

```python title="handler.py"
from functualize.app import FunctualizeApp, JobSources, env_only
from functualize_lambda import LambdaAdapter

app = FunctualizeApp(
    name="my-tool",
    job_sources=JobSources(directories=["jobs"]),
    config_sources=env_only(dotenv=False),
)

adapter = LambdaAdapter(app)
handler = adapter.make_handler()
```

Deploy `handler` as your Lambda function entry point. The adapter translates Lambda events into job executions.

### TUI Adapter

The TUI adapter ships with the core `[cli]` extras:

```python title="src/my_tool/main.py"
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import TuiAdapter

def main():
    app = FunctualizeApp(
        name="my-tool",
        job_sources=JobSources(directories=["src/my_tool/jobs"]),
    )

    adapter = TuiAdapter(app)
    adapter.run()
```

Or launch from the CLI with `my-tool tui` (when using `CliAdapter`, TUI is available as a built-in sub-command).

### Limitations

- HTTP and Lambda adapters are separate packages (`functualize-http`, `functualize-lambda`)
- Lambda adapter has cold-start considerations (keep dependencies lean)
- TUI requires `[cli]` extras installed (`click`, `rich`, `textual`)
- HTTP/Lambda adapters don't support interactive prompts (`rc.prompt()`)

---

## Comparison Table

| Feature | Single-File | Directory | Library | Adapter |
|---------|:-----------:|:---------:|:-------:|:-------:|
| Auto-discovery | — | ✓ | Manual | Inherits from app |
| Config files (TOML) | — | ✓ | ✓ | ✓ |
| Environment variables | ✓ | ✓ | ✓ | ✓ |
| Preset system | — | ✓ | ✓ | ✓ |
| Plugin loading | — | ✓ | ✓ | ✓ |
| DI registration | — | ✓ | ✓ | ✓ |
| TUI | — | ✓ | ✓ | ✓ (dedicated) |
| Child projects | — | ✓ | ✓ | ✓ |
| Caching | — | ✓ | ✓ | ✓ |
| EventBus / hooks | Limited | ✓ | ✓ | ✓ |
| Custom CLI entry point | — | ✓ | ✓ | N/A |
| Non-CLI delivery (HTTP/Lambda) | — | — | — | ✓ |
| Zero project setup | ✓ | — | — | — |
| `rc.invoke()` (job chaining) | ✓ | ✓ | ✓ | ✓ |

---

## Decision Guide

Choose your mode based on project maturity:

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  Start here → Single-file mode                                      │
│  "I have one script, I just want to run it"                         │
│                                                                     │
│         │                                                           │
│         ▼  (you now have 3+ jobs)                                   │
│                                                                     │
│  Graduate → Directory mode                                          │
│  "I have several jobs that share config"                            │
│                                                                     │
│         │                                                           │
│         ▼  (you need custom CLI, DI, or plugin wiring)              │
│                                                                     │
│  Upgrade → Library mode                                             │
│  "I need programmatic control over the app"                         │
│                                                                     │
│         │                                                           │
│         ▼  (you need HTTP/Lambda/TUI delivery)                      │
│                                                                     │
│  Add → Adapter mode                                                 │
│  "I need to expose jobs as an API or run serverless"                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Rules of thumb

- **Start with single-file mode.** No ceremony, no project structure. Just a function and `func file.py`.
- **Graduate to directory mode** when you have 3+ jobs, need config files, or want the TUI for discovery.
- **Switch to library mode** when you need custom CLI behavior, DI registration, or want to distribute your tool as a standalone command.
- **Add adapter mode** when you need non-CLI delivery (HTTP APIs, Lambda handlers) or want a dedicated TUI experience.

Library mode and adapter mode are complementary — you construct a `FunctualizeApp` (library mode) and then attach an adapter to it. Most production projects use both.

---

## Next steps

- **[Architecture](architecture.md)** — How the layers fit together internally
- **[Configuration](configuration.md)** — Layered config resolution and presets
- **[Jobs and Auto-Discovery](jobs-discovery.md)** — How functualize finds your job functions
- **[Plugins](plugins.md)** — Extending functualize with plugins
