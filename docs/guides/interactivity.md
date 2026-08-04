# Interactivity

How a job talks to a human — prompts, live output, and job-owned UIs. A job
never imports a UI; it speaks only to its `RunContext` (`rc`), and the framework
routes that to whatever surface is active.

## The two channels

The engine's entire live conversation with a UI is two one-method protocols:

- **`Surface`** — `handle_event(event)`. The engine fans every non-framework
  event out to every registered surface (the TUI panel, a stdout renderer, a
  log file, a job-owned app).
- **`PromptCollector`** — `collect(request) -> response`. Exactly one active
  collector answers `rc.prompt_*()` at a time.

They are independent — a render-only surface has no `collect`; the stdin
fallback collects but renders nothing; a full-screen app does both. Register
either (or both) with `app.register_surface(obj)`.

## Where a job renders: three surfaces

| Surface | Terminal owner | Job renders via |
|---|---|---|
| **PANEL** | the `func` TUI | events → the TUI output panel |
| **STDOUT** | the `func` Rich runtime | events → scrollback + a live zone |
| **EXCLUSIVE** | the job itself | the job draws directly (`TTY`) |

The surface is resolved by a ladder (top wins): a `tty: TTY` requirement forces
EXCLUSIVE; otherwise a job hint → the `tui.default_surface` setting
(`panel`/`stdout`) → the framework default. EXCLUSIVE needs a real terminal, so
a `tty: TTY` job run over a pipe/CI/MCP is refused with `TerminalUnavailable`.

## Prompting — `rc.prompt_*()`

From any job, ask the user a question; it renders as terminal input, a Textual
modal, or an MCP gate depending on the active collector:

```python
def deploy(config: DeployConfig, rc: RunContext) -> str:
    if not rc.prompt_confirm("Deploy to production?", default=False):
        return "cancelled"
    region = rc.prompt_choice("Region", ["us-east-1", "eu-west-1"])
    return f"deploying to {region}"
```

At an interactive terminal with no UI plugin registered, a built-in TTY-gated
stdin collector answers. In a non-terminal context (piped, CI, MCP, background),
prompts resolve to their `default`, or raise `InputNotAvailable` when required
with no default — a job never blocks a headless run.

### Where a prompt goes

The same `rc.prompt_*()` call reaches a different collector depending on how the
job was started. The job does not choose, and does not need to know:

| Caller context | Active `PromptCollector` | Headless / timeout behavior |
|---|---|---|
| CLI direct (`func deploy`, no TUI) | kernel stdin collector, **only at a TTY** | non-TTY → `default` / `InputNotAvailable`; **never blocks** |
| Inline TUI (bare `func` on a TTY) | the TUI's in-app collector (the input bar) | interactive |
| Fullscreen TUI (`FunctualizeTUI` host) | the app's modal collector | interactive |
| MCP tool call | gate strategy — **no** interactive collector | never blocks; gate checkpoint or `default` |
| Inbound AI | AI gate strategy | policy-driven default |
| Outbound AI job | none interactive | `default` or job-supplied value |
| Non-interactive / background | none | `default` / `InputNotAvailable`; never blocks |
| Test | `TestRunContext` / mock collector | deterministic from the fixture |

The invariant that makes the table safe to rely on: **the kernel stdin collector
activates only at a TTY.** MCP, CI, and background runs stay inert — there is no
context in which a prompt silently waits on a terminal nobody is watching.

## Live output — the `Live` capability

A job that wants a live-updating view declares `live: Live` and pushes a
construct (a Rich renderable):

```python
class SyncTable:
    def __init__(self, total): self.total, self.done = total, 0
    def __rich__(self):
        from rich.table import Table
        t = Table(title=f"Syncing {self.done}/{self.total}")
        t.add_column("progress"); t.add_row("█" * self.done)
        return t

def sync(config: SyncConfig, rc: RunContext, live: Live) -> str:
    table = SyncTable(config.files)
    handle = live.add(table)
    for i in range(config.files):
        table.done = i + 1
        handle.update()          # the surface owns the cursor + repaint
    return "done"
```

`live` is always injected and degrades: it renders into a `rich.live` zone on
`func sync`, and no-ops where there is no live surface. The construct owns only
its state; the surface owns the cursor. The raw fallback is Rich's own off-TTY
degradation — no second renderer.

## Job-owned UIs — the `TTY` capability

A job that draws its own full-screen UI declares `tty: TTY` and runs a
`TextualApp` (from `functualize.ui`, the `[cli]` extra):

```python
from functualize.ui import TextualApp

def edit(rc: RunContext, tty: TTY) -> str:
    class EditorApp(TextualApp[None]):
        BINDINGS = [("q", "quit", "Quit")]
        def compose(self):
            from textual.widgets import TextArea
            yield TextArea("Edit me. q to quit.")
    tty.run(EditorApp())
    return "edited"
```

`TextualApp` is the batteries-included base: engine events reach `on_func_event`
(marshaled onto the loop thread, buffered until mount) and `rc.prompt_*()` is
answered by a modal — no threading work from you. `tty.ctx` is the `RunContext`,
the sanctioned API handle for the app.

**Selecting a `tty: TTY` job in the `func` TUI hands off:** the shell steps
aside, the app owns the screen, and the shell relaunches when the app exits.

### Adaptive jobs

`tty: TTY | None` is a preference — injected when the job can own the terminal,
`None` otherwise. One job renders two ways from its signature:

```python
def report(config: ReportConfig, rc: RunContext, live: Live,
           tty: TTY | None = None) -> str:
    if tty is not None:
        tty.run(ReportApp())          # full-screen when we own the terminal
    else:
        live.add(ReportTable())       # a live table otherwise
    return "reported"
```

## Custom surfaces

A plugin renders events by implementing `Surface` and registering it:

```python
class LogFileSurface:
    needs_terminal = False            # keep receiving even while a job owns the screen
    def handle_event(self, event):
        with open("run.log", "a") as f:
            f.write(f"{event.event_name} {event.payload}\n")

class MyPlugin:
    name = "log-file"
    def __call__(self, app):
        app.register_surface(LogFileSurface())
```

`handle_event` is called on worker threads; a UI surface must marshal onto its
own loop (use `TextualApp`). Exceptions are logged and swallowed — one bad
surface never breaks a job or its peers.

## Built-in and plugin surfaces

- **stdin fallback** (kernel) — a zero-config `PromptCollector` for `rc.prompt_*`
  at a terminal.
- **`StdoutSurface`** (`functualize.ui`, `[cli]`) — the one-writer rich stdout
  runtime: scrollback + a live zone + prompts. Hosts `live: Live` constructs.
- **`functualize-inline`** — inline Textual prompt/selection widgets.
- **`functualize-flow-viz`** — an inline execution-tree visualization.

See `examples/standalone/showcase/` (the `jobs/surfaces.py` module) for a
runnable project exercising every surface, and
`contributor/architecture/interactivity-model.md` for the internals.
