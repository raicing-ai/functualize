# Configuration

The `func` CLI uses a layered configuration system. Settings can come from CLI flags, environment variables, project files, or a global config file — with a clear precedence chain determining which value wins.

## Precedence Chain

Settings are resolved from highest to lowest priority. The first non-empty value wins:

```
┌─────────────────────────────────────────────────┐
│  1. CLI flags (--require-file-import, etc.)     │  ← Highest priority
├─────────────────────────────────────────────────┤
│  2. FUNCTUALIZE_* environment variables         │
├─────────────────────────────────────────────────┤
│  3. pyproject.toml [tool.functualize]           │
├─────────────────────────────────────────────────┤
│  4. .functualize.toml (only if no pyproject)    │
├─────────────────────────────────────────────────┤
│  5. ~/.config/functualize/config.toml           │
├─────────────────────────────────────────────────┤
│  6. Built-in defaults (all unset/None)          │  ← Lowest priority
└─────────────────────────────────────────────────┘
```

> **See also:** [`examples/standalone/config_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/config_lab/) for a working precedence demo.

---

## Global Config File

The global config provides persistent user-level preferences that apply across all projects.

### Location

```
$XDG_CONFIG_HOME/functualize/config.toml
```

Falls back to `~/.config/functualize/config.toml` when `$XDG_CONFIG_HOME` is unset or empty.

### Schema

```toml
[discovery]
require_file_prefix = "job_"                      # optional
require_file_postfix = "_task"                    # optional
require_file_import = "functualize"               # optional
require_file_marker = "__functualize__"           # optional
require_job_decorators = ["job", "workflow"]       # optional
require_job_prefix = "run_"                       # optional
require_job_postfix = "_job"                      # optional
extra_directories = ["~/.config/functualize/jobs"] # optional, max 20 entries
exclude_patterns = ["**/test_*.py"]               # optional, max 50 entries

[cli]
output = "rich"       # "rich" | "plain" | "json"
show_timing = false

[aliases]
d = "deploy"
m = "migrate"
r = "run_tests"
```

All fields are optional. When absent, no constraint is applied (baseline convention mode).

See [Global Config Directory](global-config-directory.md) for the full directory layout.

---

## Project Config

### pyproject.toml

The primary project-level config location:

```toml
[tool.functualize]
jobs_directories = ["jobs"]

[tool.functualize.discovery]
require_file_import = "functualize"
exclude_patterns = ["**/test_*.py", "**/migrations/**"]
```

### .functualize.toml (Alternative)

For non-Python projects or when you prefer a standalone config file:

```toml
# .functualize.toml — root-level keys (no [tool.functualize] nesting)
jobs_directories = ["jobs"]

[discovery]
require_file_import = "functualize"
exclude_patterns = ["**/test_*.py"]
```

**Rules:**
- If `pyproject.toml` contains `[tool.functualize]`, `.functualize.toml` is ignored
- If `pyproject.toml` lacks `[tool.functualize]` (or doesn't exist), `.functualize.toml` is used
- Both formats support the same settings with the same semantics

**Key placement:** the directory-list keys (`jobs_directories`,
`extra_directories`, `exclude_patterns`, `import_libs`) are accepted both at
the top level and under `[discovery]`; the top-level location is checked
first. `jobs_directories` is consumed by the CLI's project discovery
(`auto_discover`) — relative paths resolve against the config file's own
directory, and entries from every config layer in the upward walk contribute
(nearest layer first).

> **See also:** [`examples/standalone/showcase/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/showcase/) for a `.functualize.toml` example.

---

## Environment Variables

Override any setting via environment variables using the `FUNCTUALIZE_` prefix.

### Naming Convention

The env var name is constructed by uppercasing the full key path with underscores:

```
[section].key_name → FUNCTUALIZE_SECTION_KEY_NAME
```

### Examples

| Config Key | Environment Variable |
|---|---|
| `[discovery].require_file_import` | `FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT` |
| `[discovery].require_file_prefix` | `FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_PREFIX` |
| `[cli].output` | `FUNCTUALIZE_CLI_OUTPUT` |
| `[cli].show_timing` | `FUNCTUALIZE_CLI_SHOW_TIMING` |

### Top-Level Keys

Recognized top-level (non-section) keys map directly, without a section
segment:

| Config Key | Environment Variable |
|---|---|
| `dotenv` | `FUNCTUALIZE_DOTENV` |
| `dotenv_path` | `FUNCTUALIZE_DOTENV_PATH` |
| `import_libs` | `FUNCTUALIZE_IMPORT_LIBS` |
| `jobs_directories` | `FUNCTUALIZE_JOBS_DIRECTORIES` |
| `extra_directories` | `FUNCTUALIZE_EXTRA_DIRECTORIES` |

```bash
export FUNCTUALIZE_DOTENV=true
export FUNCTUALIZE_DOTENV_PATH=.env.local
```

### Boolean Values

Boolean env vars accept (case-insensitive): `true`, `1`, `false`, `0`.

```bash
export FUNCTUALIZE_CLI_SHOW_TIMING=true
export FUNCTUALIZE_CLI_SHOW_TIMING=1     # equivalent
```

### Empty Values

An empty string is treated as **unset** — resolution continues to the next level:

```bash
export FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT=""  # treated as unset
```

### List Values

List-typed settings (like `exclude_patterns`) use comma separation in env vars:

```bash
export FUNCTUALIZE_DISCOVERY_EXCLUDE_PATTERNS="**/test_*.py,**/migrations/**"
```

---

## List Merge Behavior

When list values (like `exclude_patterns`, `extra_directories`) exist at multiple levels, they are **concatenated and deduplicated**:

- Project-level entries come first
- Global-level entries are appended
- Duplicates are removed (project-level entry is retained)

```toml
# pyproject.toml
[tool.functualize.discovery]
exclude_patterns = ["**/test_*.py"]

# ~/.config/functualize/config.toml
[discovery]
exclude_patterns = ["**/test_*.py", "**/migrations/**"]

# Resolved: ["**/test_*.py", "**/migrations/**"]
# (duplicate removed, project-level retained)
```

---

## `func builtin config` Commands

Built-in commands for inspecting and editing your configuration.

### `func builtin config show`

Display the fully resolved configuration with source annotations:

```bash
$ func builtin config show
[discovery]
require_file_import = "functualize"  # from: pyproject.toml
exclude_patterns = ["**/test_*.py"]  # from: global config

[cli]
output = "rich"                      # from: default
show_timing = false                  # from: default

[aliases]
d = "deploy"                         # from: global config
```

### `func builtin config path`

Show config file paths with their status:

```bash
$ func builtin config path
[used]    /home/user/project/pyproject.toml
[missing] /home/user/project/.functualize.toml
[used]    /home/user/.config/functualize/config.toml
```

Status indicators:
- **used** — file exists and contributed values
- **found** — file exists but all values were overridden by higher-priority sources
- **missing** — file does not exist

### `func builtin config edit`

Open the global config file in your editor:

```bash
$ func builtin config edit
```

Editor resolution order:
1. `$EDITOR`
2. `$VISUAL`
3. Platform default (`vi` on POSIX, `notepad` on Windows)

If the config file doesn't exist, `func builtin config edit` creates the directory and a template file before opening the editor.

If no editor can be resolved, an error message is displayed and the command exits with a non-zero code.

---

## Error Handling

The configuration system follows **warn and continue** for ambient config, **fail fast** for explicit actions:

| Condition | Behavior |
|---|---|
| Global config missing | Proceed with defaults (silent) |
| Global config unreadable (permissions) | Warning to stderr, proceed with defaults |
| TOML syntax error | Warning to stderr with file + line, proceed with defaults |
| Unrecognized section in config | Silently ignored |
| Unrecognized key in recognized section | Warning to stderr, key ignored |
| Type mismatch for recognized key | Warning to stderr, schema default substituted |
| Invalid `[cli].output` value | Warning, falls back to "rich" |
| Invalid alias key (pattern mismatch) | Warning, alias skipped |
| Invalid UTF-8 in config file | Warning, proceed with defaults |
| `--dotenv-file` points to missing file | Error + non-zero exit (explicit = required) |
| `.env` missing with auto-load | Proceed silently (opportunistic) |

---

## Dotenv Support

The CLI can auto-load `.env` files for environment variable injection.

```toml
# pyproject.toml — top-level keys, NOT a [tool.functualize.config] section
[tool.functualize]
dotenv = true                    # enable auto-loading
# dotenv_path = ".env.local"    # optional: explicit path
```

### CLI Flags

```bash
func --dotenv-file .env.local deploy   # explicit file (required to exist)
func --no-dotenv deploy                # suppress all .env loading
```

### Environment Variables

```bash
export FUNCTUALIZE_DOTENV=true            # enable auto-loading
export FUNCTUALIZE_DOTENV_PATH=.env.local # explicit path (opportunistic)
```

### Behavior

- `dotenv = false` (default): no `.env` loading unless `--dotenv-file` is provided
- `dotenv = true`: auto-loads `.env` from CWD (missing file = no error)
- `dotenv_path = "..."`: loads the named file (missing file = warning, no error)
- `--dotenv-file`: overrides all other settings, file must exist
- `--no-dotenv`: suppresses all loading regardless of config
- Loaded values never override variables already set in the shell (`override=False`)

> **Ordering caveat:** dotenv settings are read from the resolved CLI config,
> so the `.env` file itself cannot influence CLI config resolution (e.g. a
> `FUNCTUALIZE_CLI_OUTPUT` value inside `.env` does not affect the current
> invocation's output format). Job config resolution through `EnvSource`
> *does* see `.env` values — the file is loaded before the resolution chain
> is built at app boot.
- Loading happens after flag parsing, before job execution
