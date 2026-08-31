# Entry Point Catalog

## Console Scripts (`pyproject.toml` `[project.scripts]`)

| Command | Target | Notes |
|---|---|---|
| `functualize` | `functualize._cli.main:main` | Full name |
| `func` | `functualize._cli.main:main` | Short alias, identical target |

## Python Module Invocation

`python -m functualize` → `src/functualize/__main__.py` imports `main` from `functualize._cli.main` and calls it directly.

## Entry-Point Groups (plugin/extension discovery)

| Group | Populated by | Purpose |
|---|---|---|
| `functualize.plugins` | Plugin packages (empty in core `pyproject.toml`) | Dynamic plugin discovery at boot (`_plugins/loader.py`) |
| `functualize.format_providers` | Core: `toml` → `functualize._config.providers.toml:TomlFormatProvider`. `IniFormatProvider` is in-tree but **not** registered by default (ADR-007) — a plugin or a third-party entry point registers it. | Config file format parsers |
| `functualize.remote_providers` | Reserved, empty in core; populated by plugins | Remote config source providers |

## Two entry points, one common path

> **Read `contributor/architecture/surface-boundary.md` before adding a flag or
> a dispatch behaviour.** This page catalogues what exists; that one states
> which half of it is `func`-only by design and which half must work on a
> `FunctualizeApp` too.

Everything in the chain below **above** `FunctualizeApp(...)` is `func`'s own
pre-boot layer — global-flag parsing, discovery, routing-name resolution, alias
expansion, mode detection, and the rendering of listings and unknown-command
errors. A user's own `main.py` has none of it and enters at `FunctualizeApp(...)`
directly.

## Invocation Chain: `func <job>` → job execution

```
func deploy --env prod
  │
  ▼
__main__.py  (only for `python -m functualize`; console scripts call main() directly)
  │
  ▼
_cli/main.py: main()                                     [captures _module_import_start_ns
  │                                                        before heavy CLI imports, for perf timing]
  1. _extract_global_options(sys.argv)                    → global flags + cli_flags
  2. auto_discover(cwd, overrides=DiscoveryOverrides(...)) → anchor, merged_config,
     (functualize.app.utils)                                jobs_directories, import_libs
  3. Cache-first name resolution:
     read_routing_names_from_cache(cache.json via resolve_cache_path)
     else cold-boot AST scan: enumerate_job_names / enumerate_group_names
  4. _extract_aliases(merged_config)                       → alias map
  5. detect_mode(sys.argv, job_names, group_names, aliases) → Mode enum:
     (functualize._cli.dispatch)                              SINGLE_FILE | BUILTIN | JOB |
                                                                GROUP | BARE | UNKNOWN
  6. Direct dispatch (no exception-based fallback):
     _handle_single_file() | _handle_job() | _handle_group() |
     _handle_bare() | _handle_unknown() | Click cli_app() (BUILTIN/--help)
  │
  ▼
Handler constructs FunctualizeApp (functualize.app)   ◄── THE BOUNDARY.
                                                       A user's own main.py
                                                       starts here.
  │
  ▼
12-step boot sequence (_app/boot.py) — see data-flow.md
  │
  ▼
Active adapter takes delivery: CliAdapter.run() | TuiAdapter.run() | HttpAdapter | LambdaAdapter | MCP server
  │
  ▼
app.execute(job_name, **kwargs) → JobExecutionEngine.execute() (_engine/executor.py)
  │
  ▼
JobResult
```

## Delivery Adapter Entry Points

| Adapter | Location | Trigger |
|---|---|---|
| `CliAdapter` | `app/adapters/cli.py` | Click command dispatch, built into core `[cli]` extras. Builds one `click.Group` per path segment; a segment whose group declares `GroupOptions` also carries those as real click params, consumed **mid-path** (`glab deploy --env prod web run v1.2`) — see ADR-009 decision 11 |
| `TuiAdapter` | `app/adapters/tui.py` + `_cli/tui/app.py` | inline SmartBar TUI (bare `func` on a TTY) / full-screen TUI |
| HTTP adapter | `plugins/functualize-http` | asyncio HTTP server, `AdapterPlugin.run()` |
| Lambda adapter | `plugins/functualize-lambda` | AWS Lambda event → `app.execute()` |
| MCP adapter | `plugins/functualize-mcp` | FastMCP tool exposure of jobs |

All delivery adapters converge on the same `engine.execute(name, fn, config_class, kwargs)` call — see `contributor/architecture/execution-flow.md` and `data-flow.md`.

**One argument beside `kwargs`.** A job reached through a group that declares
`GroupOptions` also carries `group_option_values` — a flat `{field: value}` map
of the flags typed *before* the job name. They are not the job's kwargs (the job
never declares them; it receives an options class), and they reach the engine as
the **CLI layer**, outranking the group's config file. Two entry points fill it,
and they must agree:

| Path | Who consumes the mid-path flags |
|---|---|
| `func …` | `walk_group_path` in `_cli/dispatch.py`, before click sees the line |
| an app's own script (`glab …`) | click itself, via params attached to each declaring group node in `app/adapters/cli.py` |

The adapter path deposits only values click reports as coming from
`COMMANDLINE`; depositing its defaults would silently beat the group's config
file. Parity between the two is pinned by
`tests/group_options/test_adapter_entry_point_parity.py`.

## Static/Programmatic Entry Point

Library users construct `FunctualizeApp` directly with explicit `JobSources(functions=[...])`, bypassing filesystem discovery entirely for a boot fast-path (<5ms):

```python
app = FunctualizeApp(
    "lambda-fn",
    job_sources=JobSources(functions=[deploy]),
    config_sources=ConfigSources(config_resolution_chain=explicit_chain),
    plugin_sources=PluginSources(explicit_plugins=[], entry_point_group=""),
)
```
