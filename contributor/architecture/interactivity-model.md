# Interactivity Model

How a job talks to a human. The design collapses to a small number of concepts;
see `contributor/adr/001-surface-architecture-collapse.md` for the full rationale.

## Two channels, and only two

The engine's entire live conversation with a UI is two one-method protocols
(both in `functualize.plugin` / `_types.interactivity`):

```python
@runtime_checkable
class Surface(Protocol):                       # engine → UI, 1:N fan-out
    def handle_event(self, event: StructuredEvent) -> None: ...

@runtime_checkable
class PromptCollector(Protocol):               # UI → engine, 1:1 active collector
    def collect(self, request: PromptRequest) -> PromptResponse: ...
```

They are independent: a render-only surface (flow-viz) has no `collect`; the
stdin fallback collects but renders nothing; a full-screen app satisfies both.
`needs_terminal(surface)` is a module-level helper (not a protocol member) that
marks surfaces suspended while a job owns the screen.

A job never touches a Surface. Its whole conversational API is `rc`
(`log`/`emit`/`set_phase`/`prompt_*`); the engine turns those into
`StructuredEvent`s and `PromptRequest`s. That ignorance is what lets one
unmodified job render in a TUI panel, in plain stdout, in a job-owned app, as
MCP gate checkpoints, or under a test double.

## Three rendering surfaces

Who owns the terminal while a job runs, and who draws on it:

| Surface | Terminal owner | Job thread | Job I/O path |
|---|---|---|---|
| **PANEL** | the func TUI | worker thread | events → the TUI output panel |
| **STDOUT** | the func Rich runtime (host exited) | main thread | events → scrollback + a `rich.live` zone (`StdoutSurface`) |
| **EXCLUSIVE** | the job | main thread | the job draws directly via `TTY` |

Resolution ladder (top wins, `_cli/orchestrator.resolve_surface`): a `tty: TTY`
requirement → EXCLUSIVE; else a job hint (`@surface_hint("stdout"|"panel")`,
cached on the descriptor) → the `tui.default_surface` setting → the framework
default. Clamped by the capability floor: EXCLUSIVE needs a real terminal, so
MCP/CI/piped contexts refuse a `tty: TTY` job with `TerminalUnavailable`.
Direct `func <job>` runs consult only the *explicit* rungs
(`explicit_surface` + `app/adapters/surface_gate.wants_stdout_surface`): a
`StdoutSurface` is registered when the job `uses_live`, an ambient construct
is eligible, or hint/setting say STDOUT — otherwise plain output is untouched.

## Job-facing capabilities

A job declares where it renders in its signature; the markers (plus
`@suppress_live`/`@surface_hint` declarations) are harvested statically into
the descriptor cache (v7), so warm/lazy boot routes without importing the job:

| Capability | Meaning |
|---|---|
| `tty: TTY` | HARD requirement: terminal ownership. `tty.run(app)` runs a job-owned UI; `tty.ctx` is the `RunContext`. Forces EXCLUSIVE; refused off a terminal. |
| `tty: TTY \| None` | preference: injected when EXCLUSIVE can be granted, else `None` — an adaptive job branches. |
| `live: Live` | per-surface live-display channel. `live.add(construct)` renders a `LiveConstruct` (a Rich renderable); `live.panel(construct)` additionally mounts it as an interactive PanelHost panel in the func TUI (passive render on STDOUT). Always injected, degrading to a no-op where there is no live surface. |

## Prompt routing — which collector answers

`rc.prompt_*()` is context-free at the call site: the job asks, and the *caller's*
context decides who answers. This table is the contract every prompt path must
satisfy.

| Caller context | Active `PromptCollector` | Headless / timeout behavior |
|---|---|---|
| CLI direct (`func deploy`, no TUI) | kernel stdin collector, **only at a TTY** | non-TTY → `default` / `InputNotAvailable`; **never blocks** |
| Inline TUI (`FunctualizeInlineTUI`) | the TUI's in-app collector (SmartBar / `DynamicInputBar`) | interactive |
| Fullscreen TUI (`FunctualizeTUI` host + `TextualApp`) | the app's modal collector | interactive |
| MCP tool call | gate strategy — **no** interactive collector | never blocks; gate checkpoint or `default` |
| Inbound AI | AI gate strategy | policy-driven default |
| Outbound AI job | none interactive | `default` or job-supplied value |
| Non-interactive / background | none | `default` / `InputNotAvailable`; never blocks |
| Test | `TestRunContext` / mock collector | deterministic from the fixture |

**Invariant: the kernel stdin collector activates only at a TTY**
(`_engine/capabilities/stdin_collector.py`). MCP, CI, and background runs stay
inert, so there is no context in which a prompt waits on a terminal nobody is
watching. The historical `default` / `InputNotAvailable` behaviour is unchanged
by anything above — the table describes *who is asked*, not what happens when
no one can be.

> Vocabulary note: this is the `Surface` / `PromptCollector` model
> (`_types/interactivity.py`). The dynamic-input-bar proposal states the same
> table in terms of `InputProvider`, which ADR-001 collapsed — see
> `contributor/adr/001-surface-architecture-collapse.md`. Prefer this one.

## The surface stack

`app._surfaces` holds boot-registered surfaces; `app._surface_stack` holds
phase-scoped ones (a job-owned app pushed by `TTY.run` for its window,
`finally`-popped). `_engine/surface_routing` fans events to all surfaces except,
while an exclusive terminal window is active, other terminal surfaces (headless
ones — log files, MCP progress, test recorders — always receive). Prompts resolve
top-of-stack; `Live` binds to the active live-capable surface.

## Where code lives

| Concern | Location | Public API |
|---|---|---|
| `Surface` / `PromptCollector` / `LiveConstruct` | `_types/interactivity.py` + `plugin/` re-export | `from functualize.plugin import Surface, PromptCollector, LiveConstruct` |
| `PromptRequest`/`Response` | `_types/` + `plugin/`/`job/` re-export | `from functualize.plugin import PromptRequest` |
| `TTY` / `Live` capabilities | `_engine/capabilities/{tty,live}.py` | `from functualize.job import TTY, Live` |
| Surface routing (fan-out, collect, live zone) | `_engine/surface_routing.py` | internal |
| Surface stack (`push_surface`/`pop_surface`) | `app/core.py` | `FunctualizeApp` |
| `rc.emit` / `rc.prompt_*` | `_engine/capabilities/runcontext.py` | `rc.emit(...)` / `rc.prompt_*(...)` |
| Kernel stdin fallback | `_engine/capabilities/stdin_collector.py` | internal |
| `TextualApp` / `StdoutSurface` / fullscreen | `functualize/ui/` (the `[cli]` extra) | `from functualize.ui import TextualApp, StdoutSurface` |
| Surface-resolution ladder + EXCLUSIVE handoff | `_cli/orchestrator.py`, `_cli/inline_tui.py` | internal |
| Inline TUI plugin | `plugins/functualize-inline/` | separate package |
| Flow visualization plugin | `plugins/functualize-flow-viz/` | separate package |

## Design principle

> The engine emits `StructuredEvent`s to every registered `Surface` and routes a
> `PromptRequest` to one active `PromptCollector`. It never knows which UI is
> active. A job never knows either — it only speaks `rc`.

Exceptions inside a surface's `handle_event` are logged and swallowed — one
misbehaving surface never interrupts a job or starves its peers.
