# Jobs and Auto-Discovery

Functualize automatically discovers job functions from Python modules and registers them as CLI commands. This guide explains how the discovery mechanism works, what makes a function eligible for registration, and how to organize jobs into grouped sub-commands.

## How auto-discovery works

When you create a `FunctualizeApp`, the `job_sources` parameter tells the framework where to look for job modules:

```python
from functualize.app import FunctualizeApp, JobSources

app = FunctualizeApp(
    name="my-app",
    job_sources=JobSources(directories=["src/my_app/jobs"]),  # (1)!
)
```

1. You can pass multiple directories. Each one is scanned independently.

The discovery process uses Python's `pkgutil.iter_modules` to scan each directory. For every Python module found (`.py` files), the framework:

1. **Skips sub-packages** — only top-level modules in the directory are scanned, not nested packages
2. **Imports the module** — loads it so functions and module-level variables can be inspected
3. **Inspects all attributes** — checks each public attribute against the eligibility criteria
4. **Registers qualifying functions** — adds them as Click CLI commands

!!! info "Import failures are non-fatal"
    If a module fails to import (syntax error, missing dependency, etc.), a warning is logged and discovery continues with the remaining modules. Your application won't crash because of one broken job file.

## Job names are canonical

A job's name is derived from its function name and **normalized to
lowercase-hyphenated form** — the spelling command-line tools conventionally
use, and the one Click itself defaults to:

| You write | The job is | You run |
|---|---|---|
| `def data_sync()` | `data-sync` | `func data-sync` |
| `def buildWheel()` | `build-wheel` | `func build-wheel` |
| `JOB_GROUP = "data_ops"` + `def run_etl()` | `data-ops.run-etl` | `func data-ops run-etl` |

Python identifiers cannot contain hyphens and command names conventionally do,
so without a single canonical form the same job has two spellings and every
consumer picks one.

**Typing the Python spelling still works.** `func data_sync`,
`rc.invoke("data_sync")` and `Deps("data_sync")` all reach `data-sync`. That is
normalization, not aliasing: there is one name, and you cannot miss it by
writing it the way Python spells it. `func --help` always shows the canonical
form.

Two places keep the underscored spelling for good reasons:

- **Environment variables** — `DATA_SYNC_BATCH_SIZE`, because no shell can
  export a name containing a hyphen.
- **Config sections** — `[data_sync]` and `[data-sync]` are both read, so an
  existing config file keeps working.

Two functions whose names normalize to the same job (`build_wheel` and
`buildWheel`) are rejected at registration rather than one silently replacing
the other.

## Function eligibility criteria

Not every function in a job module becomes a CLI command. A function is registered only if **all** of the following are true:

| Criterion | Description |
|-----------|-------------|
| **Callable** | The attribute must be callable |
| **Is a function** | Must be an actual function (`inspect.isfunction`), not a class or other callable object |
| **No underscore prefix** | The name must not start with `_` — underscore-prefixed functions are treated as private |
| **Defined in the module** | The function must be defined in the scanned module, not imported from elsewhere |

The "defined in module" check prevents imported helper functions from accidentally becoming CLI commands. Only functions whose source module matches the scanned module are registered.

```python
# jobs/data_tasks.py

from some_library import helper_function  # (1)!

JOB_NAME = "data"


def export():  # (2)!
    """Export data to CSV."""
    print("Exporting...")


def _validate_row(row):  # (3)!
    """Internal validation helper."""
    return row is not None


class DataProcessor:  # (4)!
    """Not registered — it's a class, not a function."""
    pass
```

1. `helper_function` is **not** registered — it's imported from another module.
2. `export` **is** registered — it's a public function defined in this module.
3. `_validate_row` is **not** registered — it starts with an underscore.
4. `DataProcessor` is **not** registered — it's a class, not a function.

## JOB_NAME and sub-command grouping

The `JOB_NAME` module-level variable controls how functions are organized in the CLI hierarchy.

### With JOB_NAME (grouped)

When a module defines `JOB_NAME`, all qualifying functions in that module are registered under a Click sub-command group named after the `JOB_NAME` value:

```python
# jobs/reporting.py

JOB_NAME = "report"  # (1)!


def generate(format: str = "pdf"):
    """Generate a report."""
    print(f"Generating {format} report...")


def send(recipient: str = "team@example.com"):
    """Send the latest report."""
    print(f"Sending report to {recipient}...")
```

1. All public functions in this module become sub-commands under `my-app report`.

This produces the following CLI structure:

```
my-app report generate --format pdf
my-app report send --recipient team@example.com
```

### Without JOB_NAME (top-level)

When a module does **not** define `JOB_NAME`, its qualifying functions are registered as top-level commands on the main application:

```python
# jobs/health.py
# No JOB_NAME defined


def ping():
    """Check if the service is alive."""
    print("pong")
```

This registers `ping` directly on the app:

```
my-app ping
```

## Multiple modules sharing the same JOB_NAME

Multiple job modules can share the same `JOB_NAME` value. Their functions are all registered under the same sub-command group:

```python
# jobs/data_export.py
JOB_NAME = "data"

def export():
    """Export data to file."""
    ...
```

```python
# jobs/data_import.py
JOB_NAME = "data"

def load():
    """Load data from file."""
    ...
```

Both `export` and `load` appear under the `data` sub-command group:

```
my-app data export
my-app data load
```

!!! tip "Organizing large projects"
    Splitting related functions across multiple files while sharing a `JOB_NAME` keeps individual modules focused and manageable, while presenting a unified command group to users.

## Duplicate command detection

When a command name is already registered at the same level (either within the same group or at the top level), the duplicate is **skipped** and a warning is logged:

```
WARNING - Duplicate command 'export' (already registered from 'data_export'). Skipping duplicate from 'data_backup'.
```

This can happen when:

- Two modules with the same `JOB_NAME` both define a function with the same name
- Two modules without `JOB_NAME` both define a function with the same name

The first module discovered (based on filesystem ordering from `pkgutil.iter_modules`) wins. The duplicate is silently skipped after the warning.

!!! warning "Avoid relying on discovery order"
    The order in which modules are discovered depends on the filesystem and `pkgutil.iter_modules` behavior. If you have naming conflicts, rename one of the functions rather than relying on which one gets registered first.

## Minimal job file example

Here's a complete, minimal job file with annotations showing which elements are required for discovery:

```python title="jobs/sample_job.py" hl_lines="3 6"
"""Sample job module demonstrating auto-discovery requirements."""

JOB_NAME = "sample"  # (1)!


def run(target: str, dry_run: bool = False):  # (2)!
    """Execute the sample job.  # (3)!

    Args:
        target: The target resource to process.
        dry_run: If True, simulate without making changes.
    """
    print(f"Starting sample job with target: {target}")
    if dry_run:
        print("Dry run mode — skipping actual processing")
    print("Job completed successfully")
```

1. **`JOB_NAME`** — Groups this module's functions under the `sample` sub-command. Remove this line to register functions at the top level instead.
2. **Public function** — Must be a function (not a class), must not start with `_`, and must be defined in this module. Parameters with type annotations become Click CLI options automatically.
3. **Docstring** — Used as the command's help text in `--help` output.

This produces:

```
$ my-app sample run --help
Usage: my-app sample run [OPTIONS]

  Execute the sample job.

Options:
  --target TEXT       The target resource to process. [required]
  --dry-run / --no-dry-run
                     If True, simulate without making changes. [default: no-dry-run]
  --help             Show this message and exit.
```

## Job Metadata Decorator

The `@job_metadata` decorator attaches structured metadata to job functions. This metadata is available via `JobDescriptor` and useful for AI orchestrators, schema exporters, and documentation generators.

```python
from functualize.job import job_metadata
from functualize.job import RunContext

JOB_NAME = "deploy"


@job_metadata(
    ai_description="Deploy the application to the specified environment",
    category="deployment",
    examples=["deploy --env production", "deploy --env staging --dry-run"],
    tags=["deploy", "infrastructure", "production"],
)
def run(rc: RunContext) -> None:
    """Deploy the application."""
    ...
```

### Parameters

| Parameter | Type | Constraint | Description |
|---|---|---|---|
| `ai_description` | `str \| None` | Max 500 characters | Description optimized for AI/LLM consumption |
| `category` | `str \| None` | Max 50 characters | Grouping category for job organization |
| `examples` | `list[str] \| None` | Max 10 items, each max 200 chars | Usage examples |
| `tags` | `list[str] \| None` | Max 20 items, each max 50 chars | Searchable tags |

The metadata is stored as a `JobMetadataAnnotation` on the function's `__functualize_metadata__` attribute and incorporated into the `JobDescriptor` during registration.

!!! info "Composable with other decorators"
    `@job_metadata` can be combined with any other decorators in any order. It does not wrap the function — it only attaches an attribute.

---

## JobDescriptor Retention

After registration, every job's `JobDescriptor` is retained and accessible for runtime introspection:

```python
# From application code
descriptors = app.job_registry.get_descriptors()  # All registered descriptors

descriptor = app.job_registry.get_descriptor("data-sync")  # Single descriptor by name
print(descriptor.name)           # "data-sync"
print(descriptor.group)          # "data" or None
print(descriptor.config_schema)  # Pydantic model class or None
print(descriptor.metadata)       # JobMetadataAnnotation or None
```

From within a job, use `rc.get_job_schema(job_name)` to introspect sibling jobs:

```python
def orchestrator(rc: RunContext) -> None:
    schema = rc.get_job_schema("validate-data")
    rc.log(f"Job has {len(schema.config_schema.model_fields)} config fields")
```

This enables patterns like dynamic orchestration, job discovery UIs, and AI-driven job selection.

---

## Next steps

- **[JobConfig with Pydantic](job-config.md)** — Add typed, validated configuration to your jobs with automatic CLI option generation
- **[RunContext Lifecycle](run-context.md)** — Inject runtime context with lifecycle hooks into your job functions
- **[Configuration System](configuration.md)** — Understand how config values are resolved from multiple sources
