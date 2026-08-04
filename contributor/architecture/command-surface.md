# Command Surface Architecture

**Audience:** contributors working on TUI navigation, autocomplete, or shell integration.
**Status:** shipped. See [ADR-004](../adr/004-cli-shell-convergence.md).

## 1. `CommandNode` Protocol

```python
@runtime_checkable
class CommandNode(Protocol):
    name: str                 # Canonical command name
    help: str                 # Help text (from job docstring or builtin help)
    provenance: str           # "job", "group", "builtin", "plugin"
    children: list[CommandNode]  # Nested commands (group children)
    params: list[FieldDescriptor]  # CLI parameters

    needs_terminal: bool     # True if this node requires a TTY
    def execute(self, **kwargs) -> Any: ...
```

- `name` is the canonical lowercase-hyphenated name
- `children` is empty for leaf commands
- `params` is populated from the discovery cache (no module import needed)
- `provenance` drives the TUI's breadcrumb display

## 2. `CommandProvider` Protocol

```python
@runtime_checkable
class CommandProvider(Protocol):
    def root_nodes(self) -> list[CommandNode]: ...
```

Providers are composed — the app registers multiple providers, and the TUI merges
their root nodes. This replaces five hardcoded builtin seams that existed before
convergence.

## 3. `JobCommandProvider`

Nodes over job/group trie nodes:

- **Root:** all top-level groups + standalone jobs from the trie
- **Group nodes:** children from `trie.children(group)`, params empty
- **Job nodes:** params from cache `FieldDescriptor` rows (no materialization)
- **Matrix instances:** `deploy[env=dev]`, `deploy[env=prod]` appear as sibling
  nodes under their group

## 4. `ClickCommandProvider`

Wraps click groups (builtins):

- **Root:** the `builtin` click group's subcommands
- **`builtin cache`** → `cache` node with provenance `"builtin"`
- **`builtin state`** → `state` node with children `clear`, `show`
- Params introspected from click parameter metadata

## 5. `InputMode` + `InputModeRegistry`

Sigil-dispatched modes for the `DynamicInputBar`:

```python
class InputMode(Protocol):
    sigil: str                 # "!" for shell, "?" reserved
    def mount(self, bar: DynamicInputBar) -> Widget: ...
    def handle_submit(self, text: str) -> CommandResult | None: ...

class InputModeRegistry:
    def register(self, mode: InputMode) -> None: ...
    def resolve(self, text: str) -> InputMode | None: ...
```

- Sigils (`!`, `?`) are reserved at `_types/naming.py:RESERVED_SIGILS`
- Default mode (no sigil): command mode wrapping `CursorContext` sub-modes
  (groups, jobs, params)
- `!` mode: shell mode — reuses `_job_worker_running` for execution,
  writes through `StateStore.append_history`
- `?` mode: reserved for future `InputMode`

## 6. `DynamicInputBar`

Replaces `SmartBar` as the TUI's input widget:

- **Mode widget mounting:** switches between command mode and shell mode based on sigil
- **Shell mode (`!` prefix):** executes raw shell commands via `Shell` capability,
  output streams to the pipeline display
- **Reserved sigils:** `!` and `?` enforced at boot
- **Prompt-routing table:** documented in `docs/guides/tui.md` and
  `contributor/architecture/interactivity-model.md` in `Surface`/`PromptCollector`
  vocabulary

## 7. Settings Generalization

Project apps get their own settings schema (not just func's hardcoded settings):

```python
class Setting:
    key: str                  # Dotted key (e.g. "tui.default_surface")
    type: type                # str, bool, int, Enum
    default: Any
    description: str
    section: str              # e.g. "tui", "shell"

class AppSettingsSchema:
    settings: list[Setting]
    app_name: str
    validate(self) -> None

class SettingsStore(spec: AppSettingsSchema, app_name: str):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def register_section(self, section: str, settings: list[Setting]) -> None: ...
```

- `SettingsStore(spec, app_name=)` parameterized per project
- Registration API: `app.register_settings(section, settings)` allows plugins
  to contribute settings
- `tui.*` section: shell-contributed (default surface, prompt behavior)
- `shell.*` section: shell-contributed (sudo password, default shell)
