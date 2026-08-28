# Project Structure

This page explains the project layouts for each mode of using functualize — from a single file to a full scaffolded project.

---

## Single-File Mode

The simplest layout. No structure required.

```
jobs.py          # Your job functions
```

Run with `func jobs.py deploy`. Functualize imports the file directly.

---

## Directory Mode

A `jobs/` folder with auto-discovery. Minimal structure, maximum convenience.

```
myproject/
├── jobs/
│   ├── deploy.py
│   ├── migrate.py
│   └── healthcheck.py
├── config.base.toml       # optional: layered config
└── pyproject.toml        # optional: for installable CLI
```

Run with `func deploy` from inside `myproject/`. Functualize discovers the `jobs/` directory automatically.

### What each part does

| Path | Purpose |
|------|---------|
| `jobs/` | Auto-discovered job directory. Every `.py` file with qualifying functions becomes a command. |
| `config.base.toml` | Base configuration. Values are overridden by env-specific files, env vars, and CLI args. |
| `pyproject.toml` | Optional. Needed only if you want the project installable as a named CLI command. |

---

## Full Project Mode (Scaffolded)

When you run `func builtin scaffold init my-app`, the following structure is generated:

```
my-app/
├── pyproject.toml
├── config.base.toml
└── src/
    └── my_app/
        ├── __init__.py
        ├── main.py
        └── jobs/
            ├── __init__.py
            └── sample_job.py
```

!!! note
    Hyphens in the project name are converted to underscores for the Python package. `my-app` becomes `my_app`.

---

## File Reference

### `pyproject.toml`

Project metadata, dependencies, and the CLI entry point:

```toml
[project]
name = "my-app"
version = "0.1.0"
description = "A CLI application built with functualize"
requires-python = ">=3.11"
dependencies = [
    "functualize>=0.1.0",
]

[project.scripts]
my-app = "my_app.main:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/my_app"]
```

The `[project.scripts]` section creates the `my-app` command when the package is installed. It points to the `run()` function in `main.py`.

### `config.base.toml`

The base configuration file for the layered config system. Functualize discovers this file by walking upward from the current working directory.

```toml
[general]
app_name = "my-app"
log_level = "INFO"

[jobs]
timeout = 30
retry_count = 0

[sample]
target = "default-target"
dry_run = false
```

Values are resolved in priority order: CLI args → env vars → config files → defaults. See the [Configuration Guide](../guides/configuration.md) for details.

### `src/<package>/main.py`

The application entry point. Creates a `FunctualizeApp` and defines the console script function:

```python
from functualize.app import FunctualizeApp, JobSources, ConfigSources, classic

app = FunctualizeApp(
    name="my-app",
    job_sources=JobSources(directories=["my_app.jobs"]),
    config_sources=classic(),
)

def run() -> None:
    """Console script entry point."""
    app.run()
```

| Parameter | Purpose |
|-----------|---------|
| `name` | App identifier — used for config directory fallback and logging |
| `job_sources` | Where to find job functions. `directories` lists Python module paths to scan. |
| `config_sources` | Configuration strategy. `classic()` uses file discovery. See [presets](#presets). |

### `src/<package>/jobs/`

The jobs directory where auto-discovery scans for job modules. Any Python module placed here that defines qualifying functions is registered as a CLI command.

- **`__init__.py`** — Marks the directory as a Python package (required for module import)
- **`sample_job.py`** — A working example job

### `src/<package>/jobs/sample_job.py`

A sample job demonstrating core patterns:

```python
"""Job module: sample."""

from pydantic import BaseModel, Field

from functualize.job import RunContext

JOB_NAME = "sample"


class SampleConfig(BaseModel):
    """Configuration schema for the sample job."""

    target: str = Field(description="Target resource to process")
    dry_run: bool = Field(default=False, description="Run without making changes")


def run(config: SampleConfig, rc: RunContext) -> None:
    """Execute the sample job."""
    rc.log(f"Starting sample job with target: {config.target}")
    rc.log("Job completed successfully")
```

| Element | Purpose |
|---------|---------|
| `JOB_NAME` | Groups functions under a CLI sub-command (`my-app sample run`) |
| `SampleConfig` | Pydantic model defining typed CLI options and config fields |
| `run()` | The job function — auto-discovered and registered as a command |
| `RunContext` | Structured execution context with logging, invocation, DI, events |

---

## Presets

The `config_sources` parameter accepts a preset that determines how configuration is resolved:

```python
from functualize.app import FunctualizeApp, JobSources, twelve_factor, env_only

# For Docker/Kubernetes — no config file discovery
app = FunctualizeApp(
    name="my-app",
    job_sources=JobSources(directories=["my_app.jobs"]),
    config_sources=twelve_factor(dotenv=True),
)

# For serverless — minimal env-only config
app = FunctualizeApp(
    name="my-app",
    job_sources=JobSources(directories=["my_app.jobs"]),
    config_sources=env_only(),
)
```

See the [Quickstart](quickstart.md#use-presets-for-production-deployments) for the full preset comparison table.

---

## Import Patterns

The restructured functualize package uses audience-separated imports:

```python
# Job authors — write job functions
from functualize.job import RunContext, Log, Invoke, Prompt, Perf, State

# App constructors — build and configure the app
from functualize.app import FunctualizeApp, JobSources, ConfigSources
from functualize.app import classic, twelve_factor, env_only, remote_first

# Plugin authors — extend the framework
from functualize.plugin import EventBus, JobProvider, AdapterPlugin

# Shared types
from functualize.types import JobResult, JobDescriptor, FieldDescriptor

# Testing utilities
from functualize.testing import TestRunContext, CapturingLog, MockInvoke
```

Anything prefixed with `_` (e.g., `functualize._engine`) is internal implementation — don't import from those packages.

---

## What's Next

- [Configuration System](../guides/configuration.md) — Layered config resolution in detail
- [Jobs & Auto-Discovery](../guides/jobs-discovery.md) — How modules become CLI commands
- [Job Configuration](../guides/job-config.md) — Defining typed parameters with Pydantic
- [RunContext](../guides/run-context.md) — Logging, invocation, workflow tracking, DI
- [Plugins](../guides/plugins.md) — Extending functualize with custom providers and adapters
