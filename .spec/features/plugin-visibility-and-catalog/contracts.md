# Contracts — plugin visibility and catalog

External interfaces only: declared CLI surfaces, exported signatures, and the
JSON payloads they emit. Internal types belong in `schema.md`.

---

## 1. CLI surface

### 1.1 Unchanged — pinned by AC-A10

```
func --help
```

Output is **byte-identical** to the current output: usage line, the global
options block, and a single `Commands:` entry —

```
Commands:
  builtin  First-party commands, kept out of the job namespace.
```

— followed by the agent epilog. No job, group, or plugin command may be added.
This is a contract, not an incidental property.

### 1.2 Existing, unchanged behaviour

```
func builtin plugin list [--format text|json]
func builtin plugin install PACKAGE [-y|--yes]
func builtin plugin uninstall PACKAGE [-y|--yes]
```

`list` continues to report installed extensions grouped by raw entry-point
group. Its text and JSON shapes are unchanged — `available` is a new command,
not a redefinition of `list`.

### 1.3 New — `available`

```
func builtin plugin available [--format text|json] [--remote]
```

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--format` | `text` \| `json` | `text` | Render as columns or as JSON. Mirrors `list`. |
| `--remote` | flag | off | Additionally query PyPI for `functualize-*`. Off means **no outbound request is made**. |

Exit codes: `0` on success, including when `--remote` fails to reach the
network (degrades to the shipped catalog and warns on stderr).

Text rendering groups by kind, in this order: adapters, domains,
implementations, then any uncurated remote entries. Installed rows are marked.

### 1.4 New — `install --recommended`

```
func builtin plugin install --recommended [-y|--yes]
func builtin plugin install PACKAGE [-y|--yes]
```

`--recommended` and a positional `PACKAGE` are mutually exclusive; supplying
both is a usage error. `--recommended` reuses the existing planning,
confirmation, execution, and `manifest.record_addition` path — it is a
different *input* to the same mechanism, not a second installer.

---

## 2. JSON payloads

### 2.1 `available --format json`

A JSON array, one object per plugin:

```json
[
  {
    "name": "mcp",
    "distribution": "functualize-mcp",
    "kind": "adapter",
    "description": "Expose jobs as MCP tools",
    "installed": true,
    "recommended": true,
    "source": "catalog"
  }
]
```

| Field | Type | Notes |
|---|---|---|
| `name` | `string` | Registered/short name (`mcp`), not the distribution. |
| `distribution` | `string \| null` | Package name. `null` only when metadata is unreadable, matching `ExtensionEntry.distribution`. |
| `kind` | `"adapter" \| "domain" \| "implementation" \| "unknown"` | `unknown` only for a remote entry whose group cannot be known without installing it. |
| `description` | `string` | One line. Empty string when unavailable, never `null`. |
| `installed` | `boolean` | From the metadata snapshot taken once at command start. |
| `recommended` | `boolean` | Whether `install --recommended` would install it. |
| `source` | `"catalog" \| "installed" \| "remote"` | Where this row came from. `remote` rows are not curated by this project. |

Field names are additive against `ExtensionEntry.to_json()`
(`name`, `distribution`, `group`) rather than a rename of it — `list`'s payload
is unchanged.

---

## 3. Exported signatures

### 3.1 Classification — new shared helper

Kind is derived from the entry-point group name. No hardcoded plugin-name list.

```python
def classify_group(group: str) -> PluginKind:
    """Map a `functualize.*` entry-point group to its plugin kind.

    `functualize.plugins`      -> adapter
    `functualize.domains`      -> domain
    `functualize.*_providers`  -> implementation
    anything else              -> unknown

    `functualize.jobs` is not an extension and must be filtered by the caller
    before reaching here (see `_cli/plugin_cmd._NOT_EXTENSIONS`).
    """
```

`PluginKind` is a `str`-valued enum so it serializes directly into the JSON
payload above.

**Placement is an open question (spec §Open questions 1).** It must be reachable
from both `_cli/plugin_cmd.py` — which may import public packages only — and the
command tree in `app/commands.py`. Resolve in Plan; a public-surface addition
may require an ADR.

### 3.2 Catalog access

```python
def load_catalog() -> tuple[CatalogEntry, ...]:
    """The curated plugin manifest shipped inside core. No network, no I/O
    outside the package."""

def recommended_distributions() -> tuple[str, ...]:
    """Distribution names `install --recommended` installs, in install order."""
```

`recommended_distributions()` is the single source the CLI and the drift test
(AC-B7) both read, so they cannot disagree.

### 3.3 Command tree — extended composition

`build_command_tree` keeps its signature. Its *contract* gains plugin nodes:

```python
def build_command_tree(app: FunctualizeApp) -> list[CommandNode]:
    """The shell's one command tree: user jobs, plugin commands, then the
    reserved `builtin` subtree.

    Jobs first, plugin nodes next, `builtin` last. A job wins over a plugin
    command on an exact path conflict, and the shadowed plugin command is
    absent from the returned tree rather than skipped at lookup time —
    matching `_dispatch_group`'s D3 rule.
    """
```

A new provider satisfying the existing `CommandProvider` protocol
(`_types/commands.py`) supplies the plugin nodes. No change to `CommandProvider`
or to `CommandNode`.

### 3.4 Plugin node — `CommandNode` conformance

The plugin node implements the existing protocol unchanged:

| Member | Value for a plugin node |
|---|---|
| `name` | Namespace segment, or the command name when `namespace is None`. |
| `help_text` | `PluginCommand.help_text`, first line. For a namespace node, a count summary. |
| `needs_terminal` | Always `False`. `PluginCommand` carries no terminal declaration. |
| `children()` | The namespace's commands; empty for an un-namespaced command. |
| `params()` | CLI-facing parameters derived from the callback signature. |
| `execute(args)` | Invokes the callback; returns a process-style exit code. |

### 3.5 Unchanged inputs

`PluginCommand` (`_types/descriptors.py:547`) is **not modified** by this
feature — `name`, `callback`, `help_text`, `namespace` are sufficient. In
particular no terminal-affinity field is added (spec §Open questions 2).

`app.get_plugin_commands() -> list[PluginCommand]` (`app/core.py:1080`) is
unchanged and becomes the new provider's single input.

---

## 4. Invariants the implementation must not break

1. `func --help` output is byte-identical (AC-A10).
2. `plugin list` text and JSON shapes are unchanged.
3. The metadata snapshot is read once per command invocation and never re-read
   after an install in the same process (`_cli/plugin_cmd.py:22-27`).
4. Entry-point groups are discovered, never enumerated
   (`_cli/plugin_cmd.py:16-21`; `_plugins/domain_registry.py:246`).
5. `functualize.jobs` is excluded from every extension listing.
6. `_cli/` imports no `_`-prefixed package (constitution, Forbidden Patterns).
7. Tree precedence and `_dispatch_group` precedence agree for identical inputs.
