# Module Catalog

Detailed module catalog with responsibilities and dependencies. See `dependencies.md` for the import matrix and `overview.md` for the layer model.

## Public API Surface

### `app/` — Application Construction

| Symbol | Purpose |
|--------|---------|
| `FunctualizeApp` | Public facade, delegates to `_app/impl.py` |
| `FallbackCommand` | Fallback command hook |
| `DiscoveryConfig` | Discovery configuration dataclass |
| `JobSources` | Frozen dataclass: where jobs come from |
| `ConfigSources` | Frozen dataclass: where config comes from |
| `PluginSources` | Frozen dataclass: plugin discovery settings |
| `ExecutionConfig` | Frozen dataclass: execution params (max_invoke_depth) |
| `SessionOverlaySource` | Session-scoped config overlay source |
| `classic()` / `twelve_factor()` / `env_only()` / `remote_first()` | Preset factory functions |
| `get_perf_timeline()` | Access the active `PerfTimeline` |
| `CliAdapter` (`app/adapters/cli.py`) | Built-in CLI delivery (Click wiring) |
| `TuiAdapter` (`app/adapters/tui.py`) | Built-in TUI delivery |
| `make_lazy_command` (`app/adapters/lazy_command.py`) | Click command from cached metadata (warm boot, no job import) |
| `wants_stdout_surface` (`app/adapters/surface_gate.py`) | Direct-run StdoutSurface gate shared by both command paths |

### `job/` — Job Author API

`RunContext`, `Log`, `Invoke`, `Prompt`, `Perf`, `State`, `TTY`, `Live`, `JobContext`, `JobConfigView` (capabilities + facade), plus parameter-annotation helpers `Arg`, `Option`, `Stdin`, `JobMetadataAnnotation`, decorators `job_metadata`, `suppress_live`, `surface_hint`, and decorator factories `_make_global_only_decorator`, `_make_hook_decorator`, `_make_middleware_decorator`.

### `plugin/` — Plugin Author API

Core protocols: `EventBus`, `HookEvent`, `StructuredEvent`, `JobProvider`, `JobTransform`, `Job`, `AdapterPlugin`, `Surface`, `PromptCollector`, `LiveConstruct`, `PromptRequest`, `PluginMetadata`, `PluginWithShutdown`, `Source`, `FormatProvider`.
Domain/UI extension protocols: `discover_domains`, `scan_domain_providers`, `BarRenderer`, `DisplayProvider`, `HeaderItemProvider`, `InteractiveContent`, `PanelProvider`, `PostRunStampProvider`, `SessionState`, `SignatureProvider`, `StatusBarItemProvider`, `ThemeProvider`, `validate_extension_id`.

### `ui/` — Job-Owned / Display UI Building Blocks (`[cli]` extra)

`TextualApp` (base class for `tty: TTY` jobs), `StdoutSurface` + `stdout_live_session` (rich STDOUT rendering for direct runs), `Display` (optional display-provider base; nests the `Display.DrillDown` message), `PromptModal`/`MODAL_CSS`, `FuncEvent`.

### `types/` — Shared Types

`JobResult`, `JobDescriptor`, `FieldDescriptor`, `RunStatus`, `RunType`, `JobPhase`, `CacheInfo`.

### `testing/` — Test Helpers

`TestRunContext` (builder), `CapturingLog`, `MockInvoke`, `AutoPrompt`, `NoopPerf` (doubles).

### `workflow/` — Declarative Workflow Graphs

`workflow` (the `@workflow(steps=..., edges=...)` decorator), `Step`, `Edge`, `ConditionalEdge`, `END`, `_EndSentinel`. Validates the step graph at decoration time (duplicate names, unknown refs, conditional-edge target maps).

---

## Internal Implementation

### `_types/` — Shared Vocabulary (No Logic)

Only frozen dataclasses, Enums, Protocol definitions. `descriptors.py` (`JobDescriptor` et al.) is the single highest-fan-in internal type module (21 importers).

### `_primitives/` — Foundation Utilities

| Module | Contains |
|--------|----------|
| `di.py` | `DIRegistry`, `ResolutionPlan`, `Provide` marker, `MissingProviderError` |
| `locator.py` | `ResourceLocator` (fluent path-discovery builder) |
| `middleware.py` | `MiddlewareChain[TContext, TResult]` (generic yield-based) |
| `pre_filter.py` | **File level**: `ModulePreFilter` protocol + `AllOf`/`AnyOf`/`NoneOf` combinators + built-ins (incl. `DisplayClassPreFilter`, the display-only-module admission signal) + `extract_function_decorators()` (AST decorator names, feeds the job level) |
| `job_filter.py` | **Job level**: `JobFilter`/`JobCandidate` protocols, `RawJobCandidate`, `JobPrefixFilter`/`JobPostfixFilter`/`JobDecoratorFilter`, `AllJobFilters` — the `require_job_*` family, judged per function |
| `cache_format.py` | Discovery-cache format: `CACHE_VERSION`, `PreFilterDecision`, `DisplayCacheEntry`, `resolve_cache_path()` (stdlib-only; shared by writer + fast-path readers) |
| `display_detection.py` | `is_display_provider`/`find_display_providers` duck-type seam, shared by the job scan and the TUI (via `app.utils` re-exports) |
| `lazy.py` | `lazy_cached` descriptor |
| `resilient.py` | `resilient(iterable, on_error)` generator |
| `modules.py` | `iter_module_files(directory)` |

### `_events/` — Cross-Cutting

`bus.py` (`EventBus`, trie-based topic router), `hooks.py` (`HookRegistry`, lifecycle interceptors — 19 importers), `tracing.py` (`PropagationContext`), `perf.py` (`PerfTimeline`, `Phase`, `PerfReport`).

### `_discovery/` — Job Finding

`providers.py` (`DirectoryScanProvider`, `StaticProvider`, `EntryPointProvider`), `transforms.py` (`NamespaceTransform`, `GroupByModuleAttributeTransform`), `cached_provider.py` (`CachedDirectoryScanProvider` — the single persisted discovery cache; format shared via `_primitives/cache_format.py`), `sync.py` (`extract_module` — the import+extract pass the cached provider uses), `filter_factory.py` (`build_pre_filter_from_config` file level, `build_job_filter_from_config` job level), `hierarchy.py` (child-project composition), `pipeline.py` (`ResolutionPipeline`).

### `_config/` — Configuration Resolution

`chain.py` (`ResolutionChain`), `sources.py` (`CliSource`, `EnvSource`, `FileSource`, `RemoteSource`, `DefaultSource`), `job_config.py` (`JobConfigView` + validation — 13 importers), `resolved_field.py` (`ResolvedField` / `resolve_job_fields` — the seam `builtin info --job` and `builtin env` both read, so a display cannot disagree with the run; needs a live model, which is why the TUI does *not* read it — ADR-008 A1), `errors.py` (10 importers), `providers/` (`TomlFormatProvider` — the only provider registered by default; `IniFormatProvider` is in-tree and plugin-registered only, ADR-007).

### `_engine/` — Execution Lifecycle

`executor.py` (`JobExecutionEngine`), `middleware.py`, `context.py` (`ExecutionContext`), `resolution.py` (`ResolutionPlan`/DI binding), `result.py` (`RegisteredJob` internals), `capabilities/invoke.py` (`Invoke`, ~150 LOC), `capabilities/workflow.py` (`WorkflowTracker`, ~100 LOC), `capabilities/runcontext.py` (15 importers — the concrete `RunContext` capability wiring; only `TYPE_CHECKING`-time reference to `_config.job_config`).

### `_plugins/` — Plugin Loading

`loader.py` (`PluginLoader`: discovery + topological sort + loading), `config.py` (`PluginConfigRegistry`).

### `_gate/` — Gated Workflow Step Resolution

`_strategy.py` (`GateStrategy` StrEnum: `RESOLVE`, `PROMPT`, `AI_INBOUND`), `_resolver.py` (`GateResolver` Protocol, `ResolveResolver` default impl building a pydantic model from the config chain), `_context.py` (`GateContext` frozen dataclass), `_registry.py` (`GateRegistry`: strategy/preset registry + resolution algorithm, composed into `FunctualizeApp`). Pairs with public `workflow/` — `workflow/` declares the step graph, `_gate/` resolves individual paused steps.

### `_app/` — Composition Root

`boot.py` (boot orchestration — the only place peer layers get wired together), `impl.py` (`FunctualizeApp` internal methods — **highest fan-in module in the codebase, 30 importers**), `decorators.py` (13 importers), `state.py` (`AppState`).

### `_cli/` — CLI + TUI Delivery

`main.py` (entry point — arg routing → `JobSources` → adapter `.run()`), `builtins.py` (`cache`, `version` commands), `scaffold/` (Click + Jinja2 project scaffolding), `dispatch.py` (`detect_mode` — `Mode.SINGLE_FILE|BUILTIN|JOB|GROUP|BARE|UNKNOWN`), `data/pending_execution.py` (10 importers).

#### `_cli/tui/` — Full-Screen TUI Subsystem (largest single subsystem)

Composition: `app.py` (composition root, wires state machines and delegates to plain modules), `panel_host.py` (BreadcrumbHeader + ContentSwitcher).

| Concern | Files |
|---|---|
| Command input | `bar.py` (SmartBar + `BarReadiness` FSM), `smart_bar_autocomplete.py`, `functualize_autocomplete.py`, `cli_arg_parser.py` |
| Job execution wiring | `job_execution.py` (token→kwargs, launches as Textual worker), `job_listing.py`, `missing_args.py` |
| Config inspection/editing | `chain_resolution.py`, `config_diff.py` (pure logic, no Textual dep), `config_target_discovery.py`, `diff_view_widget.py`, `editable_table.py`, `path_field_editor.py`, `path_suggestion_scanner.py` |
| Panels | `panels/job_browser.py`, `panels/config_table.py` (**10 importers — highest fan-in TUI leaf**), `panels/config_files.py`, `panels/ring.py` (zero-Textual panel-ID ordering) |
| Focus/keys | `focus.py` (pure-Python observer), `insert_mode.py`, `key_handler.py` (routes by `(FocusMode, FocusZone)`), `models/focus_state.py` (4-mode FSM) |
| Display chrome | `display_affinity.py`, `display_chrome.py`, `display_provider_discovery.py`, `display_slot.py` (mounted; hosts drill-down view stack + `current_interactive_widget`), `theme_manager.py`, `bar_items.py` (plugin header/status bar items — pure logic, no Textual dep) |
| Live surfaces | `panel_live_zone.py` (PANEL binding for `live: Live`; pushes per-run), `live_panel_widget.py` (`live.panel` construct as an interactive general-ring panel), `thread_marshal.py` |
| Modals | `shortcut_save_modal.py` (Ctrl+S, `ModalScreen[str \| None]`), `modals/` (empty package, reserved) |
| Misc widgets | `breadcrumb_header_widget.py`, `dynamic_footer.py`/`dynamic_footer_widget.py`, `preflight_summary.py`, `settings_panel.py`/`settings_validator.py`, `descriptor_fields.py`, `field_priority.py`, `type_hint_formatter.py`, `sync.py` (state↔SmartBar sync, no Textual dep) |
| Ring state | `models/panel_ring_controller.py`, `models/ring_models.py` — declared but unused; the live ring is a plain `_active_ring: str \| None` on `FunctualizeInlineTUI` (see `tui-architecture.md`) |

See `contributor/guides/tui-panels.md` for the hard rule every panel widget must follow (`min-height` in `DEFAULT_CSS`) and the deferred-population pattern.

---

## Official Plugins (`plugins/`)

| Package | Type | Purpose |
|---|---|---|
| `functualize-ai` | Domain SDK (protocols) | AI interaction capabilities |
| `functualize-ai-pydantic` | Implementation | PydanticAI-backed AI plugin |
| `functualize-inline` | Implementation | Textual inline interactivity (prompts within terminal flow) |
| `functualize-flow-viz` | Implementation | Inline flow visualization during job execution |
| `functualize-state` | Domain SDK (protocols) | State persistence / execution tracking protocols |
| `functualize-state-sqlite` | Implementation | SQLite-backed state persistence |
| `functualize-tasks` | Domain SDK (protocols) | Task management capabilities |
| `functualize-tasks-local` | Implementation | Local state-backed task storage |
| `functualize-http` | Delivery adapter | HTTP server adapter (asyncio-based) |
| `functualize-lambda` | Delivery adapter | AWS Lambda adapter (fat/thin patterns) |
| `functualize-mcp` | Delivery adapter | Exposes jobs as MCP tools via FastMCP |

All 13 are `uv` workspace members (`plugins/*`), pinned via `[tool.uv.sources]` in the root `pyproject.toml`.
