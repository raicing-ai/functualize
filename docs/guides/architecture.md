# Architecture

This guide describes how functualize is structured internally. Understanding the architecture helps when building plugins, debugging boot issues, or extending the framework.

!!! note "For Framework Contributors"
    If you're modifying functualize's internals, see `contributor/architecture/overview.md` for a terser, framework-contributor-focused version of this content optimized for understanding the framework's core layers and internal module structure.

---

## Mental Model

> **functualize is a pipeline that discovers, configures, and executes job functions through pluggable adapters.**

Think of it as three stages:

1. **Discovery** — find job functions in directories, modules, or static registrations
2. **Configuration** — resolve each job's config from CLI args, environment, files, and defaults
3. **Execution** — run the job function with a fully-wired `RunContext`, emitting lifecycle events

Adapters (CLI, HTTP, Lambda, TUI) sit at the edges — they translate external requests into `execute(job_name, **kwargs)` calls and render results back to the user. The kernel knows nothing about Click, HTTP frameworks, or terminal UIs.

---

## Data Flow

This diagram shows the complete request lifecycle from an external trigger through to the final result.

```mermaid
flowchart LR
    subgraph External
        CLI["CLI (Click)"]
        HTTP["HTTP Server"]
        Lambda["Lambda Handler"]
        TUI["TUI (Textual)"]
    end

    subgraph Adapter Layer
        CA["CliAdapter"]
        HA["HttpAdapter"]
        LA["LambdaAdapter"]
        TA["TuiAdapter"]
    end

    subgraph Core Pipeline
        APP["FunctualizeApp<br/>.execute(job_name, **kwargs)"]
        ENGINE["JobExecutionEngine"]
        MW["MiddlewareChain<br/>(pre/post hooks)"]
        RESOLVE["Config Resolution<br/>(ResolutionChain)"]
        JOB["Job Function<br/>(user code)"]
    end

    subgraph Result
        RES["JobResult<br/>(status, return_value,<br/>duration_ms, metadata)"]
    end

    CLI --> CA
    HTTP --> HA
    Lambda --> LA
    TUI --> TA

    CA --> APP
    HA --> APP
    LA --> APP
    TA --> APP

    APP --> ENGINE
    ENGINE --> MW
    MW --> RESOLVE
    RESOLVE --> JOB
    JOB --> RES
    RES --> ENGINE
    ENGINE --> APP
```

Key points:
- All adapters funnel through the same `FunctualizeApp.execute()` entry point
- The engine applies middleware (hooks, observability, error handling) around the job call
- Config resolution happens per-execution using the `ResolutionChain` built at boot time
- The job function receives a fully-configured `RunContext` with DI, logging, and event capabilities

---

## Boot Sequence

The boot process wires all subsystems in a deterministic order. Steps must not be reordered — later steps depend on earlier ones being complete.

```mermaid
sequenceDiagram
    participant User
    participant App as FunctualizeApp
    participant Boot as _app/boot.py
    participant Discovery as _discovery/
    participant Config as _config/
    participant Plugins as _plugins/
    participant Events as _events/
    participant DI as DIRegistry

    User->>App: FunctualizeApp(name, job_sources, config_sources, ...)
    App->>Boot: _boot_standard()

    Note over Boot: Phase 1: Core Infrastructure
    Boot->>Events: Create EventBus
    Boot->>DI: Create DIRegistry
    Boot->>Boot: Create JobExecutionEngine

    Note over Boot: Phase 2: Discovery
    Boot->>Discovery: Wire providers from JobSources
    Discovery-->>Boot: list[JobDescriptor]

    Note over Boot: Phase 3: Config Resolution
    Boot->>Config: Build ResolutionChain from ConfigSources
    Config-->>Boot: ResolutionChain (frozen)

    Note over Boot: Phase 4: Plugin Loading
    Boot->>Plugins: PluginLoader.load_all(plugin_sources)
    Plugins-->>Boot: Loaded plugins (sorted by dependency)

    Note over Boot: Phase 5: Registry Freeze
    Boot->>DI: Freeze registry (no further provide() calls)
    Boot->>Events: Emit REGISTRY_FROZEN

    Note over Boot: Phase 6: APP_READY
    Boot->>Events: Emit APP_READY
    Boot-->>App: Boot complete

    Note over User,App: Adapter takes over delivery
    User->>App: adapter.run()
```

| Step | Phase | What happens |
|---|---|---|
| 1 | `core_infra` | `EventBus`, `DIRegistry`, `JobExecutionEngine` instantiated |
| 2 | `provider_registry` | `TomlFormatProvider` registered — the only built-in default since ADR-007 |
| 3 | `observability` | `MiddlewareStack` created (before plugins so plugins can subscribe) |
| 4 | `plugins` | Entry-point and file-based plugins loaded via `PluginLoader.load_all()` |
| 5 | `config_entry_points` | Format and remote providers from entry points discovered |
| 6 | `config_resolution` | `ResourceLocator` and `ResolutionChain` built once; all config lookups reuse them |
| 7 | `job_registration` | Providers from `JobSources` wired (directories → `CachedDirectoryScanProvider`, functions → `StaticProvider`) |
| 8 | `children` | Child `FunctualizeApp` projects mounted via `ChildProjectLoader` |
| 9 | `registry_frozen` | DI registry frozen — no further `provide()` calls. `REGISTRY_FROZEN` event emitted |
| 10 | `app_ready` | `APP_READY` hook fires — all boot steps complete |
| 11 | `adapter.run()` | Active adapter (CLI, HTTP, Lambda, TUI) takes over delivery |

Config files are parsed **once at boot** — there is no per-invocation file I/O.

On application exit, plugins implementing `PluginWithShutdown` have their `on_shutdown()` called in reverse loading order (5-second per-plugin timeout).

---

## Layer Dependency Graph

functualize enforces strict layer dependencies via `import-linter`. Each layer may only import from layers below it in the graph. Violations are caught in CI.

```mermaid
graph TD
    subgraph Foundation["Foundation (no internal deps)"]
        _types["_types/<br/>Shared vocabulary:<br/>frozen dataclasses, Enums, Protocols"]
    end

    subgraph Utilities["Utilities"]
        _primitives["_primitives/<br/>DIRegistry, ResourceLocator,<br/>MiddlewareChain, lazy_cached"]
    end

    subgraph CrossCutting["Cross-Cutting"]
        _events["_events/<br/>EventBus, HookRegistry,<br/>PerfTimeline, PropagationContext"]
    end

    subgraph PeerLayers["Peer Layers (independent — never import each other)"]
        _discovery["_discovery/<br/>Job finding + caching"]
        _config["_config/<br/>Config resolution"]
        _engine["_engine/<br/>Execution lifecycle"]
        _plugins["_plugins/<br/>Plugin loading"]
    end

    subgraph CompositionRoot["Composition Root"]
        _app["_app/<br/>Boot orchestration,<br/>wires all peer layers via DI"]
    end

    subgraph Delivery["Delivery (public API only)"]
        _cli["_cli/<br/>CLI commands, scaffold"]
    end

    subgraph PublicAPI["Public API Surface"]
        pub_app["app/"]
        pub_job["job/"]
        pub_plugin["plugin/"]
        pub_types["types/"]
        pub_testing["testing/"]
    end

    %% Foundation dependencies
    _primitives --> _types
    _events --> _types
    _events --> _primitives

    %% Peer layer dependencies (all go to foundation + events)
    _discovery --> _types
    _discovery --> _primitives
    _discovery --> _events
    _config --> _types
    _config --> _primitives
    _config --> _events
    _engine --> _types
    _engine --> _primitives
    _engine --> _events
    _plugins --> _types
    _plugins --> _primitives
    _plugins --> _events

    %% Composition root wires everything
    _app --> _types
    _app --> _primitives
    _app --> _events
    _app --> _discovery
    _app --> _config
    _app --> _engine
    _app --> _plugins

    %% Public API delegates to internals
    pub_app --> _app

    %% CLI uses only public API
    _cli --> pub_app
    _cli --> pub_job
    _cli --> pub_plugin
    _cli --> pub_types
    _cli --> pub_testing
```

### Layer rules summarized

| Layer | May import from | Must NOT import from |
|-------|----------------|---------------------|
| `_types/` | stdlib only | Any `_`-prefixed package |
| `_primitives/` | `_types/`, stdlib | `_events` through `_cli` |
| `_events/` | `_types/`, `_primitives/` | `_discovery` through `_cli` |
| Peer layers (`_discovery`, `_config`, `_engine`, `_plugins`) | `_types/`, `_primitives/`, `_events/` | Each other, `_app`, `_cli` |
| `_app/` | All internal layers | `_cli`, any public folder |
| `_cli/` | Public folders only | Any `_`-prefixed package |

---

## Audience Diagram

Different audiences interact with different packages. This diagram shows which imports each role uses.

```mermaid
flowchart TB
    subgraph Audiences
        JA["👤 Job Author<br/>(writes job functions)"]
        PA["👤 Plugin Author<br/>(extends the framework)"]
        AC["👤 App Constructor<br/>(builds the app entry point)"]
        CT["👤 Contributor<br/>(works on functualize internals)"]
    end

    subgraph PublicPackages["Public Packages"]
        job["job/<br/>RunContext, Log, Invoke,<br/>Prompt, Perf, State"]
        plugin["plugin/<br/>EventBus, JobProvider,<br/>AdapterPlugin, HookEvent"]
        app["app/<br/>FunctualizeApp, JobSources,<br/>ConfigSources, presets"]
        types["types/<br/>JobResult, JobDescriptor,<br/>FieldDescriptor, RunStatus"]
        testing["testing/<br/>TestRunContext, CapturingLog,<br/>MockInvoke, AutoPrompt"]
    end

    subgraph InternalPackages["Internal Packages (contributor only)"]
        internals["_types/ · _primitives/ · _events/<br/>_discovery/ · _config/ · _engine/<br/>_plugins/ · _app/ · _cli/"]
    end

    JA --> job
    JA --> types
    JA --> testing

    PA --> plugin
    PA --> types
    PA --> app

    AC --> app
    AC --> types
    AC --> testing

    CT --> internals
    CT --> PublicPackages
```

### What each audience imports

| Audience | Primary imports | Example |
|----------|----------------|---------|
| **Job author** | `functualize.job`, `functualize.types` | `from functualize.job import RunContext, Log, Invoke` |
| **Plugin author** | `functualize.plugin`, `functualize.types` | `from functualize.plugin import EventBus, JobProvider, AdapterPlugin` |
| **App constructor** | `functualize.app`, `functualize.types` | `from functualize.app import FunctualizeApp, JobSources, classic` |
| **Test writer** | `functualize.testing` | `from functualize.testing import TestRunContext, CapturingLog` |
| **Contributor** | Internal `_`-prefixed packages | `from functualize._engine.capabilities.invoke import Invoke` |

---

## Composition Root Pattern

The `_app/` package is the **sole composition root** — the only place where peer layers are wired together. No peer layer knows about any other peer layer.

```mermaid
flowchart TD
    subgraph _app["_app/ (Composition Root)"]
        boot["boot.py<br/>Orchestrates wiring"]
        impl["impl.py<br/>Heavy internal methods"]
        state["state.py<br/>AppState holder"]
    end

    subgraph Peers["Peer Layers (independent)"]
        disc["_discovery/"]
        conf["_config/"]
        eng["_engine/"]
        plug["_plugins/"]
    end

    subgraph Foundation
        ev["_events/"]
        prim["_primitives/"]
        typ["_types/"]
    end

    boot -->|"creates providers"| disc
    boot -->|"builds ResolutionChain"| conf
    boot -->|"configures executor"| eng
    boot -->|"loads plugins"| plug
    boot -->|"creates EventBus"| ev
    boot -->|"creates DIRegistry"| prim
    boot -->|"reads protocols"| typ

    disc -.->|"CANNOT import"| conf
    disc -.->|"CANNOT import"| eng
    disc -.->|"CANNOT import"| plug
    conf -.->|"CANNOT import"| disc
    conf -.->|"CANNOT import"| eng
    eng -.->|"CANNOT import"| disc
    eng -.->|"CANNOT import"| conf
```

**Why this matters:**
- Adding a new discovery provider doesn't require touching config or engine code
- Plugin loading can be tested in complete isolation from job discovery
- The boot sequence in `_app/boot.py` is the single place to understand how everything connects
- Changing wiring logic (e.g., swapping a provider) is localized to one file

---

## Config Resolution

Configuration is resolved with a fixed precedence. The first non-`None` value wins.

```
CLI args  >  Environment variables  >  Config files  >  Defaults
```

| Source | Implementation | Notes |
|---|---|---|
| CLI args | Click option parsing | Passed as `kwargs` to the job function |
| Environment variables | `EnvSource` | Variables named `<APP>_<SECTION>_<KEY>` |
| Config files | `FileSource` + format providers | TOML by default; pluggable |
| Defaults | `DefaultSource` | Pydantic field `default` / `default_factory` |

**Key components:**

- `ResolutionChain` — consults `Source` implementations in order; records provenance for each resolved value
- `ResourceLocator` — walks upward from CWD to find config files; never uses hard-coded paths
- `JobConfigView` — wraps `ResolutionChain` plus in-memory overrides; injected into `RunContext`
- Format providers — pluggable parsers registered via entry points or a plugin. TOML is the only one registered by default; `IniFormatProvider` ships in-tree and must be registered explicitly (ADR-007), which a plugin can do because plugins load before the resolution chain is built

---

## Interactivity Layer

The interactivity layer decouples job execution from any specific UI through two protocol-based channels: output rendering and input collection.

### Output channel — the Surface protocol

`JobExecutionEngine` fans every non-framework event out to all registered
`Surface` instances (`handle_event(event)`):

```
JobExecutionEngine
      |  handle_event(StructuredEvent)     [Surface]  (e.g. the TUI panel,
      +--------------------------------->            StdoutSurface, flow-viz,
      |                                              a job-owned TextualApp,
      +--------------------------------->            a log-file recorder)
```

While a job owns the screen (an EXCLUSIVE window), other terminal-drawing
surfaces are skipped; headless surfaces (`needs_terminal = False`) keep receiving.

### Input channel — the PromptCollector protocol

When a job calls `rc.prompt_*()`, the framework routes to exactly one active
`PromptCollector` (top of the surface stack), falling back to a TTY-gated stdin
collector:

```
[Job Function] → rc.prompt_confirm(...) → [RunContext]
      → active PromptCollector.collect(request) → PromptResponse
        (inline TUI, a job app's modal, stdin fallback, MCP gate)
```

### Job-owned UIs — the TTY and Live capabilities

A job declares where it renders in its signature (harvested statically into the
descriptor cache): `tty: TTY` grants terminal ownership for a job-owned Textual
app (`tty.run(app)`, refused off a terminal), and `live: Live` mounts a live
`LiveConstruct` into the active surface's live zone (`live.add(construct)`).

### Custom event emission — rc.emit()

Jobs emit custom structured events that reach the `EventBus` and every registered
`Surface`:

```python
rc.emit("pipeline.stage.complete", resource="extract", records=1000)
```

Framework lifecycle events (`job.execute.*`, `job.teardown.*`, `plugin.*`,
`config.*`, `cli.*`, `tui.*`) are filtered out — they never reach a `Surface`.

Exceptions inside `handle_event` are **swallowed with a warning** — one bad
surface never interrupts a job or starves its peers.

---

## Extension Points Summary

| Extension point | Interface | Registered via | Purpose |
|---|---|---|---|
| **Hooks** | `HookRegistry.register()` | Code (`app.hooks.register(...)`) | Callbacks at lifecycle points |
| **DI Registration** | `app.provide()` / `provide_factory()` / `provide_named()` | Code (from plugins during boot) | Register typed capabilities for DI injection |
| **Plugins** | `PluginMetadata` protocol + callable | Python entry points (`functualize.plugins`) | Add CLI commands, register providers, subscribe to events |
| **Adapters** | `AdapterPlugin` Protocol | `adapter(app); adapter.run()` | Delivery surfaces: CLI, HTTP, Lambda, custom |
| **Surface** | `Surface` protocol (`handle_event`) | `app.register_surface(obj)` | Render a job's events |
| **PromptCollector** | `PromptCollector` protocol (`collect`) | `app.register_surface(obj)` | Answer `rc.prompt_*()` |
| **Job UI capabilities** | `tty: TTY` / `live: Live` params | declared in the job signature | Own the terminal / mount a live construct |
| **Job Providers** | `JobProvider` Protocol | `app.add_job_provider(provider)` | Custom job discovery sources |
| **Job Transforms** | `JobTransform` Protocol | `app.add_job_transform(transform)` | Intercept and modify job descriptors |
| **EventBus** | `app.event_bus.emit / subscribe` | Code | Structured publish-subscribe |
| **Middleware** | `MiddlewareChain` (yield-based generators) | Code | Wrap execution at named operation points |
| **Format providers** | `FormatProvider` protocol | Entry points or `provider_registry` | Support for new config file formats |
| **StateStore** | `StateStoreProtocol` protocol | `scope.replace_state_store(impl)` | Pluggable state storage backends |
