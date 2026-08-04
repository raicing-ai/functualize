# Architecture Overview

Machine-assisted architecture map (regenerate with the `/sync-docs` skill). See `entry-points.md`, `modules.md`, `dependencies.md`, `data-flow.md` for detail.

## What This Is

Functualize is a **job execution framework**: a Python library + CLI (`func`/`functualize`) that discovers job functions, resolves their configuration and dependencies, executes them with a structured lifecycle, and delivers input/output through pluggable surfaces (CLI, TUI, HTTP, Lambda, MCP).

Core insight: the execution engine is **delivery-agnostic**. It never knows whether a job was triggered by a CLI command, a Textual TUI form, an HTTP request, or a Lambda event — adapters translate each surface into a single `engine.execute()` call.

## Audience-Separated Package Structure

The codebase splits `src/functualize/` into six **public** packages (safe for users to import) and ten **internal** (underscore-prefixed) packages (framework-only, never imported by user code):

```
src/functualize/
├── app/          PUBLIC — Application construction, presets, built-in adapters
├── job/          PUBLIC — Job author API (RunContext, capabilities, decorators)
├── plugin/       PUBLIC — Plugin/extension author API (protocols, EventBus)
├── types/        PUBLIC — Shared types (JobResult, JobDescriptor, enums)
├── testing/      PUBLIC — Test doubles (TestRunContext, CapturingLog, ...)
├── workflow/     PUBLIC — Declarative multi-step workflow graph API (@workflow)
│
├── _types/       INTERNAL — Shared vocabulary (dataclasses/enums/protocols only)
├── _primitives/  INTERNAL — Zero-dep utilities (DI, ResourceLocator, MiddlewareChain)
├── _events/      INTERNAL — Cross-cutting (EventBus, HookRegistry, PerfTimeline)
├── _discovery/   INTERNAL — Job finding + caching
├── _config/      INTERNAL — Configuration resolution
├── _engine/      INTERNAL — Execution lifecycle
├── _plugins/     INTERNAL — Plugin loading machinery
├── _gate/        INTERNAL — Gate resolution for workflow steps that pause for input
├── _app/         INTERNAL — Composition root (wires everything together)
└── _cli/         INTERNAL — `func` CLI + Textual TUI delivery (public API only)
```

`_gate/` and `workflow/` are a paired mechanism: `workflow/` declares a step graph (`@workflow(steps=..., edges=...)`); `_gate/` resolves individual steps that need to pause for external input (`GateStrategy.RESOLVE | PROMPT | AI_INBOUND`).

## The Three Layers

Every job invocation passes through three conceptual layers, regardless of entry surface:

1. **Discovery & Metadata** (`_discovery/`) — "What jobs exist? What do they need?" Output: `list[JobDescriptor]`, pure data, no side effects.
2. **Loading & Wiring** (`app/adapters/`, `_app/boot.py`) — Import code, resolve config, wire into a runner. Two partitions: full boot (import all, for `--help`/TUI) vs. selective (import one, fast path).
3. **Execution** (`_engine/`) — Run the job with full lifecycle (hooks, middleware, DI). Single path for every invocation mode: CLI, `rc.invoke()`, `func` standalone, HTTP, Lambda, MCP.

## Bootstrap Strategies

`func` (standalone, discovered bootstrap) and `FunctualizeApp` (library, declared bootstrap) are two ways of feeding the same shared runtime (`FunctualizeApp` kernel, `JobExecutionEngine`, `ResolutionChain`, `EventBus`+`HookRegistry`, an adapter). Declared bootstrap uses explicit `JobSources`/`ConfigSources`; discovered bootstrap scans the CWD.

## Interactivity Model (Input/Output Axes)

Two independent axes, freely combinable — see `contributor/architecture/interactivity-model.md` for the authoritative version:

- **Input**: Programmatic (0) → CLI/Click (1) → Auto TUI/auto-generated form (2) → Custom Input TUI (3).
- **Output**: Silent (0) → Stdout/Logging (1) → Inline Textual (2) → Full-screen TUI (3) → External/Remote (4).

The full-screen TUI (`_cli/tui/`) is the largest single subsystem in the codebase by file count — see `modules.md` §`_cli/tui/`.

## Design Principles

1. Core stays synchronous — async complexity lives at adapter boundaries.
2. Protocols over inheritance — all ports are `@runtime_checkable` Protocols.
3. Composition root wires everything — only `_app/` imports across peer layers.
4. `_cli/` dogfoods the public API — proves API completeness (no `_`-prefixed imports allowed).
5. Presets are factory functions — any `() -> ConfigSources` is valid.
6. Zero runtime cost for unused features — null stubs, lazy imports, optional deps.
7. Pre-release stance — no backward-compatibility baggage (see `.spec/CONSTITUTION.md`).

## Architecture Highlights (from this scan)

- **Highest fan-in module**: `functualize._app.impl` (30 importers) — the internal `FunctualizeApp` implementation is the true hub of the dependency graph, followed by `_types.descriptors` (21) and `_events.hooks` (19). See `dependencies.md`.
- **Peer-layer independence holds**: the only cross-import found between `_discovery`/`_config`/`_engine`/`_plugins` is a `TYPE_CHECKING`-only reference in `_engine/capabilities/runcontext.py`, which the import-linter contract explicitly excludes. No runtime violation.
- **13 official plugins** live in the `plugins/` workspace, split into Domain SDKs (ai, interactivity, state, tasks — protocol-only) and their concrete implementations (ai-pydantic, inline/fullscreen-tui, state-sqlite, tasks-local) plus delivery adapters (http, lambda, mcp) and a visualization plugin (flow-viz).
- **Potential issue**: no circular dependencies detected; the one notable coupling to watch is `_cli/tui/panels/config_table.py` at 10 importers — a TUI panel with unusually high internal fan-in for a leaf UI module (see `modules.md` for detail).
