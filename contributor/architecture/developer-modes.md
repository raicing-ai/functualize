# Developer Modes Architecture

Comprehensive reference for all six developer modes used in the framework, mapped to the three-layer architectural model.

## The Mental Model

The framework supports six distinct entry points and bootstrapping strategies. All six paths converge at Layer 3 (Execution), but diverge significantly in how they reach that convergence.

## The Six Developer Modes

| Mode | Entry Point | Use Case | Bootstrap | Cache |
|------|-------------|----------|-----------|-------|
| **A** — Declared app | `FunctualizeApp.run()` | Developer-owned project with explicit job directories | Cached lazy boot (`lazy=True`, default); eager opt-in via `lazy=False` | ✅ Yes (default) |
| **B** — `func <job>` adhoc | `func deploy --env prod` | Cold-start one-shot execution from unfamiliar directory | Cache for routing + lazy boot (`lazy=True`); dispatch materializes ONLY the invoked job | ✅ Yes |
| **C** — `func` discovery | `func --help` / `func tui` | Exploring and browsing available jobs | Cache-backed name/metadata listing (no execution boot) | ✅ Yes |
| **D** — Single-file mode | `func file.py function_name` | Quick one-off on a specific known file | Direct import, no scan | ❌ No |
| **E** — Programmatic invoke | Inside job: `rc.invoke()` | Job orchestration within a workflow | Already registered, skip discovery | N/A |
| **F** — Direct execution | Test code: `engine.execute()` | Library embedders, test authors, internal use | Caller provides function ref | N/A |

## Layered Architecture Mapping

### Layer 1: Discovery & Metadata

**Purpose:** "What jobs exist? What do they need?"

**Input:** Job directories, module paths, metadata providers  
**Output:** `list[JobDescriptor]` — pure data, no side effects  
**Key Classes:** `CachedDirectoryScanProvider`, `StaticProvider`, `ResolutionPipeline`, `ModulePreFilter`  
**Location:** `_discovery/`

| Mode | Discovery Strategy | Discovery Cache Used | Scope |
|------|---|---|---|
| **A** | `_register_jobs_lazy()` → `CachedDirectoryScanProvider.list_jobs()` (default `lazy=True`); `scan_and_register_headless()` eager when `lazy=False` | ✅ Yes (default) | All `jobs_directories` at boot |
| **B** | Pre-boot `read_routing_names_from_cache()` for routing; execution boots the app with `lazy=True` (warm: zero imports) and materializes only the invoked job | ✅ Yes | `discover_job_directories(CWD)` |
| **C** | Cache-first name/metadata listing (`read_routing_names_from_cache()`, AST fallback) — no execution boot, no imports | ✅ Yes | Same as B |
| **D** | `full_import_and_extract(file)` — single file only | ❌ No | One file (no scan) |
| **E** | None — job already registered in running app | ❌ N/A | Already in registry |
| **F** | None — caller provides function directly | ❌ N/A | Caller owns reference |

**Mode A lazy boot (default):**

Mode A is cache-backed and lazy by default (`JobSources.lazy=True` → `app._lazy_boot`). `boot_standard()` wires a `CachedDirectoryScanProvider`, and `resolve_and_register_jobs()` calls `_register_jobs_lazy()`:
1. `CachedDirectoryScanProvider` loads the persisted `cache.json` (via ResourceLocator — `.functualize/` or XDG platform cache) at construction
2. `list_jobs()` reconciles disk vs cache — the *metadata* (descriptors) is served from `cache.json` without re-extracting schemas when the cache is valid
3. Return `list[JobDescriptor]` — serializable metadata, no live module objects
4. `register_descriptors()` registers each cache-only descriptor as a `LazyJobFunction` proxy (`_discovery/lazy_wrapper.py`) — **no module import at boot**. The engine materializes the entry (imports the ONE module, detects `config_class`, swaps the frozen `RegisteredJob` in both the engine registry and the JobRegistry mirror, runs deferred DI validation) on first use: `get_job()` / `execute()` / `materialize_job()`. Descriptors that carry a live function (cold boot, static providers) register it directly with a detected `config_class` — cold boot behaves exactly like the eager path, including boot-time DI validation.

Opt into deterministic eager boot with `FunctualizeApp(job_sources=JobSources(..., lazy=False))`: this routes to `scan_and_register_headless()`, importing every module at boot with boot-time DI validation — the documented escape hatch for users who need import-time side effects or all errors at boot.

**Mode B/C (`func` CLI) — lazy end to end:**

- **Routing/listing (both B and C):** `_cli/main.py` reads job/group names from `cache.json` via `read_routing_names_from_cache()` (AST scan fallback on cold cache) with zero module imports. This is what makes `func --help`, `func tui`, and mode detection fast.
- **Execution (Mode B, `func deploy`):** the handlers boot with `JobSources(..., lazy=True)`; once a job is selected, `_handle_job`/`_dispatch_group` call `engine.materialize_job(name)` (via `_materialize_for_dispatch`), importing **only the invoked job's module**, then wire the live function through `create_job_command` — full `Arg()`/`Option()`/`Stdin()` marker fidelity with a single import.

Mode D skips the registry entirely. It calls `full_import_and_extract(source_file)`, imports one module directly, extracts a `JobDescriptor`, and discards it — goes straight to execution.

### Layer 2: Loading & Wiring

**Purpose:** "Import code, resolve config, wire into a runner"

**Two paths:**
- Path A: Full boot (import all → Click tree, for --help and TUI)
- Path B: Selective (import one → execute immediately, fast path)

**Key Classes:** `CliAdapter` (builds Click tree from descriptors)  
**Location:** `app/adapters/`, `_app/boot.py`

The app's command group is a `click.Group`, exposed as `app.cli_command`
(renamed from the historical `typer_app` by convergence task B2c; typer itself
was removed earlier).

| Mode | Wiring Strategy | Lazy | Command Group Used |
|------|---|---|---|
| **A** | `register_discovered_jobs()` → `make_lazy_command()` from descriptors (default); eager `cli_command.command(fn)` only when `lazy=False` | ✅ Lazy (default) | Declared app's own group (`cli_command`) |
| **B** | Booted app with `lazy=True`; dispatch materializes the ONE target via `engine.materialize_job()` → `create_job_command` on the live fn | ✅ Lazy (single import) | Booted `func` app's group |
| **C** | No execution wiring — jobs listed from cache metadata for browse/help | N/A | — |
| **D** | None — direct to Layer 3 | N/A | No CLI group |
| **E** | None — already wired in host app | N/A | Host app's group |
| **F** | None — caller passes function directly | N/A | No CLI group |

Mode A's default lazy path uses `make_lazy_command(descriptor, app)` (`app/adapters/lazy_command.py` — the click-facing half lives in the adapter/delivery layer, keeping `_cli` on the public API):
- Reconstructs `inspect.Signature` from cached `FieldDescriptor` data (no import), honoring `positional` (click.Argument) and `short_flag` (click.Option) markers
- Registers a Click command with the synthetic signature
- On invocation: `engine.materialize_job(name)` imports the one module, then `engine.execute()`

**Layer separation (previously a known violation, now resolved):** the old `_register_module()` fused Layer 1 (import + extract + build descriptor) and Layer 2 (Click wiring) in one synchronous call. That function has been removed from production code. The layers are now split:
- Layer 1: `scan_and_register_headless()` (metadata only, no CLI wiring) and `CachedDirectoryScanProvider` (cached descriptors)
- Layer 2: `register_discovered_jobs()` / `CliAdapter` build Click commands from descriptors

`_register_module()` survives only as a test helper (`tests/discovery/test_group_by_module_attribute_transform.py`).

### Layer 3: Execution

**Purpose:** "Run the job with full lifecycle"

**Single path for ALL modes:**

```
Mode A:  Click parse → make_lazy_command → materialize (one module) → engine.execute()
Mode B:  materialize_job (one module) → create_job_command → Click parse → engine.execute()
Mode C:  same as B (TUI re-invokes CLI → same dispatch path)
Mode D:  execute_from_path() → engine.execute()
Mode E:  rc.invoke() → materialize on lookup → engine.execute()
Mode F:  caller → engine.execute() directly
```

**Convergence point:** `JobExecutionEngine.execute()`

- Builds `RunContext` (state machine: before_start → success/failure → teardown)
- Builds `JobConfigView` (wraps `ResolutionChain` with in-memory overrides)
- Fires `HookRegistry` lifecycle hooks
- Runs `MiddlewareStack`
- Runs `EventBus` instrumentation
- Calls the job function
- Returns `JobResult`

**Key Classes:** `JobExecutionEngine`, `RunContext`, `DIRegistry`  
**Location:** `_engine/`

## Convergence Architecture

```
┌─────────────────────────┐  ┌─────────────────────────┐
│ LAYER 1: Discovery      │  │ LAYER 2: Loading        │
│                         │  │                         │
│ Mode A (Lazy, default)  ├──► make_lazy_command       ├───┐
│ provider.list_jobs      │  │ (Lazy Click wiring)     │   │
│ Mode B exec (func, lazy)│  │                         │   │
│ materialize_job(name)   ├──► create_job_command      ├───┤  ┌───────────────────────┐
│ (imports ONE module)    │  │ (live fn, one import)   │   │  │ LAYER 3: Execution    │
│ Mode D (Single file)    │  │                         │   ├──►                       │
│ full_import_and_extract ├──► (Skip Click)            ├───┤  │ JobExecutionEngine    │
│                         │  │                         │   │  │ .execute()            │
│ Mode E/F (Programmatic) │  │                         │   │  │                       │
│ (Skip - already loaded) ├──► (Skip - already wired)  ├───┘  └───────────────────────┘
└─────────────────────────┘  └─────────────────────────┘
```

**Everything above the engine diverges. The engine itself is identical for all modes.**

## Known Gaps and Limitations

| Mode | Gap | Impact |
|---|---|---|
| **A/B/C** | Warm-cache Click trees render `datetime`/`date`/arbitrary custom parameter types as `str` (not reconstructable from the cached type string) | `--help` for a warm-cached job shows `TEXT` metavar for those params; dispatch (`func <job>`) is unaffected — it materializes and uses `create_job_command`. `Stdin()`, variadic `Arg()`, `Path`, `list[T]`, and `Optional[T]` ARE now rendered (cache-format v4) |
| **B/C** | Standalone app has no access to declared project's hooks/plugins | Middleware and event subscriptions on declared app don't fire for `func` |
| **D** | `execute_from_path()` passes `kwargs={}` to `engine.execute()` — invocation args captured but silently dropped | `func jobs/deploy.py deploy --env prod` loses `--env prod` |
| **E** | `rc.invoke()` depth limit is hardcoded to 10 — no configuration surface | Deep recursive job chains fail silently |
| **E/F** | No way to inject `WorkflowScope` from outside running context | Programmatic embedders can't participate in scope tracking |

> **Note:** the historical gaps are **resolved**: Mode A "no lazy boot / no cache written" (lazy cache-backed boot is the default), and Mode B "`func <job>` imports all modules" (dispatch now materializes only the invoked job — see [Lazy boot: materialize-on-demand](#lazy-boot-materialize-on-demand-measured)).

## Lazy boot: materialize-on-demand (measured)

`lazy=True` (the default) genuinely defers job-module imports: warm boot imports **zero** job modules; the first use of a job imports exactly **that one module**. This holds for Mode A (`app.execute`, `rc.invoke`, Click commands) and Mode B (`func <job>` dispatch).

**Mechanism (materialize-on-demand):**

1. Warm boot registers each cache-only descriptor as a `LazyJobFunction` proxy (`_discovery/lazy_wrapper.py`) in both the JobRegistry and the execution engine — no import.
2. The engine materializes an entry at its choke points — `get_job()`, the top of `execute()` (before any signature introspection, so `id(function)`-keyed resolution-plan/validator caches key on the real function), and the public `materialize_job(name)` used by CLI dispatch.
3. Materialization imports the module once (thread-safe), detects `config_class` from the real signature, swaps the frozen `RegisteredJob` in the engine registry **and** all registered mirrors (the app's JobRegistry — `add_registry_mirror`), and runs the deferred per-job DI validation.
4. Descriptors carrying a live function (cold boot, static providers) register directly with a detected `config_class` — cold boot is byte-for-byte the eager behavior, including boot-time DI validation.

**Environment guarantees under `lazy=True`** (verified): all extension points load at boot, independent of job-module imports —

| Extension kind | Source | Loaded when | Affected by `lazy`? |
|---|---|---|---|
| Entry-point plugin | `PluginSources.entry_point_group` | `boot_standard` "load plugins early" | ❌ No |
| Explicit plugin | `PluginSources.explicit_plugins` | `bootstrap` | ❌ No |
| File-based plugin | `[tool.functualize] plugins_directories` or `.functualize/plugins/` (convention) | `load_all` Phase 1b (`_discover_from_files`) | ❌ No |
| Domain SDK | `functualize.domains` entry points (+ each domain's `entry_point_group`) | `boot_standard` step 4b (`boot_domain_registry`) | ❌ No |

App hooks/middleware (`@app.on_*`, `@app.run_middleware`, incl. job-scoped forms) register at decoration time in the app module, before jobs. `rc.invoke("sibling")` resolves lazy entries by name; `rc.invoke(<callable>)` resolves unmaterialized proxies via a module/qualname metadata fallback (`invoke.py::_resolve_job_name`).

**Semantics of `lazy=True` (and the escape hatch):**

- A non-invoked job module's import-time side effects run at **first invocation**, not at boot (cold boot still imports everything once to build the cache).
- DI-binding errors for warm-cached jobs surface at **first use** (`DIValidationError` from materialization) instead of at boot. Cold boot and `lazy=False` validate at boot exactly as before.
- Materialization import failures raise `JobMaterializationError` (chains the original error); CLI dispatch prints it and exits 1.
- **Escape hatch:** `JobSources(lazy=False)` restores fully eager boot — all modules imported and DI-validated at boot.

**Measured** (60 synthetic modules × 30 ms import cost each, fresh process per run):

| Scenario | Boot | Job modules imported |
|---|---|---|
| Before this refactor (warm, any mode) | ~2080 ms | 60 / 60 |
| Cold boot (builds cache) | ~2010 ms | 60 / 60 (required for extraction) |
| **Warm boot, `lazy=True`** | **~125 ms** | **0 / 60** |
| Warm boot + `app.execute("job5")` | ~114 ms + ~32 ms | exactly 1 |
| Warm `func job7 --x 9` (subprocess, end-to-end) | ~0.5 s total (vs ~2.5 s cold) | exactly 1 |
| `lazy=False` escape hatch | ~2000 ms | 60 / 60 (by design) |

Guardrail tests: `tests/integration/test_lazy_true_engine_materialization.py` (app-level zero-import warm boot, single-import invocation, config-injection regression, deferred DI), `tests/cli/test_lazy_dispatch_single_import.py` (CLI single-import dispatch), `tests/execution/test_lazy_materialization.py` (proxy + engine units).

> **Historical note:** before 2026-07, `lazy=True` did *not* defer imports — `register_descriptors()` eagerly imported every module via the since-removed `make_lazy_job_function()` to satisfy three real-signature consumers (boot-time DI validation, `create_job_command`, invoke resolution plans), and the `func` CLI additionally forced `lazy=False` because its dispatch read a live `descriptor.function`. The materialize-on-demand engine (above) removed both constraints. A pre-existing bug fixed along the way: lazy-registered jobs had `config_class=None`, so `rc.invoke()` of a job with a Pydantic config param never injected its config.

## Mode Decision Tree

Use this tree to determine which mode fits your use case:

```
                   [ What do you want to do? ]
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
   [ Own the         [ Cold-start on      [ Testing /
     project? ]       unknown CWD? ]      Embedding? ]
    /       \          /      \               /    \
  YES       NO      YES       NO           PROG   DIRECT
   │         │       │        │              │      │
   ├─────┐   └─┬─┐   │        │              │      │
   │     │     │ │   │        │              │      │
   ▼     ▼     ▼ ▼   ▼        ▼              ▼      ▼
  [ How?] [File?] [Browse Mode Mode         Mode  Mode
   │      │       │  or Run?]  E     F
   │      │       │     │  │
  CLI    rc.     No   Yes  │
  │     invoke() │    │    │
  │      │      │    ▼    │
  │      │      │   Mode  │
  │      │      │    B    │
  │      │      ▼         │
  │      │    Mode D      │
  │      │               │
  │      └──────┬────────┘
  │             │
  └─────┬──────┘
        │
    Mode A / Mode E / Mode F
```

## Summary Table

| | Mode A | Mode B | Mode C | Mode D | Mode E | Mode F |
|---|---|---|---|---|---|---|
| **Entry point** | `myapp run()` | `func <job>` | `func --help / tui` | `func file.py fn` | `rc.invoke()` | `engine.execute()` |
| **Layer 1: Discovery** | Cache + lazy (default) | Cache routing + lazy boot | Cache listing | Single file | Skip | Skip |
| **Cache used** | ✅ (default) | ✅ | ✅ | ❌ | N/A | N/A |
| **Layer 2: Wiring** | Lazy wrappers (default) | Materialize ONE + live wiring | List only | Skip | Skip | Skip |
| **Layer 3: Execution** | `engine.execute()` | `engine.execute()` | `engine.execute()` | `engine.execute()` | `engine.execute()` | `engine.execute()` |
| **Plugin environment** | Declared app plugins | Standalone app plugins | Standalone app plugins | Standalone app plugins | Inherits from host | Inherits from caller |
| **Config source** | App's `ResolutionChain` | CWD-discovered chain | CWD-discovered chain | CWD-discovered chain | Host app's chain | Caller's app chain |
| **Known issues** | Warm --help lacks Stdin/variadic markers | Plugin/hook isolation from declared apps | Same as B | Args dropped | Depth hardcoded | Scope not injectable |

## References

- **Three-layer model:** See `contributor/architecture/overview.md` for high-level architecture and audience separation
- **Boot sequence:** See `contributor/architecture/boot-sequence.md` for FunctualizeApp initialization order and performance budgets
- **Performance:** See `contributor/reference/performance.md` for boot phase budgets and plugin import constraints
- **Layer rules:** See `contributor/reference/layer-rules.md` for import constraints and peer-layer communication patterns
