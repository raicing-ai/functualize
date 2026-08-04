# Architecture Overview

!!! note "For End Users and Job Authors"
    For a more detailed, diagram-rich version of this content oriented toward job authors and plugin developers, see `docs/guides/architecture.md`. That guide explores the mental model, data flow, and adapter layer from an end-user perspective.

## The Mental Model

Functualize is a **job execution framework** with three concerns:

1. **Discover** what jobs exist and what they need
2. **Execute** them with structured lifecycle, DI, and config
3. **Deliver** results through pluggable surfaces (CLI, HTTP, Lambda, TUI)

The core insight: the execution engine is delivery-agnostic. It doesn't know or care whether a job was triggered by a CLI command, an HTTP request, or a Lambda event. Adapters handle that translation.

## Audience Separation

The codebase separates imports by who needs them:

```
┌─────────────────────────────────────────────────────────────────┐
│  JOB AUTHORS (the 80% case)                                     │
│                                                                  │
│  from functualize.job import RunContext, Log, Invoke, Prompt     │
│  from functualize.types import JobResult, RunStatus              │
│  from functualize.testing import TestRunContext, CapturingLog    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  PLUGIN AUTHORS (the 15% case)                                   │
│                                                                  │
│  from functualize.plugin import EventBus, JobProvider            │
│  from functualize.plugin import AdapterPlugin, Surface            │
│  from functualize.app import FunctualizeApp, JobSources          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  FRAMEWORK CONTRIBUTORS (the 5% — you)                           │
│                                                                  │
│  from functualize._engine.executor import JobExecutionEngine     │
│  from functualize._primitives.di import DIRegistry               │
│  from functualize._discovery.cache import CachedDirectoryScan... │
│                                                                  │
│  Underscore prefix = internal. Users must never import these.    │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
src/functualize/
├── app/              PUBLIC — Application construction + built-in adapters
├── job/              PUBLIC — Job author API (RunContext, capabilities)
├── plugin/           PUBLIC — Plugin author API (EventBus, protocols)
├── types/            PUBLIC — Shared types (JobResult, JobDescriptor, enums)
├── testing/          PUBLIC — Test helpers (TestRunContext, doubles)
├── workflow/         PUBLIC — Workflow definition API (@workflow decorator, Step/Edge types)
│
├── _types/           INTERNAL — Shared vocabulary (only dataclasses, enums, protocols)
├── _primitives/      INTERNAL — Zero-dep utilities (DI, ResourceLocator, MiddlewareChain)
├── _events/          INTERNAL — Cross-cutting (EventBus, HookRegistry, PerfTimeline)
├── _discovery/       INTERNAL — Job finding + caching
├── _config/          INTERNAL — Configuration resolution
├── _engine/          INTERNAL — Execution lifecycle
├── _plugins/         INTERNAL — Plugin loading machinery
├── _app/             INTERNAL — Composition root (wires everything together)
├── _gate/            INTERNAL — Gate resolution for workflow input pauses
└── _cli/             INTERNAL — `func` CLI delivery (uses public API only)
```

## The Three Layers

Every job passes through three layers with strict separation:

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: Discovery & Metadata                                   │
│                                                                  │
│  "What jobs exist? What do they need?"                           │
│                                                                  │
│  Input:  Job directories, pyproject.toml, providers              │
│  Output: list[JobDescriptor] — pure data, no side effects        │
│                                                                  │
│  Key classes: CachedDirectoryScanProvider, StaticProvider,        │
│               ResolutionPipeline, ModulePreFilter                 │
│  Lives in: _discovery/                                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2: Loading & Wiring                                       │
│                                                                  │
│  "Import code, resolve config, wire into a runner"               │
│                                                                  │
│  Two partitions:                                                 │
│    A) Full boot: import all → Click tree (for --help, TUI)       │
│    B) Selective: import one → execute immediately (fast path)     │
│                                                                  │
│  Key classes: CliAdapter (builds Click tree from descriptors)     │
│  Lives in: app/adapters/, _app/boot.py                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3: Execution                                              │
│                                                                  │
│  "Run the job with full lifecycle"                               │
│                                                                  │
│  Single path for ALL invocation modes:                           │
│    CLI, rc.invoke(), func standalone, HTTP, Lambda               │
│                                                                  │
│  Key classes: JobExecutionEngine, RunContext, DIRegistry          │
│  Lives in: _engine/                                              │
└─────────────────────────────────────────────────────────────────┘
```

## Bootstrap Strategies

`func` (standalone) and `FunctualizeApp` (library) are NOT two frameworks. They're two bootstrap strategies feeding one shared runtime:

```
┌───────────────────────────┐   ┌───────────────────────────┐
│  Declared Bootstrap        │   │  Discovered Bootstrap      │
│  (FunctualizeApp)          │   │  (func standalone)         │
│                            │   │                            │
│  jobs_dirs = explicit      │   │  jobs_dirs = CWD scan      │
│  config   = named search   │   │  config   = CWD search     │
│  identity = app name       │   │  identity = none           │
│  plugins  = named group    │   │  plugins  = generic group  │
│  children = declared       │   │  children = not supported  │
└──────────────┬─────────────┘   └──────────────┬────────────┘
               │                                 │
               └────────────┬────────────────────┘
                            ▼
               ┌─────────────────────────┐
               │    Shared Runtime        │
               │                          │
               │  FunctualizeApp kernel   │
               │  JobExecutionEngine      │
               │  ResolutionChain         │
               │  EventBus + Hooks        │
               │  CliAdapter (or other)   │
               └─────────────────────────┘
```

## Interactivity Model (Input/Output Axes)

Interactivity operates on two independent axes:

**Input axis** (how the user tells it what to run):
- Level 0: Programmatic — `app.execute("deploy", **kwargs)`
- Level 1: CLI — `func deploy --target-env prod`
- Level 2: Auto TUI — inline SmartBar form generated from job metadata
- Level 3: Custom Input TUI — guided wizards

**Output axis** (how it shows what's happening):
- Level 0: Silent — return value only
- Level 1: Stdout/Logging — `rc.log()`, Rich panels
- Level 2: Inline Textual — progress bars within terminal flow
- Level 3: Full-screen TUI — live DataTables, split panes
- Level 4: External/Remote — webhooks, Slack, dashboards

Any input mode can pair with any output mode. The engine is the pivot point — it emits events/callbacks, and output adapters render them.

## Design Principles

1. **Core stays synchronous** — Async complexity lives at adapter boundaries
2. **Protocols over inheritance** — All ports are `@runtime_checkable` Protocols
3. **Composition root wires everything** — Only `_app/` imports across peer layers
4. **`_cli/` dogfoods the public API** — Proves API completeness
5. **Presets are factory functions** — Any `() → ConfigSources` is valid
6. **Zero runtime cost for unused features** — Null stubs, lazy imports, optional deps
7. **Pre-release stance** — No backward compatibility baggage
