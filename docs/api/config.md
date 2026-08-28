# Config (Internal)

The configuration resolution system now lives in the internal `functualize._config` package. End users interact with configuration through:

- **`functualize.app.ConfigSources`** — the public dataclass for specifying config strategies
- **Preset factory functions** — `classic()`, `twelve_factor()`, `env_only()`, `remote_first()` from `functualize.app`
- **`functualize.job.JobConfigView`** — the resolved config view available inside jobs

## Public API

```python
from functualize.app import ConfigSources, classic, twelve_factor, env_only, remote_first
from functualize.job import JobConfigView
```

## Internal Location

The implementation details (ResolutionChain, config sources, providers) are in `functualize._config/`:

- `_config/chain.py` — ResolutionChain
- `_config/sources.py` — CliSource, EnvSource, FileSource, RemoteSource, DefaultSource
- `_config/job_config.py` — JobConfigView implementation + validation
- `_config/providers/` — format providers. `TomlFormatProvider` is the only one registered by default; `IniFormatProvider` is in-tree but must be registered by a plugin (ADR-007)

!!! warning "Internal API"
    Modules under `functualize._config` are implementation details. Import from `functualize.app` or `functualize.job` instead.
