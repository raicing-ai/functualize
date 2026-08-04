# Key Data Flow Paths

## 1. Boot Sequence (`FunctualizeApp` initialization)

Fixed order, do not reorder (see `contributor/architecture/boot-sequence.md` for the authoritative version):

| Step | Phase | Budget |
|---|---|---|
| 1 | `core_infra` — HookRegistry, DIRegistry, JobExecutionEngine instantiated | 50ms |
| 2 | `provider_registry` — built-in TOML + INI format providers registered | 10ms |
| 3 | `observability` — EventBus, MiddlewareStack created (before plugins, so plugins can subscribe) | 50ms |
| 4 | `plugins` — entry-point + file-based plugins loaded via `PluginLoader` (topological sort) | 200ms |
| 5 | `config_entry_points` — format/remote provider entry points discovered | 50ms |
| 6 | `config_resolution` — `ResourceLocator` + `ResolutionChain` built once | 100ms |
| 7 | — `AFTER_CONFIG_INIT` hook fires | — |
| 8 | `job_registration` — providers from `JobSources` wired | 50ms |
| 9 | `children` — child `FunctualizeApp` projects mounted | 50ms |
| 10 | `app_ready` — `APP_READY` hook fires, boot complete | — |
| 11 | `registry_frozen` — DI registry frozen, `REGISTRY_FROZEN` emitted | — |
| 12 | `adapter.run()` — active adapter takes over delivery | — (TUI: 20ms) |

Total boot budget: 500ms (CI-enforced via `tests/perf/test_startup_budget.py`). Static wiring (all sources explicit) skips steps 2, 5, 6, 8, 9 → boot in <5ms.

## 2. Job Execution Lifecycle

All invocation modes (CLI, `rc.invoke()`, `func` standalone, HTTP, Lambda, MCP) converge on one path:

```
Trigger → adapter.execute() call
  │
  ▼
JobExecutionEngine.execute(job_name, function, kwargs)
  1. Get ResolutionPlan (cached by id(function))
  2. Build per-invocation capabilities (Log, Invoke, Prompt, Perf, State)
  3. Resolve DI params from registry
  4. Construct RunContext if function declares it
  5. Fire PRE_EXECUTE hooks       (can BLOCK or MODIFY kwargs)
  6. Fire BEFORE_JOB hooks        (observe only)
  7. Run middleware chain, pre-phase (yield-based generators)
  8. Call job function(**resolved_kwargs)
  9. Run middleware chain, post-phase
 10. Fire AFTER_SUCCESS or AFTER_FAILURE hooks
 11. Fire ON_TEARDOWN hooks       (always)
 12. Return JobResult
```

**Resolution priority** for function parameters: DI > RunContext > Config > Default value > Skip.
Resolution plans are computed once (during discovery) and cached by `id(function)` — subsequent calls skip `inspect.signature()`.

**Global `func` CLI routing** (`_cli/main.py`) classifies each invocation *before*
boot via `detect_mode()` (`.py` file > builtin > job group > job name > alias >
`UNKNOWN`). `GROUP` and `UNKNOWN` both boot the full app, then resolve the target
in `_dispatch_group(app, …)`:

```
func <token> …
  detect_mode() → GROUP  → _handle_group  → boot → _dispatch_group(app, …)
                → UNKNOWN → _handle_job    → boot → (job not found)
                                                   → _dispatch_group / ungrouped
                                                     plugin command / error
```

`_dispatch_group` merges discovered job groups with `app.get_plugin_commands()`
(plugin commands register at `APP_READY`, so they are invisible pre-boot — e.g.
the `mcp` group). This is why `func mcp serve` works despite global `func` having
no `CliAdapter`. Job wins over a plugin command on an exact name conflict; plugin
commands execute through an ad-hoc single-command Click group (same path as the
scaffolded-project `CliAdapter`).

## 3. Three-Layer Caching

```
Layer 1: Provider Persistence (disk)
  CachedDirectoryScanProvider → .functualize/cache.json (mtime → sha256 → dep-hash invalidation)

Layer 2: Kernel Facade Memo (in-memory)
  app.get_jobs() memoized; invalidated by app.add_job_provider()

Layer 3: Engine Resolution Plan (in-memory)
  ResolutionPlan cached by id(function); never invalidated (signatures immutable in-process)
```

The `_cli/main.py` fast path additionally reads **routing names** (job/group names) from the same `cache.json` file (resolved via `cache_format.resolve_cache_path`) to skip a cold-boot AST scan for `Mode` detection on every invocation.

## 4. Hook Event Timeline

| Event | When | Can modify? |
|---|---|---|
| `JOB_REGISTERED` | After discovery adds a job | No |
| `APP_READY` | Boot complete, before freeze | Last chance for DI registration |
| `REGISTRY_FROZEN` | After DI freeze | No |
| `PRE_EXECUTE` | After config resolved, before job runs | Yes — BLOCK or MODIFY kwargs |
| `BEFORE_JOB` | Just before function call | No |
| `AFTER_SUCCESS` / `AFTER_FAILURE` | Job returned / raised | No |
| `ON_TEARDOWN` | Always | No |
| `INVOKE_START` / `INVOKE_END` | Around `rc.invoke()` child execution | No |
| `ON_SCOPE_CREATED` | `WorkflowScope` created | No |
| `TUI_STARTED` | TUI app launches | No |

## 5. Gated Workflow Step Resolution

For jobs decorated with `@workflow(steps=..., edges=...)` (public `functualize.workflow`):

```
workflow graph declared → _validation._validate_workflow_graph() at decoration time
  │  (rejects duplicate step names, unknown step refs, invalid ConditionalEdge targets)
  ▼
Step reached during execution that needs external input
  │
  ▼
GateContext built (frozen dataclass: resolver inputs)
  │
  ▼
GateRegistry.resolve() dispatches by GateStrategy:
  RESOLVE    → ResolveResolver builds a pydantic model from the config chain (no human interaction)
  PROMPT     → delegates to the active PromptCollector.collect() (interactive)
  AI_INBOUND → external/agent-driven resolution
  │
  ▼
Step result feeds back into the workflow graph → next Edge/ConditionalEdge
```

## 6. Interactivity Data Flow (Input/Output Decoupling)

The engine is output-agnostic — it emits lifecycle events, adapters render them:

```
Input Providers                    Engine (pivot point)              Output Renderers
─────────────────                  ─────────────────────             ──────────────────
Programmatic kwargs  ─┐                                          ┌─ Silent (return value)
CLI (Click parse)    ─┤                                          ├─ Stdout/Rich panels
Auto TUI form         ┼─► engine.execute() ──► emits events ────►┼─ Inline Textual
Custom Input TUI      ─┘                                         ├─ Full-screen TUI (DataTables)
                                                                  └─ External (webhooks/Slack)
```

Two one-method protocols decouple the engine from any specific UI: `Surface`
(`handle_event(event)` — the engine fans every non-framework event out to every
registered surface) and `PromptCollector` (`collect(request) -> PromptResponse`
— one active collector answers `rc.prompt_*()`). An object may satisfy both.
Exceptions inside `handle_event` are swallowed with a warning — they never
interrupt job execution or starve peer surfaces. See
`contributor/architecture/interactivity-model.md`.

## 7. TUI SmartBar Data Flow (full-screen TUI)

```
User keystrokes → bar.py (SmartBar Input + BarReadiness FSM)
   │
   ▼
cli_arg_parser.py tokenizes (--key value / -short / bare args)
   │
   ▼
job_execution.py resolves tokens → kwargs, cross-checks missing_args.py
   │
   ▼
run_job() launches execution as a thread worker (run_worker(..., thread=True))
   │
   ▼
preflight_summary.py / preflight_widget.py show resolved config when SmartBar is "green"
   │
   ▼
engine.execute() (same path as CLI/programmatic — see §2)
   │
   ▼
Results rendered into panels/job_browser.py, panels/config_table.py, dynamic_footer.py
```

`sync.py` and `config_diff.py` keep the SmartBar text and config panels consistent with pure-Python state (no Textual import), enabling unit testing without a running app. See `contributor/architecture/tui-architecture.md` for the full keybinding map and panel ring structure — there is no separate argument-form modal; missing-argument handling stays inline in the SmartBar/pre-flight flow.
