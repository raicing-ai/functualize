# Plugin Module

::: functualize.plugin
    options:
      show_root_heading: true
      members_order: source

---

## Overview

The `functualize.plugin` module is the entry point for plugin authors. It exports all protocols and types needed to build functualize plugins.

**Module location:** `src/functualize/plugin/`

```python
from functualize.plugin import (
    EventBus,
    HookEvent,
    StructuredEvent,
    JobProvider,
    JobTransform,
    Job,
    AdapterPlugin,
    Surface,
    PromptCollector,
    LiveConstruct,
    PromptRequest,
    PromptSeverity,
    PluginMetadata,
    PluginWithShutdown,
    Source,
    FormatProvider,
    ModulePreFilter,
    DEFAULT_SIGIL,
    SettingsSources,
)
```

---

## `PluginMetadata`

A `typing.Protocol` with `runtime_checkable`. Every plugin object must satisfy this protocol.

```python
from functualize.plugin import PluginMetadata

@runtime_checkable
class PluginMetadata(Protocol):
    name: str
    version: str
    description: str
```

| Attribute | Type | Constraint |
|---|---|---|
| `name` | `str` | Maximum 64 characters. |
| `version` | `str` | Must be a valid PEP 440 version string. |
| `description` | `str` | Maximum 256 characters. |

---

## `Surface`

A protocol for objects that render a job's events. The engine's single
engine→UI channel: every non-framework event is fanned out to every registered
surface.

```python
from functualize.plugin import Surface

@runtime_checkable
class Surface(Protocol):
    def handle_event(self, event: StructuredEvent) -> None: ...
```

Register with `app.extensions.register_surface(obj)`. `handle_event` is called on worker
threads — a UI implementation must marshal onto its own loop (see
`functualize.ui.TextualApp`, which does this for you). A surface may set
`needs_terminal = False` to keep receiving events while a job owns the screen
(log files, MCP progress, test recorders).

!!! note "Exception safety"
    Exceptions raised inside `handle_event` are caught and logged at ERROR level
    by the event bus; dispatch continues, so a failing surface never interrupts
    job execution or starves other surfaces.

---

## `PromptCollector`

A protocol for objects that answer a job's prompts. Exactly one collector is
active at a time — the one that owns the terminal (or the modal) right now.

```python
from functualize.plugin import PromptCollector

@runtime_checkable
class PromptCollector(Protocol):
    def collect(self, request: PromptRequest) -> PromptResponse: ...
```

An object may satisfy both `Surface` and `PromptCollector` (a full-screen
`TextualApp` does). Also registered with `app.extensions.register_surface(obj)`.

---

## `LiveConstruct`

A protocol for a renderable hosted in a surface's live zone — a job's
`live: Live` capability mounts these via `live.add(construct)`.

```python
from functualize.plugin import LiveConstruct

@runtime_checkable
class LiveConstruct(Protocol):
    def __rich__(self) -> Any: ...   # any Rich renderable
```

The surface owns the cursor and repaint; the construct just returns its current
state as a Rich renderable. The "raw" fallback is Rich's own off-TTY degradation.

---

## `PromptRequest`

A frozen dataclass carrying the complete specification for a user prompt.

```python
from functualize.plugin import PromptRequest

request = PromptRequest(
    question="Select environment",
    intent=PromptIntent.SELECT,
    choices=[PromptChoice(value="staging"), PromptChoice(value="prod")],
)
```

---

## `PromptSeverity`

Visual severity level for prompt presentation.

```python
from functualize.plugin import PromptSeverity

class PromptSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    DANGER = "danger"
    SUCCESS = "success"
```

Largely **derivable from `PromptIntent`** — a destructive confirmation is a danger prompt, everything else is informational — so a `PromptRequest` normally lets the engine's own intent→severity mapping supply it rather than passing it by hand. It remains settable on `PromptRequest` for the cases where a caller genuinely wants to override the styling (e.g. a warning on a non-destructive action).

---

## `PluginWithShutdown`

A protocol for plugins that need graceful shutdown:

```python
from functualize.plugin import PluginWithShutdown

class MyPlugin:
    def on_shutdown(self, app) -> None:
        """Called during application shutdown."""
        ...
```

Shutdown methods are called in **reverse loading order** with a **5-second per-plugin timeout**.

---

## `ModulePreFilter`

Decides whether a module is worth importing, **before** discovery imports it.
The built-in filters express the `require_*` settings; a host whose jobs no
setting can describe supplies its own.

```python
from pathlib import Path

from functualize.plugin import ModulePreFilter


class HasJobSuffix:
    def should_import(self, source_file: Path) -> bool:
        return source_file.stem.endswith(("_tasks", "_ops"))

    def fingerprint(self) -> str:
        return "has-job-suffix:v1"
```

Satisfied structurally — there is nothing to inherit. Supply it through
`DiscoveryConfig(pre_filter=...)`, where it is **ANDed** onto the built-in
stack rather than replacing it, and runs last because its cost is unknown.

!!! warning "`fingerprint()` is not optional"
    The discovery cache persists *negative* pre-filter decisions and replays
    them while the fingerprint matches. Identity cannot stand in for it:
    `str()` of an object carries its memory address, so a digest built from the
    object would differ on every boot — invalidating the cache on every run
    while appearing to work. A filter with no `fingerprint()` is refused with a
    `TypeError` rather than cached wrongly.

    Return the same string across processes for the same behaviour, and a new
    one when the predicate changes. Forgetting to bump it gives a stale cache —
    the same contract as any cache key.

See [Jobs and Auto-Discovery](../guides/jobs-discovery.md) for the full
treatment and [Hosting Functualize](../guides/hosting.md) for the other host
seams.

---

## `DEFAULT_SIGIL`

The sigil the shell's default (command) input mode is registered under — the empty string. A mode is selected by the first character of the input text; the default mode's sigil is empty so it is the fallback for any input that starts with no other registered sigil, and cannot collide with a real one.

```python
from functualize.plugin import DEFAULT_SIGIL, InputMode, InputModeRegistry

registry = InputModeRegistry()
registry.register(InputMode(
    sigil=DEFAULT_SIGIL,
    name="command",
    candidate_source=my_candidates,
    is_ready=lambda text: True,
    submit=run_command,
    history_namespace="command",
))
```

`InputModeRegistry.resolve(text)` falls back to whatever mode is registered under `DEFAULT_SIGIL` when `text`'s first character matches no other registered sigil.

---

## `SettingsSources`

Where a host app's settings are read from, in precedence order. Precedence itself is fixed (default < global < project < env); what varies per app is the *file names* — declaring them is what makes the settings store app-agnostic rather than hardcoded to `func`'s own filenames.

```python
from functualize.plugin import SettingsSources

@dataclass(frozen=True)
class SettingsSources:
    global_file_name: str = "config.toml"
    project_file_names: tuple[str, ...] = (
        "pyproject.toml",
        ".functualize.toml",
        ".functualize/.functualize.toml",
    )
    env: bool = True
```

| Attribute | Type | Description |
|---|---|---|
| `global_file_name` | `str` | File inside the user config dir (XDG-resolved). |
| `project_file_names` | `tuple[str, ...]` | Candidates for the upward project walk, nearest wins, probed in this order at each level. |
| `env` | `bool` | Whether environment variables participate in resolution at all. |

It is the `sources` field of `AppSettingsSchema` (also exported from `functualize.plugin`) — the full declaration a second app hands to the settings store to get the same machinery `func` uses under its own name.

---

## Internal Location

Plugin loading machinery lives in `functualize._plugins/`:

- `_plugins/loader.py` — Discovery + dependency sort + loading (also defines `PluginMetadata` protocol)
- `_plugins/config.py` — PluginConfigRegistry

!!! warning "Internal API"
    Modules under `functualize._plugins` are implementation details. Import from `functualize.plugin` instead.
