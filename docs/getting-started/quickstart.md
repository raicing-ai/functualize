# Quickstart

This guide walks you through functualize's three modes of use — from a single file to a full framework project. Start simple, graduate when you need more.

!!! note "Prerequisites"
    Python 3.11+ and functualize installed. See [Installation](installation.md) if you haven't set up yet.

---

## Mode 1: Single-File Script

The fastest way to start. One file, one job, zero configuration.

### Create a job file

```python title="jobs.py"
from functualize.job import RunContext, Log

def deploy(rc: RunContext):
    """Deploy the application to production."""
    rc.log("Starting deployment...")
    rc.log("Deployment complete")
```

### Run it

```bash
func jobs.py deploy
```

That's it. No `pyproject.toml`, no project structure, no registration. Functualize imports the file, finds `deploy`, and runs it with a full `RunContext`.

### List available functions

If your file has multiple jobs, run without a function name to see what's available:

```python title="jobs.py"
from functualize.job import RunContext, Log

def deploy(rc: RunContext):
    """Deploy the application to production."""
    rc.log("Deploying...")

def rollback(rc: RunContext):
    """Roll back the last deployment."""
    rc.log("Rolling back...")

def healthcheck(rc: RunContext):
    """Check service health."""
    rc.log("All services healthy")
```

```bash
func jobs.py
```

```
Available functions in jobs.py:
  deploy       — Deploy the application to production.
  healthcheck  — Check service health.
  rollback     — Roll back the last deployment.
```

```bash
func jobs.py healthcheck
```

---

## Mode 2: Project Directory with Auto-Discovery

When you have multiple job files, organize them in a `jobs/` directory. Functualize auto-discovers everything inside it.

### Create the structure

```
myproject/
├── jobs/
│   ├── deploy.py
│   ├── migrate.py
│   └── healthcheck.py
└── pyproject.toml        # optional at this stage
```

```python title="jobs/deploy.py"
from functualize.job import RunContext, Log

def run(rc: RunContext):
    """Deploy the application."""
    rc.log("Deploying to production...")
```

```python title="jobs/migrate.py"
from functualize.job import RunContext, Log

def run(rc: RunContext):
    """Run database migrations."""
    rc.log("Running migrations...")
```

### Run from the project directory

```bash
cd myproject
func deploy
func migrate
```

Functualize scans the `jobs/` directory, discovers modules, and registers each as a CLI command. The function name defaults to `run` when not specified.

### Scaffold a new job

Instead of creating files manually, use the scaffold command:

```bash
func builtin scaffold add job backup
```

This creates `jobs/backup.py` with the correct template and imports.

---

## Mode 3: Full FunctualizeApp Project

For production applications that need custom configuration, plugins, and a dedicated CLI command, scaffold a complete project.

### Scaffold a new project

```bash
func builtin scaffold init my-platform
cd my-platform
```

This generates:

```
my-platform/
├── pyproject.toml
├── config.base.toml
└── src/
    └── my_platform/
        ├── __init__.py
        ├── main.py
        └── jobs/
            ├── __init__.py
            └── sample_job.py
```

### Install and run

=== "uv (recommended)"

    ```bash
    uv sync
    uv run my-platform --help
    uv run my-platform sample run --target hello-world
    ```

=== "pip"

    ```bash
    pip install -e .
    my-platform --help
    my-platform sample run --target hello-world
    ```

### The entry point

The generated `main.py` wires everything together:

```python title="src/my_platform/main.py"
from functualize.app import FunctualizeApp, JobSources, ConfigSources, classic

app = FunctualizeApp(
    name="my-platform",
    job_sources=JobSources(directories=["my_platform.jobs"]),
    config_sources=classic(),
)

def run() -> None:
    """Console script entry point."""
    app.run()
```

The `pyproject.toml` maps your project name to this entry point:

```toml title="pyproject.toml"
[project.scripts]
my-platform = "my_platform.main:run"
```

### Use presets for production deployments

Swap the configuration strategy based on your deployment target:

```python title="src/my_platform/main.py"
from functualize.app import FunctualizeApp, JobSources, ConfigSources, twelve_factor

app = FunctualizeApp(
    name="my-platform",
    job_sources=JobSources(directories=["my_platform.jobs"]),
    config_sources=twelve_factor(dotenv=True),  # Env vars only, no config files
)
```

| Preset | Strategy | Best for |
|--------|----------|----------|
| `classic()` | CLI → Env → Config files → Defaults | Local dev, desktop tools |
| `twelve_factor()` | CLI → Env → Defaults (no files) | Docker, Kubernetes, Heroku |
| `env_only()` | CLI → Env → Defaults (dotenv on) | Serverless, minimal setups |
| `remote_first()` | CLI → Remote → Env → Files → Defaults | Vault, AWS Secrets Manager |

You can also write your own preset — any function returning `ConfigSources` works:

```python
from functualize.app import ConfigSources

def my_custom_preset(**kwargs) -> ConfigSources:
    return ConfigSources(dotenv=True, file_pattern=r"^settings\.\w+\.toml$")
```

---

## Exposing a Global CLI Command (uv project)

When you scaffold a project with `func builtin scaffold init`, the `pyproject.toml` already includes a `[project.scripts]` entry that makes your app available as a named command after installation.

Here's how it works:

```toml title="pyproject.toml"
[project.scripts]
my-platform = "my_platform.main:run"
```

This tells Python's packaging system: "when this package is installed, create a `my-platform` executable that calls `my_platform.main:run()`."

After `uv sync` or `pip install -e .`, the command is available globally in your environment:

```bash
my-platform deploy --target production
my-platform --help
```

### Adding it to an existing uv project

If you already have a `pyproject.toml`, add the entry point manually:

```toml
[project.scripts]
my-cli = "myapp.main:run"
```

Where `myapp/main.py` contains:

```python
from functualize.app import FunctualizeApp, JobSources

app = FunctualizeApp(
    name="my-cli",
    job_sources=JobSources(directories=["myapp.jobs"]),
)

def run() -> None:
    app.run()
```

Then reinstall:

```bash
uv sync   # or: pip install -e .
my-cli --help
```

---

## Scaffolding Commands

Functualize provides scaffolding for common operations:

| Command | What it does |
|---------|-------------|
| `func builtin scaffold init <name>` | Create a new project with full structure |
| `func builtin scaffold add job <name>` | Add a job file to the current project (or CWD in bare mode) |
| `func builtin scaffold add plugin <name>` | Add a plugin file |
| `func builtin scaffold add tui-screen <name>` | Add a TUI screen component |

### Scaffold a new project

```bash
func builtin scaffold init my-tool
func builtin scaffold init my-tool --template simple
```

### Add a job to an existing project

```bash
cd my-tool
func builtin scaffold add job deploy
# Creates src/my_tool/jobs/deploy.py
```

### Add a job in bare mode (no project)

When you're outside a project context, scaffold creates a standalone job file:

```bash
mkdir scripts && cd scripts
func builtin scaffold add job backup
# Creates backup.py in the current directory
```

---

## What's Next

| Topic | Guide |
|-------|-------|
| Understand the generated project layout | [Project Structure](project-structure.md) |
| Configure jobs with typed parameters | [Job Configuration](../guides/job-config.md) |
| Set up layered config resolution | [Configuration System](../guides/configuration.md) |
| Add more jobs and understand discovery | [Jobs & Auto-Discovery](../guides/jobs-discovery.md) |
| Extend with plugins | [Plugins Guide](../guides/plugins.md) |
| Choose a usage mode | [Modes Guide](../guides/modes.md) |
