# Boot Sequence

## FunctualizeApp Initialization Order

Steps execute in this fixed order. Do not reorder.

| Step | Phase | What Happens |
|------|-------|-------------|
| 0 | `dotenv` | `.env` loaded when `ConfigSources.dotenv`/`dotenv_path` requests it (`override=False`; before EnvSource can be consulted) |
| 1 | `core_infra` | HookRegistry, DIRegistry, JobExecutionEngine instantiated |
| 2 | `provider_registry` | Built-in TOML + INI format providers registered |
| 3 | `observability` | EventBus, MiddlewareStack created (before plugins so they can subscribe) |
| 4 | `plugins` | Entry-point + file-based plugins loaded via PluginLoader (topological sort) |
| 5 | `config_entry_points` | Format/remote provider entry points discovered |
| 6 | `config_resolution` | ResourceLocator + ResolutionChain built once |
| 7 | — | `AFTER_CONFIG_INIT` hook fires |
| 8 | `job_registration` | Providers from JobSources wired (directories → CachedDirectoryScanProvider, functions → Static) |
| 9 | `children` | Child FunctualizeApp projects mounted |
| 10 | `app_ready` | `APP_READY` hook fires — boot complete |
| 11 | `registry_frozen` | DI registry frozen. `REGISTRY_FROZEN` event emitted |
| 12 | `adapter.run()` | Active adapter (CLI/HTTP/Lambda) takes over delivery |

## Static Wiring Fast Path

When all sources are explicit (no filesystem discovery needed):

```python
app = FunctualizeApp(
    "lambda-fn",
    job_sources=JobSources(functions=[deploy]),
    config_sources=ConfigSources(config_resolution_chain=explicit_chain),
    plugin_sources=PluginSources(explicit_plugins=[], entry_point_group=""),
)
```

Steps 2, 5, 6, 8, 9 are skipped entirely → boot in <5ms. Step 0 (dotenv)
still runs when `ConfigSources.dotenv` requests it — the one permitted
filesystem probe on this path; pass `dotenv=False` (or `twelve_factor()`)
for strictly zero I/O.

## Plugin Loading Detail

Within step 4, plugins load in three sub-phases:

1. **Discovery**: `entry_points(group="functualize.plugins")` scan
2. **Ordering**: Topological sort via `depends_on` (Kahn's algorithm)
3. **Registration**: Each plugin's `__call__(app)` invoked in sorted order

Plugins may call `app.provide()`, `app.register_plugin_command()`, subscribe to EventBus, register middleware — all during their `__call__`.

## DI Registry Lifecycle

```
UNFROZEN (during boot)                    FROZEN (after APP_READY)
─────────────────────────                 ────────────────────────
app.provide(Type, inst)     ← allowed     RegistryFrozenError
app.provide_factory(...)    ← allowed     RegistryFrozenError
app.provide_named(...)      ← allowed     RegistryFrozenError

resolve(Type)               ← works       resolve(Type) ← still works
```

The freeze happens between steps 10 and 11. APP_READY hooks are the last chance to register DI providers.

## Performance Budget

Each boot phase has a CI-enforced time budget. See `contributor/reference/performance.md` for the complete budget table and measurement methodology.

The total boot budget is 500ms. If any phase exceeds its budget in CI, the test fails — this is a regression gate.
