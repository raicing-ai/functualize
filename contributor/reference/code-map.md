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
| `DiscoveryConfig` | `app/config.py` | Frozen dataclass: the ten discovery settings. `pre_filter` takes a caller-supplied `ModulePreFilter`, ANDed onto the `require_*` stack; its `fingerprint()` — never the object — joins the cache digest |
| `classic()` | `app/presets.py` | Preset: CLI → Env → Files → Defaults |
| `twelve_factor()` | `app/presets.py` | Preset: CLI → Env → Defaults (no files) |
| `env_only()` | `app/presets.py` | Preset: CLI → Env → Defaults (minimal) |
| `remote_first()` | `app/presets.py` | Preset: CLI → Vault → Env → Files → Defaults. `provider://reference` values resolve from the project's encrypted local vault, filled by `func builtin vault sync`; reads never touch the network. Raises at construction when no remote provider is registered, rather than degrading to `classic()` (ADR-016) |
| `coerce_kwargs()` | `app/utils.py` | String → Python type coercion via Pydantic |
| `import_job()` | `app/utils.py` | Import job function(s) from a file path |
| `auto_discover()` | `app/utils.py` | Scan CWD for job directories |
| `CliAdapter` | `app/adapters/cli.py` | Built-in CLI delivery (Click wiring) |
| `TuiAdapter` | `app/adapters/tui.py` | Built-in TUI delivery (inline Textual TUI) |
| `detect_from_process()` | `app/packaging.py` | How this program was installed and which distribution owns it (`InstallMode`, `Detection`). Stdlib only, every input a parameter |
| `update_commands()` | `app/packaging.py` | The argv that upgrades this installation — also `install_commands`, `uninstall_commands`. Returns commands or raises; never prints, prompts or spawns |

### `job/` — Job Author API

| Symbol | File | Purpose |
|--------|------|---------|
| `RunContext` | `_engine/capabilities/runcontext.py` | The job-author core: `config`, `log`, `invoke`, `state`, `cwd`. ~256 executable lines, budgeted at 500 by `tests/test_facade_loc_limits.py`. Rarer capabilities are grouped behind `rc.events`, `rc.prompts`, `rc.discovery` and `rc.wiring` (`engine-sealed-construction`/T8) |
| `Log` | `job/capabilities.py` | Logging capability (info, warning, error, debug) |
| `Invoke` | `job/capabilities.py` | Job invocation (call, parallel, schema) |
| `Prompt` | `job/capabilities.py` | User input collection (ask, confirm, choice, text) |
| `Perf` | `job/capabilities.py` | Performance marking (mark, mark_start, mark_end) |
| `State` | `job/capabilities.py` | Key-value state (get, set, delete, keys) |
| `JobContext` | `job/capabilities.py` | Frozen dataclass: name, trace_id, span_id, cwd, job_directory, invoke_depth, scope_id, metadata |
| `JobConfigView` | `job/` | Scoped config access for jobs |
| `TTY` | `job/capabilities.py` | Terminal-ownership capability (HARD: forces EXCLUSIVE) |
| `Live` | `job/capabilities.py` | Live-display channel (always injected, degrading) |
| `ShellError` | `job/capabilities.py` | Raised when a `Shell` command exits non-zero under `check=True`, on timeout, or when a `FailingResponder` sentinel appears. Carries the failing `ShellResult` |
| `FailingResponder` | `job/capabilities.py` | A `Responder` that also aborts (raises `ShellError`) when a `sentinel` regex appears in live output |
| `FreshnessVerdict` | `job/capabilities.py` | What a job's own `@job(cache=Fingerprint(..., decides=True))` decided — `state`, `key`, `recorded_value`, declared sources/generates, `source_map`. Exposed via the `Freshness` capability's `.verdict()` |
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
| `DEFAULT_SIGIL` | `plugin/` (`_types/input_modes.py`) | The empty-string sigil the shell's default (command) `InputMode` registers under |
| `SettingsSources` | `plugin/` (`_types/settings.py`) | Frozen dataclass: file names + precedence for a host app's settings store (`AppSettingsSchema.sources`) |
| `PromptSeverity` | `plugin/` (`_types/interactivity.py`) | Enum: visual severity for `PromptRequest.severity` — INFO, WARNING, DANGER, SUCCESS |

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
| `RunSurface` | `types/` (`_types/run_request.py`) | `Literal` of the 19 doors a run can enter through; the required, no-default `RunRequest.surface` field |
| `RUN_SURFACES` | `types/` (`_types/run_request.py`) | `frozenset[str]` of every `RunSurface` value, derived from the `Literal` via `get_args()` so the two cannot drift |
| `request_from_envelope` | `types/` (`_types/run_request.py`) | Parses a wire payload (`{"arguments": {...}, "scope_id": ..., "force": ...}`) into a `RunRequest` — the shared implementation for every out-of-process door |
| `wire_value` / `status_from_wire` | `types/` (`_types/outcome.py`) | The inverse pair translating a `RunStatus` to/from the lowercase status string a tool or HTTP response carries |
| `report_line` | `types/` (`_types/outcome.py`) | The one line `BLOCKED`/`REFUSED` owe a caller before their exit code/status is delivered; `None` for every other status |
| `ConfigFileRole` | `types/` (`_types/enums.py`) | Enum: BASE / OVERLAY / INERT — the role a discovered config file plays under the active environment (`ConfigFileInfo.role`) |
| `EnvironmentSource` | `types/` (`_types/enums.py`) | Enum: where the active environment name came from (`app.configuration.environment_source()`) |

### `testing/` — Test Helpers

| Symbol | File | Purpose |
|--------|------|---------|
| `TestRunContext` | `testing/builder.py` | Builder with `.create(...)` for minimal test setup |
| `CapturingLog` | `testing/doubles.py` | Records (level, message) tuples |
| `MockInvoke` | `testing/doubles.py` | Returns pre-configured results by job name |
| `AutoPrompt` | `testing/doubles.py` | FIFO response queue |
| `NoopPerf` | `testing/doubles.py` | Accepts all calls silently |
| `FakeShell` | `testing/shell.py` | Scripted, recording `Shell` capability double — matches a pattern→`ShellResult` table, raises loudly on an unmapped command |
| `FakeShellCall` | `testing/shell.py` | Frozen dataclass: one recorded `FakeShell` invocation (`argv`, `command`, `kwargs`) — appended to `FakeShell.calls` |
| `FakeStdout` | `testing/stdout.py` | In-memory `Stdout` capability double — `emitted` (objects passed to `emit()`), `writes` (raw `write()` payloads), `text` (rendered stream) |

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
| `main.py` | Entry point, arg routing → JobSources → CliAdapter.run(); the pre-boot intercepts (`--version`, `self doctor`) and first-run registration |
| `builtins.py` | The `builtin` command registry and every family's mount point |
| `scaffold/` | scaffold sub-command (Click + Jinja2) |
| `orchestrator.py` | Surface-resolution ladder (`resolve_surface`, `RenderSurface`) |
| `inline_tui.py` | Inline-TUI launch + the EXCLUSIVE handoff loop |
| `manifest.py` | The user-global registry of every `func` that has run (`install.json`). Voluntary, append-only, never discovers anything |
| `package_ops.py` | The half of self-management that needs a terminal: `refuse`, `announce`, `plan_or_exit`, the pending-update file, and `_call` — the one place this subsystem executes anything. Detection and command *planning* are public, in `app/packaging.py` |
| `self_cmd.py` | `builtin self` — `doctor`, `update`, `install`, `python`, `uv` |
| `plugin_cmd.py` | `builtin plugin` — `list`, `install`, `uninstall`; extension discovery across `functualize.*` entry-point groups |

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
| `OnFailure` | `_types/workflow.py` | Where control goes when a named step raises — `source`, `target` (or `END`), optional `when` predicate |
| `Notification` | `_types/workflow.py` | What a registered notifier is handed when a `Notify` declaration fires — `to`, `scope_id`, `workflow`, `status`, `node` |
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
