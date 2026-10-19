# config-unknown-keys — External contracts

## C1. `func builtin config path` — text output

Per file line, unchanged prefix:

```
  <status> <path>[ <existing qualifier>]
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
- A file without unknown keys prints exactly what `d1c7e40a` prints.
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
- Files: every layer `resolve_cli_config_layers()` returns that exists.
- The plain renderer (`info` without `--json`) is unchanged.

## C3. Internal module surface (consumed by C1 and C2)

`functualize._cli.data.config_vocabulary` — `_cli` layer, imports stdlib and
`_cli` siblings only:

```python
@dataclass(frozen=True)
class UnknownKey:
    file: Path
    key: str                 # dotted, relative to the functualize table
    suggestion: str | None

def find_unknown_keys(values: Mapping[str, Any], *, file: Path) -> tuple[UnknownKey, ...]: ...
def unknown_keys_in_file(path: Path) -> tuple[UnknownKey, ...]: ...
def unknown_keys_in_layers(layers: Sequence[SettingsFileInfo]) -> tuple[UnknownKey, ...]: ...
def describe(findings: Sequence[UnknownKey]) -> str: ...   # C1 suffix, "" when empty
```

Not exported from any public folder; no public API change.

## C4. The one declaration (Revision 2 — pending M1)

Extends the existing `_types/settings.py` types (public re-export
`functualize.plugin`, unchanged) and adds func's own declaration as data.

```python
# functualize._types.settings — extended, additive
@dataclass(frozen=True)
class Setting:
    ...                                  # every existing field unchanged
    places: tuple[str, ...] = ()         # ordered lookup places; () == (self.section,)
                                         # "" is the top level. e.g. jobs_directories: ("", "discovery")
    listed: bool = True                  # a settings row / generated help entry
    env: bool = True                     # an environment variable sets it
    # `type` gains "map" (free-form table, keys never checked: [aliases])
    # and "records" (array of tables: [[vault_secret]])

class AppSettingsSchema:
    ...                                  # every existing field and method unchanged
    def setting(self, name: str) -> Setting | None: ...
    def sections(self) -> frozenset[str]: ...                 # "" excluded
    def keys_in(self, section: str) -> frozenset[str]: ...    # every key accepted there
    def value_in(self, table: Mapping[str, Any], setting: Setting) -> Any | None: ...
        # first place in `places` that holds the key; None otherwise

# functualize._types.functualize_settings — NEW, data only
ROOT: Setting                 # "root", bool, listed=False, env=False
JOBS_DIRECTORIES: Setting     # places=("", "discovery")
PLUGINS_DIRECTORIES: Setting
IMPORT_LIBS: Setting
EXTRA_DIRECTORIES: Setting
EXCLUDE_PATTERNS: Setting
VAULT_SECRET: Setting         # type="records", listed=False, env=False
ALIASES: Setting              # type="map", listed=False
PLUGINS_DISABLED: Setting     # "plugins.disabled", list
...                           # every setting in today's _BASE_SETTINGS and tui_settings()
FUNCTUALIZE_SETTINGS: AppSettingsSchema   # settings=(all of the above), sources, prefixes

# public: functualize.app.config re-exports FUNCTUALIZE_SETTINGS and the constants
```

Rules:
- Every name in today's `_BASE_SETTINGS`, `tui_settings()`, `_RECOGNIZED_*`,
  `LIST_KEYS`, `_DISCOVERY_FINGERPRINT_FIELDS` (minus `pre_filter`, which is
  not a file key) is declared exactly once.
- Display order, defaults, choices, bounds, descriptions, `cli_flag`, `phase`
  and environment variable names equal today's values (AC14).
- No public signature is removed. `FuncSetting`, `FUNC_SETTINGS`,
  `FUNC_SCHEMA`, `register_settings` keep their shapes; they become views
  over the declaration.
