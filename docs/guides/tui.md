# TUI Integration

> This page covers `FunctualizeTUI` — the embeddable multi-screen TUI adapter
> for apps built on Functualize. For the interactive shell that bare `func`
> launches (SmartBar, panel rings), see [Inline TUI](../cli/inline-tui.md).

## Interactivity Architecture

The TUI layer in Functualize is built on two decoupled channels: one for receiving job events (output) and one for triggering job execution (input). Together they let any UI backend — terminal, web, desktop, or headless — participate in job orchestration without coupling to internal framework objects. Both are single-method protocols in `functualize._types.interactivity` (re-exported from `functualize.plugin`); see `contributor/architecture/interactivity-model.md` for the full model.

### Output channel: the `Surface` protocol

A `Surface` receives a 1:N fan-out of every `StructuredEvent` a job emits. It has exactly one method:

```python
@runtime_checkable
class Surface(Protocol):
    def handle_event(self, event: StructuredEvent) -> None: ...
```

`StructuredEvent` carries `event_name` (a `{domain}.{resource}.{action}` string such as `job.execute.start`, `job.execute.end`, `job.teardown.end`), `resource`, and a `payload` dict — so a surface reads whatever it needs off one uniform shape rather than a fixed callback list. Register a surface with `app.register_surface(obj)`.

!!! danger "handle_event runs on the job's worker thread"
    When a host owns the terminal, `handle_event` is invoked from the job's
    worker thread. A surface that touches a UI must marshal onto its own loop
    (Textual: `post_message` / `call_from_thread`); writing to a widget directly
    freezes the app silently. Headless surfaces set `needs_terminal = False` to
    keep receiving events even while a job owns the screen.

### Input channel: `interactivity.job.submit` EventBus event

To trigger a job from a UI backend without touching the engine directly, emit this event:

```python
app.event_bus.emit(
    "interactivity.job.submit",
    resource=job_name,
    job_name=job_name,
    kwargs={},
)
```

`FunctualizeApp` subscribes `_on_job_submit_event` to this topic at boot and routes it to `JobExecutionEngine.execute()`.

To *answer* a job's questions (`rc.prompt_*`), a backend additionally implements the `PromptCollector` protocol (`collect(request) -> PromptResponse`); exactly one collector is active at a time — whoever owns the terminal or modal.

### Data flow diagram

```
[TUI / Web / Custom Backend]
         |                        ^
         |  emit(                 |  handle_event(event)   ← Surface, 1:N fan-out
         |    "interactivity.     |    event.event_name
         |     job.submit", ...)  |    event.resource
         |                        |    event.payload
         v                        |
[FunctualizeApp.event_bus]        |
         |                 [registered Surfaces]
         v                        ^
[JobExecutionEngine] ─────────────+
         |
    [Job Function]  ── rc.prompt_* ──►  [active PromptCollector.collect]
```

### The inline TUI as the reference implementation

`FunctualizeInlineTUI` (`_cli/tui/app.py`) is the built-in reference `Surface`. It subscribes to the EventBus and renders live updates into its panels (`JobBrowserPanel`, `ConfigTablePanel`, `ConfigFilesPanel`, …) rather than separate screens. You can use it as a template when building your own backend.

---

Functualize provides two ways to drive jobs from a terminal UI:

1. **The inline auto-form** — running your app bare on a TTY opens a SmartBar
   where you type a job name and see a live pre-flight form built from the
   job's metadata. This *is* the auto-generated form experience. There is **no**
   separate `tui` subcommand, and Trogon is not involved. It is documented in
   full under [Inline TUI](../cli/inline-tui.md).
2. **`FunctualizeTUI`** — a lightweight container for cycling between your own
   full-screen [Textual](https://github.com/Textualize/textual) screens,
   described below.

## The inline auto-form

Running your app bare in an interactive terminal launches the inline TUI:

```bash
my-app
```

The SmartBar accepts a job name and renders its parameters as an interactive
pre-flight form derived from the job's `JobConfig` / signature — `str`/`int`/
`float` as text inputs, `bool` as a `--flag/--no-flag` toggle, `Enum` as a
constrained choice, and so on. Option names display their CLI-flag spelling
(`dry_run` → `dry-run`); positional arguments keep their bare name.

Validation is **Pydantic's**, not the form's: `Enum` choices are constrained in
the form, while `ge`/`le`/`gt`/`lt`/`@field_validator` constraints are enforced
**when the job runs**, not while you fill in the form. See
[Inline TUI](../cli/inline-tui.md) for the full keybindings, panels, and
behavior.

```python
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class Speed(str, Enum):
    slow = "slow"
    normal = "normal"
    fast = "fast"


class CountdownConfig(BaseModel):
    speed: Speed = Field(default=Speed.normal, description="Processing speed")
    start: int = Field(default=5, ge=1, le=10, description="Count from (1-10)")

    @field_validator("start")
    @classmethod
    def in_range(cls, v: int) -> int:
        return v
```

!!! tip "Communicate constraints in help text"
    Since the form does not enforce numeric ranges visually, include the valid
    range in each field's `description` — it shows next to the field:

    ```python
    start: int = Field(default=5, ge=1, le=10, description="Count from (1-10)")
    ```

## FunctualizeTUI — multi-screen container

`FunctualizeTUI` (`functualize.app.adapters.FunctualizeTUI`) is a minimal
registry for cycling between full-screen [Textual](https://github.com/Textualize/textual)
`Screen`s. It ships **no** built-in screens — you register your own — and it is
deliberately small: a screen list plus a cycle action. For a fuller, job-owned
application surface with prompts and displays, prefer `functualize.ui.TextualApp`
(see the Interactivity guide).

### API

```python
class FunctualizeTUI:
    BINDINGS = [("ctrl+tab", "cycle_screen", "Next Screen")]

    def register_screen(self, screen_class, identifier: str) -> None: ...
    def action_cycle_screen(self) -> None: ...
```

| Member | Behavior |
|---|---|
| `register_screen(screen_class, identifier)` | Register a Textual `Screen` subclass under a unique identifier. Duplicate identifiers are silently ignored — the first registration for an identifier wins. |
| `action_cycle_screen()` | Advance to the next registered screen in registration order, wrapping after the last. Bound to ++ctrl+tab++. Does nothing when no screens are registered. |

### Example

```python
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from functualize.app.adapters import FunctualizeTUI


class DashboardScreen(Screen):
    """A custom dashboard screen showing application summary."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Welcome to My App Dashboard", id="title")
        yield Footer()


tui = FunctualizeTUI()
tui.register_screen(DashboardScreen, "dashboard")
```

Registered screens participate in ++ctrl+tab++ cycling in registration order.
