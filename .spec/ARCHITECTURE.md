# Architecture Details

Implementation-level architectural decisions extracted from pre-release ADRs.
For high-level rules and invariants, see `CONSTITUTION.md`.

## AdapterPlugin Protocol (Delivery Surfaces)

FunctualizeApp is a lean kernel (~300 LOC facade). All delivery concerns live in `AdapterPlugin` implementations.

```python
@runtime_checkable
class AdapterPlugin(Protocol):
    name: str
    version: str
    description: str
    adapter_type: str  # "cli", "http", "lambda", "mcp"

    def __call__(self, app: FunctualizeApp) -> None: ...  # setup
    def run(self, *args, **kwargs) -> Any: ...             # serve
    def shutdown(self) -> None: ...                         # cleanup
```

Design choices:
- Method is `run()` not `serve()` — more general (CLI "runs", Lambda "runs")
- The adapter owns async decisions internally (kernel stays synchronous)
- CLI is built-in (`[cli]` extras) because `func` needs it; HTTP/Lambda are separate plugin packages
- Capability plugins (e.g., `HttpServerPlugin`) register commands — adapters route them
- Multiple adapters can coexist (e.g., CLI adapter routes to HTTP plugin's `serve` command)
- `adapter_type` field enables introspection without isinstance checks
- Lifecycle: setup → boot → freeze → run → shutdown

## Presets as Factory Functions

Named configuration strategies are plain functions, not a class registry:

```python
def twelve_factor(*, dotenv: bool = False) -> ConfigSources:
    """CLI → Env → Defaults. No file discovery."""
    chain = ResolutionChain([CliSource({}), EnvSource(), DefaultSource({})])
    return ConfigSources(config_resolution_chain=chain, dotenv=dotenv)
```

Contract: any function with signature `(**kwargs) -> ConfigSources` is a valid preset.

- IDE autocompletion works (type the function name, see its kwargs)
- Type-safe: each factory exposes only relevant kwargs
- No registry lookup, no string-based selection, no `PresetNotFoundError`
- Custom presets from teams are just functions in their own modules
- Built-in presets: `classic()`, `twelve_factor()`, `env_only()`, `remote_first()`

## Monorepo Plugin Packaging

Official plugins are independently installable from PyPI, developed alongside core:

```
functualize/
├── src/functualize/          # Core (published as "functualize")
├── plugins/
│   ├── functualize-http/     # Published as "functualize-http"
│   ├── functualize-lambda/   # Published as "functualize-lambda"
│   ├── functualize-state-sqlite/
│   ├── functualize-inline/
│   ├── functualize-flow-viz/
│   └── functualize-fullscreen-tui/
├── pyproject.toml            # [tool.uv.workspace] members = ["plugins/*"]
└── uv.lock                   # Single lockfile for everything
```

Mechanics:
- Each plugin has its own `pyproject.toml` with `[project.entry-points."functualize.plugins"]`
- Entry-point auto-discovery: `pip install functualize-inline` just works — no user configuration
- `functualize[all]` meta-extra installs everything
- Single lockfile (`uv.lock`) via `[tool.uv.workspace]`
- Plugins depend on `functualize>=0.1.0` — version coupling is explicit
- Tests can cross plugin boundaries (integration testing in monorepo)
