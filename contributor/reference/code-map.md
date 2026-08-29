# Code Map — Where Things Live

## Public API Surface

### `app/` — Application Construction

| Symbol | File | Purpose |
|--------|------|---------|
| `FunctualizeApp` | `app/core.py` | Public facade (≤300 LOC), delegates to `_app/` |
| `JobSources` | `app/config.py` | Frozen dataclass: where jobs come from |
| `ConfigSources` | `app/config.py` | Frozen dataclass: where config comes from |
| `PluginSources` | `app/config.py` | Frozen dataclass: plugin discovery settings |
| `ExecutionConfig` | `app/config.py` | Frozen dataclass: execution params (max_invoke_depth) |
| `classic()` | `app/presets.py` | Preset: CLI → Env → Files → Defaults |
| `twelve_factor()` | `app/presets.py` | Preset: CLI → Env → Defaults (no files) |
| `env_only()` | `app/presets.py` | Preset: CLI → Env → Defaults (minimal) |
| `remote_first()` | `app/presets.py` | Preset: CLI → Env → Files → Defaults. Named for an unwired capability — nothing constructs `RemoteSource`, so this resolves as `classic()` with a different file pattern |
| `coerce_kwargs()` | `app/utils.py` | String → Python type coercion via Pydantic |
| `import_job()` | `app/utils.py` | Import job function(s) from a file path |
| `auto_discover()` | `app/utils.py` | Scan CWD for job directories |
| `CliAdapter` | `app/adapters/cli.py` | Built-in CLI delivery (Click wiring) |
| `TuiAdapter` | `app/adapters/tui.py` | Built-in TUI delivery (inline Textual TUI) |

### `job/` — Job Author API

| Symbol | File | Purpose |
|--------|------|---------|
| `RunContext` | `job/context.py` | Thin facade over DI registry (~500 LOC) |
| `Log` | `job/capabilities.py` | Logging capability (info, warning, error, debug) |
| `Invoke` | `job/capabilities.py` | Job invocation (call, parallel, schema) |
| `Prompt` | `job/capabilities.py` | User input collection (ask, confirm, choice, text) |
| `Perf` | `job/capabilities.py` | Performance marking (mark, mark_start, mark_end) |
| `State` | `job/capabilities.py` | Key-value state (get, set, delete, keys) |
| `JobContext` | `job/capabilities.py` | Frozen dataclass: name, trace_id, deadline, metadata |
| `JobConfigView` | `job/` | Scoped config access for jobs |
| `TTY` | `job/capabilities.py` | Terminal-ownership capability (HARD: forces EXCLUSIVE) |
| `Live` | `job/capabilities.py` | Live-display channel (always injected, degrading) |
| `suppress_live` | `job/decorators.py` | Opt a job out of ambient live constructs |
| `surface_hint` | `job/decorators.py` | Per-job render-surface preference ("stdout"/"panel") |
| `Arg` / `Option` / `Stdin` | `job/markers.py` | CLI parameter annotation markers |

### `plugin/` — Plugin Author API

| Symbol | File | Purpose |
|--------|------|---------|
| `EventBus` | `plugin/` | Structured event pub-sub |
| `HookEvent` | `plugin/` | Hook event constants |
| `StructuredEvent` | `plugin/` | Event dataclass |
| `JobProvider` | `plugin/` | Protocol: job discovery source |
| `JobTransform` | `plugin/` | Protocol: modify job descriptors |
| `Job` | `plugin/` | Frozen dataclass for static job registration |
| `AdapterPlugin` | `plugin/` | Protocol: delivery surface |
| `Surface` | `plugin/` | Protocol: renders a job's events (`handle_event`) |
| `PromptCollector` | `plugin/` | Protocol: answers a job's prompts (`collect`) |
| `LiveConstruct` | `plugin/` | Protocol: a Rich renderable hosted in a live zone |
| `PromptRequest` | `plugin/` | Rich prompt context dataclass |
| `PluginMetadata` | `plugin/` | Protocol: plugin identity |
| `PluginWithShutdown` | `plugin/` | Protocol: graceful cleanup |
| `Source` | `plugin/` | Protocol: config source |
| `FormatProvider` | `plugin/` | Protocol: config file format |
| `DisplayProvider` | `plugin/protocols.py` | Protocol: above-header ambient display panel |
| `PanelProvider` | `plugin/protocols.py` | Protocol: panel-ring panel (reserved shape) |
| `InteractiveContent` | `plugin/protocols.py` | Protocol: the converged widget interaction contract |

### `ui/` — Job-Owned / Display UI (`[cli]` extra)

| Symbol | File | Purpose |
|--------|------|---------|
| `TextualApp` | `ui/textual_app.py` | Base class for `tty: TTY` jobs' own Textual apps |
| `StdoutSurface` / `stdout_live_session` | `ui/stdout_surface.py` | Rich STDOUT rendering for direct runs |
| `Display` | `ui/display.py` | Optional display-provider base; nests `Display.DrillDown` |

### `types/` — Shared Types

| Symbol | File | Purpose |
|--------|------|---------|
| `JobResult` | `types/` | Execution result (status, return_value, duration_ms) |
| `JobDescriptor` | `types/` | Job metadata (name, group, function, parameters) |
| `FieldDescriptor` | `types/` | Parameter schema (name, type, default, required) |
| `RunStatus` | `types/` | Enum: RUNNING, SUCCESS, FAILURE, CANCELLED, TIMEOUT |
| `RunType` | `types/` | Enum: execution type |
| `JobPhase` | `types/` | Step tracking dataclass |
| `CacheInfo` | `types/` | Cache statistics dataclass |

### `testing/` — Test Helpers

| Symbol | File | Purpose |
|--------|------|---------|
| `TestRunContext` | `testing/builder.py` | Builder with `.create(...)` for minimal test setup |
| `CapturingLog` | `testing/doubles.py` | Records (level, message) tuples |
| `MockInvoke` | `testing/doubles.py` | Returns pre-configured results by job name |
| `AutoPrompt` | `testing/doubles.py` | FIFO response queue |
| `NoopPerf` | `testing/doubles.py` | Accepts all calls silently |

---

## Internal Implementation

### `_types/` — Shared Vocabulary (No Logic)

Contains ONLY: frozen dataclasses, Enums, Protocol definitions.
Zero function bodies beyond `...`, `pass`, or trivial property accessors.

### `_primitives/` — Foundation Utilities

| Module | Contains |
|--------|----------|
| `di.py` | DIRegistry, ResolutionPlan, Provide marker, MissingProviderError, etc. |
| `locator.py` | ResourceLocator (fluent builder for path discovery) |
| `middleware.py` | MiddlewareChain[TContext, TResult] (generic yield-based) |
| `pre_filter.py` | ModulePreFilter protocol + AllOf/AnyOf/NoneOf combinators |
| `lazy.py` | `lazy_cached` descriptor |
| `resilient.py` | `resilient(iterable, on_error)` generator |
| `modules.py` | `iter_module_files(directory)` |

### `_events/` — Cross-Cutting

| Module | Contains |
|--------|----------|
| `bus.py` | EventBus implementation (trie-based topic router) |
| `hooks.py` | HookRegistry (lifecycle interceptors) |
| `tracing.py` | PropagationContext (trace_id/span_id) |
| `perf.py` | PerfTimeline, Phase, PerfReport |

### `_discovery/` — Job Finding

| Module | Contains |
|--------|----------|
| `providers.py` | DirectoryScanProvider, StaticProvider, EntryPointProvider |
| `transforms.py` | NamespaceTransform, GroupByModuleAttributeTransform |
| `cache.py` | CachedDirectoryScanProvider (consolidated) |
| `pre_filter.py` | Built-in pre-filter implementations |
| `hierarchy.py` | Child project composition |
| `pipeline.py` | ResolutionPipeline |

### `_config/` — Configuration Resolution

| Module | Contains |
|--------|----------|
| `chain.py` | ResolutionChain |
| `sources.py` | CliSource, EnvSource, FileSource, RemoteSource, DefaultSource |
| `job_config.py` | JobConfigView implementation + validation |
| `providers/` | TomlFormatProvider, IniFormatProvider |

### `_engine/` — Execution Lifecycle

| Module | Contains |
|--------|----------|
| `executor.py` | JobExecutionEngine |
| `middleware.py` | Job execution middleware chain |
| `context.py` | ExecutionContext |
| `resolution.py` | ResolutionPlan, DI param binding |
| `result.py` | RegisteredJob internals |
| `surface_routing.py` | Event fan-out, active collector, live-zone resolution over the surface stack |
| `capabilities/invoke.py` | Invoke implementation (~150 LOC) |
| `capabilities/workflow.py` | WorkflowTracker (~100 LOC) |
| `capabilities/tty.py` | `TTY` capability (terminal ownership) + `terminal_available()` |
| `capabilities/live.py` | `Live` capability (per-surface live-display channel) |
| `capabilities/stdin_collector.py` | Kernel TTY-gated stdin `PromptCollector` fallback |

### `_plugins/` — Plugin Loading

| Module | Contains |
|--------|----------|
| `loader.py` | PluginLoader (discovery + topological sort + loading) |
| `config.py` | PluginConfigRegistry |

### `_app/` — Composition Root

| Module | Contains |
|--------|----------|
| `boot.py` | Boot orchestration (the only place that wires peer layers) |
| `impl.py` | FunctualizeApp internal methods |
| `state.py` | AppState |

### `_cli/` — CLI Delivery

| Module | Contains |
|--------|----------|
| `main.py` | Entry point, arg routing → JobSources → CliAdapter.run() |
| `builtins.py` | cache, version, domains commands |
| `scaffold/` | scaffold sub-command (Click + Jinja2) |
| `orchestrator.py` | Surface-resolution ladder (`resolve_surface`, `RenderSurface`) |
| `inline_tui.py` | Inline-TUI launch + the EXCLUSIVE handoff loop |

### `ui/` — Textual/Rich building blocks (the `[cli]` extra)

Public home of the UI building blocks (importable only with `functualize[cli]`):

| Module | Contains |
|--------|----------|
| `textual_app.py` | `TextualApp` — Surface + PromptCollector base for job-owned UIs (`FuncEvent`, pre-mount buffer, modal `collect`) |
| `stdout_surface.py` | `StdoutSurface` (one-writer rich stdout runtime) + `stdout_live_session` |
| `_prompt_modal.py` | Shared `PromptModal` used by `TextualApp.collect` |
| `fullscreen/` | `FullscreenTuiApp` — a shipped `TextualApp` subclass (was the fullscreen plugin) |

### `_gate/` — Gate Resolution (Internal)

Gate resolution for workflow steps that pause for input collection.

| Module | Contains |
|--------|----------|
| `_strategy.py` | GateStrategy enum (RESOLVE, PROMPT, AI_INBOUND) |
| `_resolver.py` | GateResolver implementation |
| `_context.py` | Gate execution context |
| `_registry.py` | Gate registry and lookup |

### `workflow/` — Workflow Definition API (Public)

Decorator and type definitions for workflow-based job composition.

| Symbol | Module | Purpose |
|--------|--------|---------|
| `@workflow` | `_decorator.py` | Decorator for defining multi-step workflows with edges and conditions |
| `Step` | `_types.py` | Workflow step definition |
| `Edge` | `_types.py` | Directed edge between workflow steps |
| `ConditionalEdge` | `_types.py` | Conditional edge with guard clause |
| `END` | `_types.py` | Sentinel marking workflow termination |

---

## Official Plugins

Located in `plugins/`, these are maintained as part of the core monorepo:

| Plugin | Package | Purpose |
|--------|---------|---------|
| `functualize-ai` | AI/LLM integration | LLM-powered job generation and parameter inference |
| `functualize-ai-pydantic` | AI + Pydantic | Pydantic schema integration for AI parameter extraction |
| `functualize-flow-viz` | Flow visualization | Directed acyclic graph rendering for job workflows |
| `functualize-http` | HTTP delivery | HTTP request adapter for REST API exposure |
| `functualize-inline` | Inline TUI | Inline text-based user interface (minimal terminal overhead) |
| `functualize-lambda` | AWS Lambda | AWS Lambda deployment and invocation adapter |
| `functualize-mcp` | Model Context Protocol | Claude MCP server integration for model-assisted execution |
| `functualize-state` | State management | In-memory key-value state backend |
| `functualize-state-sqlite` | SQLite state | Persistent state backend using SQLite |
| `functualize-tasks` | Task scheduling | Task queue abstraction for async job scheduling |
| `functualize-tasks-local` | Local task queue | Local in-memory task queue implementation |
