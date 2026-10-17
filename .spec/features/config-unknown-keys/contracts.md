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
