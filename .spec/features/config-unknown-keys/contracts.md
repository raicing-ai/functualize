# config-unknown-keys — External contracts

## C1. `func builtin config path` — text output

One line per settings layer (`settings_layers()`) and per expected location
that is not a layer, in **ascending precedence**, today's order: the global
file first, then project files from the farthest to the nearest. At each
project directory, `pyproject.toml` comes before `.functualize.toml`, as today.
A `pyproject.toml` with no `[tool.functualize]` keeps today's
`○ found … (no [tool.functualize])` line. A missing global file or a missing
anchor candidate keeps its `✗ missing` line. The line format is unchanged:

```
  <status> <path>[ <existing qualifier>]
<status>    := "✓ used   " | "○ found  " | "✗ missing"      # meanings: spec.md §3.6
```

followed, only when the file has unknown keys, by:

```
 — <finding>[; <finding>]*
<finding>   := unknown key "<dotted-key>"[ (did you mean "<dotted-key>"?)]
```

- `<dotted-key>` is `<key>` at top level, `<section>.<key>` inside a section,
  relative to the functualize table (for `pyproject.toml`, relative to
  `[tool.functualize]`).
- Findings are in document order (top-level keys first as TOML yields them,
  then section keys in section order).
- For a project whose settings live only in the current directory and hold only
  known keys, the output is byte-identical to `91947bb4` (spec §3.9).
- Exit code: unchanged (0).

## C2. `func builtin info --json` / `func builtin info all --json`

New key inside the existing, always-present `config` object:

```json
{
  "config": {
    "anchor": "…",
    "import_libs": [],
    "dotenv": false,
    "output": "rich",
    "unknown_keys": [
      {"file": "/abs/path/.functualize.toml", "key": "roots", "suggestion": "root"},
      {"file": "/abs/path/.functualize.toml", "key": "definitely_not_a_setting", "suggestion": null},
      {"file": "/abs/path/.functualize.toml", "key": "cli.outptu", "suggestion": "cli.output"}
    ]
  }
}
```

- Always present; `[]` when no participating file has an unknown key.
- `file`: absolute path string. `key`: dotted key as in C1. `suggestion`:
  dotted key or `null`.
- Order: layer precedence order (nearest project file first, global last),
  then document order within a file.
- Files: every layer `settings_layers()` returns that exists (C5).
- The plain renderer (`info` without `--json`) is unchanged.

## C3. The unknown-key check (internal, `_cli` layer)

`functualize._cli.data.config_vocabulary` imports stdlib and the public
re-exports only:

```python
@dataclass(frozen=True)
class UnknownKey:
    file: Path
    key: str                 # dotted, relative to the functualize table
    suggestion: str | None

def find_unknown_keys(table: Mapping[str, Any], *, file: Path,
                      schema: AppSettingsSchema) -> tuple[UnknownKey, ...]: ...
def unknown_keys_in_layers(layers: Sequence[SettingsLayer],
                           schema: AppSettingsSchema) -> tuple[UnknownKey, ...]: ...
def describe(findings: Sequence[UnknownKey]) -> str: ...   # C1 suffix, "" when empty
```

No word list of its own. "Known" means `schema.keys_in(section)`.

## C4. The one declaration (`_types`, public via `functualize.app.config` and `functualize.plugin`)

```python
# functualize._types.settings — extended
@dataclass(frozen=True)
class Setting:
    name: str; type: str; description: str
    default: str | None = None
    choices / min_value / max_value / max_items     # unchanged
    cli_flag: str | None = None                     # now set for every settings-backed root flag
    phase: str | None = None
    places: tuple[str, ...] = ()        # ordered file lookup; () == (self.section,); "" = top level
    listed: bool = True                 # a settings row / help entry
    surface: str | None = None          # "tui": listed only where that surface runs
    env: bool = True                    # has an environment variable (env_var_for)
    # type: "str" | "int" | "bool" | "enum" | "list" | "map" | "records" | "secret"
    # merge: list settings concatenate + dedupe across layers (today's rule); others first-wins

@dataclass(frozen=True)
class AppSettingsSchema:
    settings, env_prefix, sources, file_section_prefixes   # unchanged
    def extend(self, *settings: Setting) -> AppSettingsSchema: ...   # an app's own settings; name clash → ValueError
    def setting(self, name: str) -> Setting | None: ...
    def sections(self) -> frozenset[str]: ...
    def keys_in(self, section: str) -> frozenset[str]: ...
    def flag(self, flag: str) -> Setting | None: ...
    def value_in(self, table: Mapping[str, Any], setting: Setting) -> Any | None: ...
    env_var_for(setting) / section_prefix_for / section_in_file          # unchanged

# functualize._types.functualize_settings — NEW, data only
ROOT, DOTENV, DOTENV_PATH, IMPORT_LIBS, JOBS_DIRECTORIES, PLUGINS_DIRECTORIES,
EXTRA_DIRECTORIES, EXCLUDE_PATTERNS, SCAN_DEPTH, REQUIRE_FILE_PREFIX, … ,
CLI_OUTPUT, CLI_SHOW_TIMING, CLI_INLINE_TUI, PLUGINS_STRICT, PLUGINS_DISABLED,
SHELL_PROGRAM, SHELL_SUDO_PASSWORD, VAULT_KEYRING_TIMEOUT, ALIASES, VAULT_SECRET,
TUI_THEME, … : Setting
FUNCTUALIZE_SETTINGS: AppSettingsSchema
SCRIPT_METADATA: AppSettingsSchema      # PEP 723 [tool.functualize]: job (+ skill per M5)
```

## C5. Layers and resolution (`_config`, public via `functualize.app.config`)

```python
@dataclass(frozen=True)
class SettingsLayer:
    path: Path
    kind: Literal["project", "global"]
    section_prefix: str            # "tool.functualize" or ""
    table: Mapping[str, Any]       # the functualize-scoped table; {} when missing/broken
    exists: bool

def settings_layers(schema: AppSettingsSchema, cwd: Path) -> tuple[SettingsLayer, ...]:
    """Upward walk via ResourceLocator, root = true stop, global last. The only reader of settings files."""

@dataclass(frozen=True)
class ResolvedSetting:
    setting: Setting
    value: Any
    source: str                    # "cli" | "vault" | "env" | "file" | "default"
    origin: str                    # flag, env var name, file path, or "default"
    contributors: tuple[str, ...]  # every file path that contributed (merged lists)

@dataclass(frozen=True)
class ResolvedSettings(Mapping[Setting, ResolvedSetting]):
    schema: AppSettingsSchema
    layers: tuple[SettingsLayer, ...]
    def value(self, setting: Setting) -> Any: ...
    def contributes(self, layer: SettingsLayer) -> bool: ...   # config path "used"

def resolve_settings(schema: AppSettingsSchema, layers: Sequence[SettingsLayer], *,
                     flags: Mapping[Setting, Any] = {}, environ: Mapping[str, str] | None = None,
                     vault: Source | None = None) -> ResolvedSettings:
    """Builds one ResolutionChain (CliSource → vault → EnvSource(prefix) → one source per layer → defaults)."""
```

- `ConfigSources` gains `settings: AppSettingsSchema = FUNCTUALIZE_SETTINGS`
  (an app's declaration) and carries the pre-boot `ResolvedSettings`. Boot
  re-resolves only `secret` settings with the vault source.
- `FunctualizeApp.settings -> ResolvedSettings` (public, read-only) is what the
  engine, the adapters, the TUI and the builtins read.

## C6. Removed (pre-release: removed, not shimmed)

`register_settings`, `registered_settings`, `clear_registered_settings`,
`set_preboot_override`, `preboot_overrides`, `clear_preboot_overrides`,
`FuncSetting`, `_BASE_SETTINGS`, `tui_settings`, `SETTING_SCHEMAS`,
`_RECOGNIZED_*`, `read_global_config`, `resolve_cli_config_layers`,
`SettingsFileInfo`, `CliConfig`'s own resolution, `LIST_KEYS` literal,
`_DISCOVERY_FINGERPRINT_FIELDS` literal, `OPTIONAL_VALUE_VALID_SET` (renamed
`GLOBAL_OPTION_ACCEPTED_VALUES`), the hand-written settings click options.
`FuncSettingsStore` stays as the TUI's editor and write-back, over
`ResolvedSettings`.
