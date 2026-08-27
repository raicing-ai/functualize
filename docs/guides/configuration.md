# Configuration System

Functualize uses a layered INI-based configuration system that resolves values from multiple sources with a clear priority order. This guide covers how config files are discovered, how values are resolved, and how to use per-job configuration sections with Pydantic models.

## Overview

The configuration system provides:

- **Preset factory functions** — named configuration strategies (`classic`, `twelve_factor`, `env_only`, `remote_first`)
- **Upward directory search** for config files starting from the current working directory
- **Base + environment overlay** pattern using INI files
- **Environment variable precedence** over file-based config
- **Per-job sections** that map directly to `JobConfig` Pydantic models
- **Tracking** of which settings were accessed and where values came from

## Configuration Presets

Functualize provides preset factory functions that return a `ConfigSources` instance configured for common deployment scenarios:

```python
from functualize.app import FunctualizeApp, JobSources, classic, twelve_factor, env_only, remote_first

# Classic: CLI → Env → Files (upward search) → Defaults (the default behavior)
app = FunctualizeApp(name="myapp", config_sources=classic())

# Twelve-factor: CLI → Env → Defaults (no file discovery)
app = FunctualizeApp(name="myapp", config_sources=twelve_factor())

# Env-only: CLI → Env → Defaults (minimal, with optional dotenv)
app = FunctualizeApp(name="myapp", config_sources=env_only(dotenv=True))

# Remote-first: CLI → Remote → Env → Files → Defaults
app = FunctualizeApp(name="myapp", config_sources=remote_first())
```

When no `config_sources` is specified, the default behavior is identical to `classic()`.

You can also create custom presets — any function returning a `ConfigSources` instance works:

```python
from functualize.app import ConfigSources

def my_custom_preset(**kwargs) -> ConfigSources:
    return ConfigSources(dotenv=True, file_pattern=r"^app_config\.(\w+)\.toml$")
```

## Config Directory Discovery

When a `FunctualizeApp` is instantiated, it discovers the config directory by searching upward from the current working directory for files matching a regex pattern.

```python
from functualize.app import FunctualizeApp, JobSources

app = FunctualizeApp(
    name="myapp",
    job_sources=JobSources(directories=["jobs"]),
)
```

The `name` parameter serves as the fallback identifier. If no config files are found during the upward search, Functualize falls back to `~/.config/<name>/` (for example `~/.config/myapp/`). This XDG-style path is used on every platform — `discover_config_path` returns `Path.home() / ".config" / name` directly, without any OS-specific branch.

### Upward Directory Walk

The discovery algorithm works as follows:

1. Start at the current working directory (`os.getcwd()`)
2. List files in the current directory and match against the config file regex
3. If matches are found, use that directory as the config path
4. If no matches, move to the parent directory and repeat
5. Stop at the user's home directory (`~`) or the filesystem root (`/`), whichever is reached first
6. If no matches are found anywhere, fall back to `~/.config/<name>/`

```mermaid
flowchart TD
    A[Start at CWD] --> B{Files match config regex?}
    B -->|Yes| C[Use this directory as config path]
    B -->|No| D{Reached home dir or root?}
    D -->|No| E[Move to parent directory]
    E --> B
    D -->|Yes| F[Fall back to ~/.config/name]
```

!!! info "CLI Override"
    The `--config-directory` global CLI option overrides the discovered config path entirely. When provided, no upward search is performed.

## Config File Pattern

By default, Functualize looks for files matching the regex pattern:

```
^config\.(\w+)\.(\w+)$
```

This matches filenames like `config.base.toml`, `config.dev.toml`, `config.prod.toml`, etc.

### Custom Regex Pattern

You can customize the pattern via the `file_pattern` in `ConfigSources`:

```python
from functualize.app import FunctualizeApp, JobSources, ConfigSources

app = FunctualizeApp(
    name="myapp",
    job_sources=JobSources(directories=["jobs"]),
    config_sources=ConfigSources(file_pattern=r"^settings\.(\w+)\.toml$"),  # matches settings.base.toml, etc.
)
```

The regex is applied to filenames (not full paths), both when anchoring the config directory during the upward walk and when the file source selects which files to parse. Files still need an extension that a registered format provider handles — `.toml` alone by default. A plugin can register more by calling `app.config_registry.register_format_provider(...)`, or a package can declare one in the `functualize.format_providers` entry-point group.

## Base Config and Environment Overlays

Functualize loads configuration in two layers:

1. **Base config** — `config.base.toml` (always loaded first)
2. **Environment overlay** — `config.{env}.toml` (merged on top of base)

The environment name comes from the first of these that is set to a valid name, defaulting to `"DEV"`:

1. `FUNCTUALIZE_ENV`
2. `ENVIRONMENT`
3. `ENV`

A value that is blank, or that isn't a valid filename segment (`[A-Za-z0-9_-]+`), is skipped rather than being an error — the next variable is tried. This matters for `ENV` in particular: POSIX `sh`/`ksh` set it to the path of a startup file, which is not an environment name.

Matching is **case-insensitive**, comparing the environment name against the file's slot. The filename is not lowercased, so `config.Prod.toml` is selectable too.

| Environment value | Overlay file loaded |
|---------------------|---------------------|
| *(not set)* | `config.dev.toml` |
| `DEV` | `config.dev.toml` |
| `PROD` | `config.prod.toml` |
| `STAGING` | `config.staging.toml` |

A file naming any *other* environment is discovered but never merged. `func`'s inline TUI lists it as `○ inactive`, so a file that plainly exists but isn't taking effect is visible rather than mysterious.

!!! note
    The overlay is deep-merged on top of the base config through the file's registered `FormatProvider` — the mechanism is format-agnostic rather than tied to any one parser, so a format a plugin registers behaves the same way. Keys in the overlay override the same keys in the base file; keys only present in the base file are preserved.

!!! note "Precedence across directories"
    When config files exist in several directories (project, parents, global), the **nearest directory wins overall**, and within a single directory the overlay beats that directory's base. A project's `config.base.toml` therefore still outranks a global `config.prod.toml` — the ladder is about *whose* config it is, not which environment it names.

## Resolution Priority

Configuration values are resolved with the following priority (highest to lowest):

```mermaid
flowchart TD
    A[Request config value] --> B{Environment variable set?}
    B -->|Yes| C[Use env var value]
    B -->|No| D{Key in env-specific config?}
    D -->|Yes| E[Use env config value]
    D -->|No| F{Key in base config?}
    F -->|Yes| G[Use base config value]
    F -->|No| H{Default provided?}
    H -->|Yes| I[Use default value]
    H -->|No| J[Return None or raise error]
```

### Environment Variable Convention

Environment variables follow the `SECTION_KEY` naming convention — both the section name and key name are uppercased and joined with an underscore.

| Section | Key | Environment Variable |
|---------|-----|---------------------|
| `server` | `api_url` | `SERVER_API_URL` |
| `database` | `host` | `DATABASE_HOST` |
| `general` | `debug` | `GENERAL_DEBUG` |

When the section is an empty string, only the key name (uppercased) is used as the environment variable name.

## Environment Variables and `.env` Files

Functualize resolves environment variables from `os.environ` at config resolution time. A `.env` file can populate `os.environ` with additional values in two ways: the `--dotenv-file` CLI flag, or the app's `ConfigSources.dotenv` / `dotenv_path` settings, which boot honors before building the resolution chain.

### How `.env` Loading Works

```bash
# Explicit: load .env before config resolution runs
myapp --dotenv-file .env data-sync run

# No flag: loading depends on the app's ConfigSources (see below)
myapp data-sync run
```

When `--dotenv-file` is passed, the CLI adapter calls `python-dotenv`'s `load_dotenv()` in the root group callback — **before** any subcommand executes and before config resolution runs. This means `.env` values are available in `os.environ` by the time the resolution chain reads them.

Independently of the flag, application boot loads a `.env` file when `ConfigSources.dotenv` is true (the dataclass default) or `ConfigSources.dotenv_path` names a file — at the very start of both boot paths, so `EnvSource` sees the values. Loading always uses `override=False`: values already in the environment win.

```python
from functualize.app import FunctualizeApp, ConfigSources
from functualize.app.presets import env_only, twelve_factor

app = FunctualizeApp("myapp")                                    # dotenv=True default: loads ./.env if present
app = FunctualizeApp("myapp", config_sources=ConfigSources(dotenv=False))  # never loads
app = FunctualizeApp("myapp", config_sources=env_only(dotenv_path=".env.local"))  # explicit path
app = FunctualizeApp("myapp", config_sources=twelve_factor())   # dotenv=False default: pure 12-factor
```

### How `.env` Affects Config File Selection

Because `.env` is loaded into `os.environ` before boot runs, it can influence **which config files** get loaded. The `ENVIRONMENT` variable (read from `os.environ` during boot) controls the environment overlay:

```bash
# .env file
ENVIRONMENT=prod
DATA_SYNC_API_URL=https://api.prod.example.com
```

```bash
# This loads .env → sets ENVIRONMENT=prod → boot loads config.base.toml + config.prod.toml
myapp --dotenv-file .env data-sync run
```

Without `--dotenv-file`, the `ENVIRONMENT` variable must be set in the shell:

```bash
# Shell sets ENVIRONMENT directly
ENVIRONMENT=prod myapp data-sync run
```

In both cases, the config system loads `config.base.toml` first, then merges `config.prod.toml` on top (values in the overlay override the base).

### Precedence: Shell vs `.env`

Python-dotenv does **not** override existing shell environment variables by default. This means:

| Source | Priority | Example |
|--------|----------|---------|
| CLI flags | Highest | `--batch-size 2000` |
| Shell environment variables | High | `export DATA_SYNC_BATCH_SIZE=500` |
| `.env` file values (via `--dotenv-file`) | Medium | `DATA_SYNC_BATCH_SIZE=100` in `.env` |
| Config files (INI/TOML) | Low | `batch_size = 50` in `config.base.toml` |
| Pydantic model defaults | Lowest | `Field(default=25)` |

If `DATA_SYNC_BATCH_SIZE=500` is already set in your shell, a `.env` file containing `DATA_SYNC_BATCH_SIZE=100` will **not** override it. The shell value wins.

This applies to the `ENVIRONMENT` variable too — if your shell has `export ENVIRONMENT=staging` and your `.env` has `ENVIRONMENT=prod`, the staging overlay is used because shell takes precedence.

### Boot-Time `.env` Loading Rules

Boot's `.env` handling is driven entirely by `ConfigSources`:

- `dotenv=True` (the `ConfigSources` default and the `env_only()` preset default): boot loads `./.env` from the current working directory if it exists — missing file is not an error.
- `dotenv_path="..."`: boot loads that specific file; a missing file logs a warning and skips.
- `dotenv=False` (the `twelve_factor()` preset default): boot never calls `load_dotenv()`.
- Loading happens at the very start of boot (both the standard and static paths), before the resolution chain is built.
- Only the current directory is checked — there is **no upward directory scan**, so a `.env` forgotten in a parent directory is never silently picked up.

For the `func` CLI, the resolved CLI config (`dotenv` / `dotenv_path` from `pyproject.toml` `[tool.functualize]`, `FUNCTUALIZE_DOTENV`, `FUNCTUALIZE_DOTENV_PATH`) controls loading, with `--dotenv-file` / `--no-dotenv` as overrides. The CLI default is `dotenv = false` — opt in per project.

!!! info "Disabling for reproducibility"
    Automatic `.env` loading can cause differences between environments. For CI or production, use `twelve_factor()` (or `ConfigSources(dotenv=False)`, or `--no-dotenv` on the CLI) so environment variables come only from the orchestrator.

### Practical Patterns

**Local development with `.env`:**

```bash
# Create a .env for local secrets
echo "DATA_SYNC_API_KEY=dev-secret-123" > .env
echo "DATA_SYNC_API_URL=http://localhost:8080" >> .env

# Run with dotenv
myapp --dotenv-file .env data-sync run
```

**CI/Docker (no `.env` needed):**

```bash
# Real env vars are set by the orchestrator
export DATA_SYNC_API_KEY=$VAULT_SECRET
export DATA_SYNC_API_URL=https://api.prod.example.com
myapp data-sync run
```

**Verifying what's loaded:**

```bash
# show-info displays whether a dotenv file was loaded and its contents
myapp --dotenv-file .env show-info
```

### Introspection with `show-info`

The `show-info` command reports the current dotenv status:

- If `--dotenv-file` was passed, it displays the file path and its key-value contents
- If no dotenv file was loaded, it prints a notice: "No dotenv file loaded"
- Use `--show-env-vars` to see the full `os.environ` snapshot (including any values injected from `.env`)

## Per-Job Config Sections

Each job can have its own config section where the section name matches the `JOB_NAME` value defined in the job module. When a job uses a `JobConfig` Pydantic model, fields are resolved from the matching section.

```toml
# config.base.toml

[general]
debug = false
log_format = "json"

[data_sync]
api_url = "https://api.example.com"
batch_size = 100
timeout = 30

[report_gen]
output_dir = "./reports"
format = "pdf"
```

In this example, a job with `JOB_NAME = "data_sync"` reads from the `[data_sync]` section.

## JobConfig Field Resolution

When a job function declares a `JobConfig` Pydantic model parameter, each field is resolved with this precedence:

1. **CLI argument** — explicitly passed via the command line (e.g., `--batch-size 200`)
2. **Environment variable** — `JOBNAME_FIELDNAME` uppercased (e.g., `DATA_SYNC_BATCH_SIZE`)
3. **Config file section** — the `[job_name]` section in the loaded config files
4. **Model default** — the default value defined on the Pydantic field

```mermaid
flowchart TD
    A[Resolve JobConfig field] --> B{CLI argument provided?}
    B -->|Yes| C[Use CLI value]
    B -->|No| D{Env var JOBNAME_FIELDNAME set?}
    D -->|Yes| E[Use env var value]
    D -->|No| F{Key in config section?}
    F -->|Yes| G[Use config file value]
    F -->|No| H{Field has default?}
    H -->|Yes| I[Use model default]
    H -->|No| J[Pydantic ValidationError]
```

!!! warning
    If a required field (no default value) has no value from any source, an interactive surface asks for it. Off one — CI, a pipe, a cron job — Pydantic's `ValidationError` is reported with field-level details, the config files that were actually read, and the environment variable that would set the field.

## Credentials

A credential is an ordinary config field that you mark as secret. Nothing else
about it changes: it resolves through the same ladder, in the same section, under
the same environment variable name.

```python title="jobs/sync.py"
from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.types import Secret


class SyncConfig(BaseModel):
    api_url: str = Field(default="https://api.example.com")
    credential: Secret[str] = Field(description="API token")


def sync(config: SyncConfig, rc: RunContext) -> None:
    rc.log(f"connecting to {config.api_url}")
    client.authenticate(config.credential.get_secret_value())
```

`Secret[str]` is the declaration. It is a real type: it validates from a plain
string, refuses to render its value in `str()`, `repr()`, logs or `model_dump()`,
and yields the real value only through `.get_secret_value()`. A field that must stay a
plain `str` for some other reason can carry the marker instead, and is treated
identically everywhere:

```python
credential: str = Field(default="", json_schema_extra={"secret": True})
```

Both markers answer one question — *is this field a secret?* — asked in one
place. Every surface that renders configuration asks it: `func builtin info
--job`, `func builtin env`, the inline TUI's config table and source-chain
view, and the bar while you type into the field. None of them will show you the
value.

!!! warning "Detection is by declaration, never by name"
    A field called `sort_key` is not a secret, and a field called `x` is one if
    you declared it so. Name matching was tried and removed: it masked the wrong
    fields and, far worse, left real credentials in cleartext whenever the name
    did not match a pattern.

### Finding out what a job needs

```console
$ func builtin env sync
export SYNC_API_URL='https://api.example.com'   # source: config.base.toml
export SYNC_CREDENTIAL='•••'                    # source: env
```

Unset fields come back commented, so the output doubles as a `.env` skeleton and
"is the credential configured?" has a visible answer:

```console
$ func builtin env strict
# STRICT_TOKEN=  # REQUIRED — not set
```

`func builtin env <job> -- <command>` runs a command with the resolved values in
its environment instead of printing them. Secret values are omitted from both
forms unless you pass `--include-secrets`, so the default output is safe to
paste into a bug report.

### Where credentials come from

Set them in the environment, or in a `.env` file that is not committed. **Config
files have no vocabulary for naming a secret's location, and none is planned.**

A `${env:VAR}` interpolation syntax was considered and rejected. It reads as
indirection but resolves to the same environment variable the field would have
read anyway — so it adds a syntax, a parse step and a failure mode, and buys
nothing except the appearance of a secrets feature. That appearance is the
danger: it invites putting the real value there "just for now". A field that
resolves from the environment does so because that is the ladder, not because a
config file pointed at it.

There is no `[secrets]` section. A credential is a field in its job's own
section, marked secret — one concept, not two.

## Complete Example

Here's a full example showing a base config, environment overlay, and a `JobConfig` model that reads from the config system.

### Base Config

```toml title="config.base.toml"
[general]
debug = false
environment = "development"

[data_sync]
api_url = "https://api.example.com"
batch_size = 50
timeout = 30
retry_enabled = true
```

### Environment Overlay

```toml title="config.prod.toml"
[general]
debug = false
environment = "production"

[data_sync]
api_url = "https://api.prod.example.com"
batch_size = 500
timeout = 60
```

### JobConfig Model and Job Function

```python title="jobs/sync.py"
from pydantic import BaseModel, Field
from functualize.job import RunContext

JOB_NAME = "data_sync"


class SyncConfig(BaseModel):
    """Configuration for the data sync job."""

    api_url: str = Field(description="Target API endpoint URL")
    batch_size: int = Field(default=100, description="Number of records per batch")
    timeout: int = Field(default=30, description="Request timeout in seconds")
    retry_enabled: bool = Field(default=True, description="Enable automatic retries")


def sync(rc: RunContext, config: SyncConfig) -> None:
    """Synchronize data from the configured API endpoint."""
    rc.log(f"Connecting to {config.api_url}", level="info")
    rc.log(f"Batch size: {config.batch_size}, timeout: {config.timeout}s", level="info")

    if config.retry_enabled:
        rc.log("Retries enabled", level="debug")

    # ... sync logic here
```

### Runtime Resolution

With `ENVIRONMENT=PROD`, running the job resolves values as:

| Field | Resolved Value | Source |
|-------|---------------|--------|
| `api_url` | `https://api.prod.example.com` | `config.prod.toml` (overrides base) |
| `batch_size` | `500` | `config.prod.toml` (overrides base) |
| `timeout` | `60` | `config.prod.toml` (overrides base) |
| `retry_enabled` | `true` | `config.base.toml` (not overridden in prod) |

Override any value with an environment variable:

```bash
export DATA_SYNC_BATCH_SIZE=1000
```

Or via CLI:

```bash
myapp data-sync sync --batch-size 2000
```

### Application Setup

```python title="main.py"
from functualize.app import FunctualizeApp, JobSources

app = FunctualizeApp(
    name="myapp",
    job_sources=JobSources(directories=["jobs"]),
)

if __name__ == "__main__":
    app.run()
```

## Using the JobConfigView Class Directly

For advanced use cases, you can use the `JobConfigView` class directly (requires a `ResolutionChain` instance):

```python
from functualize.job import JobConfigView

# JobConfigView is available as rc.config inside job functions
# For advanced use, you can access it directly:
config_view = rc.config

# Get a value with fallback
debug = config_view.get("debug", default="false", section="general")
```

## Introspection with `show-info`

Use the built-in `show-info` command to inspect resolved configuration at runtime:

```bash
# Show general config info and loaded files
myapp show-info

# Show resolved JobConfig for a specific job
myapp show-info --job data_sync

# Show all environment variables
myapp show-info --show-env-vars
```

This displays which config files were loaded, their interpolated values, and the source of each resolved field (env var, config file, or model default).
