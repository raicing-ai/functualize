# Discovery (Internal)

The job discovery system lives in the internal `functualize._discovery` package. End users interact with discovery through:

- **`functualize.types.JobDescriptor`** — the public type representing a discovered job
- **`functualize.app.JobSources`** — the public configuration for discovery
- **`func` CLI** — handles discovery automatically via the `FunctualizeApp` constructor

## Public API

```python
from functualize.types import JobDescriptor, FieldDescriptor
from functualize.app import JobSources
```

## `JobDescriptor`

**Location:** `functualize.types` (defined in `functualize._types.descriptors`)

A frozen dataclass representing a registered job's full metadata. Accessible via `app.get_jobs()`, `app.get_job(name)`, or `rc.get_job_schema(name)`.

### Primary fields

| Field | Type | Description |
|---|---|---|
| `name` | `str` | The unique job name. |
| `group` | `str \| None` | Command group (from `JOB_GROUP`). |
| `function` | `Callable \| None` | The job function (None for cache-only descriptors). |
| `docstring` | `str \| None` | The job function's docstring. |
| `parameters` | `list[FieldDescriptor]` | Structured parameter schema for the job's configuration fields. |
| `source` | `str` | Module path or file path. |
| `metadata` | `dict[str, Any]` | Plugin extension data (JSON-serializable dict). Consumer-facing description/tags/category live on `declaration`. |
| `declaration` | `JobDeclaration \| None` | Frozen declaration from `@job(...)` — carries deps, cache, guards, exec, matrix. |

### Internal fields (for tooling/CLI/caching)

| Field | Type | Description |
|---|---|---|
| `module_path` | `str` | Dotted module path for lazy import. |
| `source_file` | `str` | Filesystem path to source file (for cache invalidation). |
| `source_mtime` | `float` | Last modification time of source file. |
| `content_hash` | `str` | Content hash for cache invalidation. |
| `config_fields` | `list[FieldDescriptor]` | Alias for `parameters` (backward-compatible). |
| `dependencies` | `dict[str, str]` | First-level in-project imports. |
| `requires_tty` | `bool` | True if the signature requires a `tty: TTY` capability. |
| `optional_tty` | `bool` | True if the signature declares `tty: TTY \| None`. |
| `uses_live` | `bool` | True if the signature declares a `live: Live` capability. |
| `suppress_live` | `tuple[str, ...]` | Ambient live constructs this job opts out of. |
| `decorators` | `tuple[str, ...]` | Decorator root names from AST extraction. |
| `surface_hint` | `str \| None` | Per-job render-surface preference. |
| `workflow` | `WorkflowShape \| None` | Cache-serializable topology from `@workflow(...)`. |
| `from_job_deps` | `tuple[str, ...]` | Names of jobs consumed via `FromJob` parameters. |
| `python_name` | `str` | Original Python function name. |

## `FieldDescriptor`

**Location:** `functualize.types`

A frozen dataclass providing structured parameter schema for a job's configuration fields.

### Fields

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Parameter name. |
| `type_annotation` | `str` | Type as a string (e.g., `"str"`, `"int"`, `"list[str]"`). |
| `default` | `Any \| None` | Default value, if any. |
| `description` | `str` | Human-readable description. |
| `required` | `bool` | Whether the parameter must be provided. |
| `choices` | `list[str] \| None` | Valid choices for Enum types. |
| `positional` | `bool` | True if marked with `Arg()` — a positional CLI argument. |
| `short_flag` | `str \| None` | Short flag alias (e.g., `-t`) from `Option()` marker. |
| `is_stdin` | `bool` | True if marked with `Stdin()` — reads from a pipe. |
| `stdin_flag` | `str \| None` | Explicit flag name from `Stdin(flag=...)`. |

## `@job` Decorator

**Location:** `functualize.job`

Attaches a `JobDeclaration` to a job function for metadata, dependencies, caching, guards, and execution control.

```python
from functualize.job.decorators import job, Deps, Fingerprint

@job(
    group="infra",
    extra_description="Deploy the application to production",
    tags=["deploy", "production"],
    deps=Deps("lint", "test"),
    cache=Fingerprint(sources=["src/**/*.py"]),
)
def deploy(rc):
    ...
```

!!! note "Replaces @job_metadata"
    The `@job_metadata` decorator has been removed. Use `@job` for all metadata,
    dependency, caching, guard, and execution declarations.

## Internal Location

The implementation details are in `functualize._discovery/`:

- `_discovery/providers.py` — DirectoryScanProvider, StaticProvider, EntryPointProvider (CachedDirectoryScanProvider lives in `_discovery/cached_provider.py`)
- `_discovery/transforms.py` — Namespace, GroupByModule, NamespaceTransform (child composition)
- `_discovery/cached_provider.py` — Cache persistence + sync
- `_discovery/hierarchy.py` — Child project definitions
- `_discovery/pipeline.py` — ResolutionPipeline

!!! warning "Internal API"
    Modules under `functualize._discovery` are implementation details. Import from `functualize.types` or `functualize.app` instead.
