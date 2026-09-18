# Config (Internal)

The configuration resolution system now lives in the internal `functualize._config` package. End users interact with configuration through:

- **`functualize.app.ConfigSources`** — the public dataclass for specifying config strategies
- **Preset factory functions** — `classic()`, `twelve_factor()`, `env_only()`, `remote_first()` from `functualize.app`
- **`functualize.job.JobConfigView`** — the resolved config view available inside jobs
- **`functualize.types.ConfigFileRole`** / **`functualize.types.EnvironmentSource`** — which discovered config file won, and where the active environment name came from

## Public API

```python
from functualize.app import ConfigSources, classic, twelve_factor, env_only, remote_first
from functualize.job import JobConfigView
from functualize.types import ConfigFileRole, EnvironmentSource
```

## Config File Roles and Environment Source

Two enums answer questions a user staring at a config file that "isn't taking effect" actually has: which file won, and why did this environment get selected.

### `ConfigFileRole`

The role a discovered config file plays under the active environment. Config files are named `config.<slot>.<ext>`: the `base` slot is always loaded, a slot matching the active environment is merged on top of it, and any other slot belongs to a different environment and is never merged.

```python
from functualize.types import ConfigFileRole

class ConfigFileRole(Enum):
    BASE = "base"        # Always merged, regardless of the active environment.
    OVERLAY = "overlay"  # Slot matches the active environment — merged on top of BASE.
    INERT = "inert"       # Slot names a different environment — discovered, but never merged.
```

It is the `role` field on `functualize.types.ConfigFileInfo` (one entry per discovered file, returned by `app.configuration.config_files()`), and drives that type's `is_active` property (`role is not ConfigFileRole.INERT and parsed`).

### `EnvironmentSource`

Where the active environment name came from — distinguishing "explicitly selected" from "fell back to the default", which matters when a config overlay silently isn't taking effect.

```python
from functualize.types import EnvironmentSource

class EnvironmentSource(Enum):
    FUNCTUALIZE_ENV = "FUNCTUALIZE_ENV"
    ENVIRONMENT = "ENVIRONMENT"
    ENV = "ENV"
    DEFAULT = "default"
```

Read it with `app.configuration.environment_source()`, paired with `app.configuration.active_environment()` for the name itself:

```python
from functualize.types import EnvironmentSource

if app.configuration.environment_source() is EnvironmentSource.DEFAULT:
    print("no environment variable selected this — using the default")
```

`EnvironmentSource.DEFAULT` means nothing selected it explicitly; the other three members name the environment variable that did (`FUNCTUALIZE_ENV` takes precedence, then `ENVIRONMENT`, then `ENV`).

## Internal Location

The implementation details (ResolutionChain, config sources, providers) are in `functualize._config/`:

- `_config/chain.py` — ResolutionChain
- `_config/sources.py` — CliSource, EnvSource, FileSource, RemoteSource, DefaultSource
- `_config/job_config.py` — JobConfigView implementation + validation
- `_config/providers/` — format providers. `TomlFormatProvider` is the only one registered by default; `IniFormatProvider` is in-tree but must be registered by a plugin (ADR-007)

!!! warning "Internal API"
    Modules under `functualize._config` are implementation details. Import from `functualize.app` or `functualize.job` instead.
