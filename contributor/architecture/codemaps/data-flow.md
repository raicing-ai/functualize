# Key Data Flow Paths

## 1. Boot Sequence (`FunctualizeApp` initialization)

Fixed order, do not reorder (see `contributor/architecture/boot-sequence.md` for the authoritative version):

| Step | Phase | Budget |
|---|---|---|
| 1 | `core_infra` — HookRegistry, DIRegistry, JobExecutionEngine instantiated | 50ms |
| 2 | `provider_registry` — built-in TOML format provider registered; `IniFormatProvider` needs a plugin (ADR-007) | 10ms |
| 3 | `observability` — EventBus, MiddlewareStack created (before plugins, so plugins can subscribe) | 50ms |
| 4 | `plugins` — entry-point + file-based plugins loaded via `PluginLoader` (topological sort) | 200ms |
| 4b | `domains` — discover domain SDKs through `functualize.domains` | included |
| 5 | `config_entry_points` — format/remote provider entry points discovered | 50ms |
| 6 | `config_resolution` — active environment + `ResourceLocator` + `ResolutionChain` built once | 100ms |
| 7 | — `AFTER_CONFIG_INIT` hook fires; max invoke depth resolved | — |
| 7c | `children` — child projects discovered and wired into the resolution pipeline | 50ms |
| 8 | `job_registration` — providers resolve and register jobs; declarations validated | 50ms |
| 9 | `app_ready` — `APP_READY` hooks fire after all boot steps | — |
| 9b | `di_validation` — report unsatisfiable job declarations | — |
| 10 | `registry_frozen` — DI registry frozen, `REGISTRY_FROZEN` emitted | — |
| delivery | `adapter.run()` — active adapter takes over after construction | — (TUI: 20ms) |

Total boot budget: 500ms (CI-enforced via `tests/perf/test_startup_budget.py`).
Static wiring (all sources explicit) uses a separate zero-discovery path: it
builds minimal registries, uses the supplied resolution chain, loads only
explicit plugins/jobs, skips entry-point/config/file/child discovery, then
still validates declarations, fires `APP_READY`, validates DI, and freezes the
registry. Its target is <5ms; requested dotenv loading is its one filesystem-I/O
exception.

## 2. Job Execution Lifecycle

All invocation modes (CLI, `rc.invoke()`, `func` standalone, HTTP, Lambda, MCP) converge on one path. The concise list below highlights the persistence-relevant boundaries; the authoritative twenty-step ordering and constraints live in `contributor/reference/execution-lifecycle.md`.

```
Trigger → adapter builds RunRequest
  │
  ▼
FunctualizeApp.execute(request) → JobExecutionEngine.run(request)
  1. Resolve the registered job and establish/reuse WorkflowScope
  2. Open the best-effort run record in the current RunStore
  3. Execute the authoritative twenty-step lifecycle
  4. Close the run record on every lifecycle exit
  5. Return JobResult
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
Programmatic request ─┐                                          ┌─ Silent (return value)
CLI (Click parse)    ─┤                                          ├─ Stdout/Rich panels
Auto TUI form         ┼─► app.execute(RunRequest) ─► events ────►┼─ Inline Textual
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
cli_arg_parser.py tokenizes — `tokenize_bar_text`, shlex-based, the one
inverse of what the emitters quote
   │
   ▼
`resolve_tui_command` walks the tokens as a *path* (`deploy web run`),
consuming any group's flags mid-path → (job_name, args, group_values)
   │
   ▼
job_execution.py turns `resolution.args` — the job's OWN tokens — into kwargs
   │
   ▼
run_job() launches execution as a thread worker (run_worker(..., thread=True))
   │
   ▼
preflight_summary.py shows resolved config when SmartBar is "green"
   │
   ▼
app.execute(RunRequest) (same path as CLI/programmatic — see §2)
   │
   ▼
Results rendered into panels/job_browser.py, panels/config_table.py, dynamic_footer.py
```

`sync.py` and `config_diff.py` keep the SmartBar text and config panels consistent with pure-Python state (no Textual import), enabling unit testing without a running app.

**The flow above runs backwards too, and that direction is where the defects
live.** A panel edit rebuilds the bar: `sync.py`'s `build_command_line` is the
only emitter, and `emit(resolve(text)) == text` is the property that keeps the
two directions honest. Two things it needs from its caller — both were wrong
once (ADR-009 decision 1, and its amendment):

- the values must be **partitioned** on `FieldDef.group_path` first. A group's
  flag handed in as one of the job's is emitted after the job, where the walk
  reads it as the job's own — no error, no group value, wrong run.
- a value the user typed must carry `edit_origin`, or a reset silently does
  nothing.

`missing_args.py` is **not** in the live path despite the name: readiness and
"what is missing" are answered by `SmartBar.evaluate`. See `STATUS.md`
follow-up 13. See `contributor/architecture/tui-architecture.md` for the full keybinding map and panel ring structure — there is no separate argument-form modal; missing-argument handling stays inline in the SmartBar/pre-flight flow.

## 8. Runtime Persistence: Current and Target Flow

Current code fans semantic workflow operations through document-oriented stores:

```text
engine / workflow / state / CLI / MCP
          |
ScopeStore + RunStore + ScopeStateStore + FreshStore + ShellHistoryStore
          |
StoreSubstrate(read/write/lock/clear/delete/describe)
          |
JsonFileSubstrate OR SQLiteSubstrate(documents[key,payload,revision])
```

The proposed flow replaces that broad document seam for authoritative runtime
truth while retaining document storage for genuinely document-shaped derived or
delivery-local data:

```text
engine + workflow orchestration
          |
RuntimeUnitOfWork
          |
WorkflowRepository + RunRepository + InteractionRepository + OutboxRepository
          |
one boot-selected RuntimePersistenceProvider
          |
normalized SQLite (single host) OR network SQL (multi-host)
```

Transitions, emitted-event rows, and outbox rows commit in one short unit of
work; EventBus notification follows commit. A transaction never wraps a job
body or external effect. The C4 views, transaction boundaries, schema, and
migration sequence are canonical in the
[`runtime-persistence` research package](../research/runtime-persistence/README.md).
