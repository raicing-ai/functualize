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
    PluginMetadata,
    PluginWithShutdown,
    Source,
    FormatProvider,
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

Register with `app.register_surface(obj)`. `handle_event` is called on worker
threads — a UI implementation must marshal onto its own loop (see
`functualize.ui.TextualApp`, which does this for you). A surface may set
`needs_terminal = False` to keep receiving events while a job owns the screen
(log files, MCP progress, test recorders).

!!! note "Exception safety"
    Exceptions raised inside `handle_event` are **swallowed with a warning** and never interrupt job execution or starve other surfaces.

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
`TextualApp` does). Also registered with `app.register_surface(obj)`.

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

## Internal Location

Plugin loading machinery lives in `functualize._plugins/`:

- `_plugins/loader.py` — Discovery + dependency sort + loading (also defines `PluginMetadata` protocol)
- `_plugins/config.py` — PluginConfigRegistry

!!! warning "Internal API"
    Modules under `functualize._plugins` are implementation details. Import from `functualize.plugin` instead.
