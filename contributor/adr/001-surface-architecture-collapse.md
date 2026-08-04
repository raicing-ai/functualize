# ADR-001: Surface Architecture — Collapsing the Interactivity Model

**Status**: accepted
**Date**: 2026-07-18
**Deciders**: Core team (architecture deliberation set 2026-07-16/17)

## Context

The interactivity model had grown to five overlapping concepts (`InputProvider`,
`OutputRenderer`, Display Slot, TUI plugin, flow-viz special-case) that shared
two live methods' worth of real behavior. The `render_log`/`render_phase`/`render_progress`
protocol trio had zero callers. The `Renderer` fan-out class had zero instantiations.
The fullscreen plugin carried three generations of dead API surface. The SDK package
boundary (`functualize-interactivity`) was fictional — it was a hard core dependency
imported by nine core modules, and core imported it right back.

Meanwhile, the question "where does a job render?" (panel vs. stdout vs. job-owned UI)
had no formal model, causing confusion when constrained contexts (MCP, CI) encountered
jobs that needed terminal ownership.

## Decision

Collapse the five-concept taxonomy into three:

1. **`Surface` protocol** — a single `handle_event(StructuredEvent)` method. Events fan
   out to every registered surface. Replaces `OutputRenderer` + the dead `render_*` trio.

2. **`PromptCollector` protocol** — a single `collect(PromptRequest) -> PromptResponse`
   method. Exactly one active at a time, resolved by surface-stack position. Replaces
   `InputProvider`.

3. **`TTY` capability** — a DI-injectable parameter that grants terminal ownership.
   Statically harvested into the `JobDescriptor` cache (like `is_stdin`), enabling
   pre-flight routing without importing the job module. Provides the runtime handle
   (`tty.run(app)`) for job-owned UIs.

Supporting decisions:

- **Surface stack** on `FunctualizeApp` (`push_surface`/`pop_surface`, `finally`-guaranteed)
  replaces "first-registered wins" provider resolution with stack-scoped routing.
- **Three rendering surfaces** (PANEL, STDOUT, EXCLUSIVE) with a resolution ladder:
  job hard requirement > job hint > TUI setting > framework default > capability floor.
- **`TextualApp` base class** in `functualize.ui` — the batteries-included Textual
  `Surface` implementation with pre-mount buffering and thread-safe `handle_event`.
- **`StdoutSurface`** — the CLI's rich surface with scrollback + live zone + prompt zone.
- **`functualize-interactivity` dissolved** — contracts + types moved into core
  (`_types/interactivity.py`); the separate package eliminated.
- **Two protocols kept separate** (not fused into one 2-method protocol) because the
  two capabilities are genuinely independent: flow-viz renders but cannot ask questions;
  the stdin fallback asks but renders nothing.

## Consequences

### Positive

- Concept count dropped from five to three
- De-facto architecture became the official one
- Job-owned UIs need no plugin — just declare `tty: TTY`
- Every cell of the rendering matrix resolves to one of three named things
- One package and its version-skew axis disappeared
- Constrained contexts (MCP, CI) get pre-flight refusal instead of garbled output

### Negative

- Event payloads become API — the `StructuredEvent` vocabulary needs documented
  stability guarantees (replaces the per-callback type safety of the old `on_*` signatures)
- The fullscreen plugin required a rewrite into a `TextualApp` subclass

### Neutral

- The PANEL path (shipped TUI) preserved byte-for-byte — zero regression risk there
- Published-SDK consumers (if any) get one release of adapter shims via deprecation

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Keep `InputProvider`/`OutputRenderer` but clean up dead code | Minimal churn | Keeps the fictional SDK boundary; five concepts for two channels | Doesn't solve the routing problem |
| Fuse `Surface` + `PromptCollector` into one 2-method protocol | Fewer types | Breaks flow-viz (renders, can't ask) and stdin fallback (asks, can't render) | Forces stub methods on every impl |
| Widget embedding (jobs mount widgets in host TUI) | Rich UI inside panels | Worker-thread marshaling pushed onto job authors; crashed job takes host down | Structured prompts (PromptRequest → DynamicInputBar) is the better path |

## References

- Implementation: `src/functualize/_types/interactivity.py` (protocols),
  `src/functualize/ui/` (`TextualApp`, `StdoutSurface`),
  `src/functualize/_engine/surface_routing.py`,
  `src/functualize/_engine/capabilities/tty.py`,
  `src/functualize/app/core.py` (surface stack)
