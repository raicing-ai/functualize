# Global Config Directory

The functualize global config directory stores user-level preferences, per-job config overrides, and user-global job definitions. It follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/).

## Location

```
$XDG_CONFIG_HOME/functualize/
```

Defaults to `~/.config/functualize/` when `$XDG_CONFIG_HOME` is unset or empty.

---

## Directory Layout

```
~/.config/functualize/
├── config.toml           # CLI tool settings (discovery, output, aliases)
├── config.base.toml      # Global job-config defaults (per-job sections)
└── jobs/                 # User-global Python job definitions
    ├── backup.py
    └── cleanup.py
```

### `config.toml`

The main CLI configuration file. Contains `[discovery]`, `[cli]`, and `[aliases]` sections.

```toml
[discovery]
require_file_import = "functualize"
exclude_patterns = ["**/test_*.py"]
extra_directories = ["~/.config/functualize/jobs"]

[cli]
output = "rich"
show_timing = false

[aliases]
d = "deploy"
b = "backup"
```

See [Configuration](config.md) for the full schema and precedence rules.

### `config.base.toml`

Global defaults for job-level configuration. Each section is a job name:

```toml
[deploy]
environment = "staging"
timeout = 300

[migrate]
dry_run = true
```

These values are the lowest priority in the job config resolution chain — project-level and CLI overrides take precedence. Per-job overrides are `[job_name]` sections in any config file on the ladder (project files outrank global).

### `jobs/` — User-Global Job Definitions

Python files placed here can be discovered as jobs across all projects (when configured):

```python
# ~/.config/functualize/jobs/backup.py
def backup_db(log):
    """Back up the database."""
    log("Running global backup job...")
```

To enable global jobs, add the directory to `extra_directories`:

```toml
# config.toml
[discovery]
extra_directories = ["~/.config/functualize/jobs"]
```

> **See also:** [`examples/standalone/discovery_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/discovery_lab/) for a working example (its `global/` directory plays the role of `~/.config/functualize/jobs`).

---

## Per-Job Config Cascading

Job configuration resolves using this cascade (highest to lowest priority):

```
┌────────────────────────────────────────────────────────┐
│  1. CLI flags (--config key=value)                     │
├────────────────────────────────────────────────────────┤
│  2. Environment variables                              │
├────────────────────────────────────────────────────────┤
│  3. Project config files                               │
├────────────────────────────────────────────────────────┤
│  4. Parent/global config.base.toml [<job-name>] sections│  ← Lowest priority
└────────────────────────────────────────────────────────┘
```

Later sources provide defaults for keys not present in earlier sources.

### Example

```toml
# project config.base.toml
[deploy]
environment = "production"

# global config.base.toml
[deploy]
environment = "staging"    # overridden by project config.base.toml
timeout = 300              # not in project file, so this value is used
```

Resolved config for `deploy`:
- `environment` = `"production"` (from project `config.base.toml`)
- `timeout` = `300` (from global `config.base.toml`)

---

## Directory Creation

The global config directory is **never auto-created** during normal CLI operation:

- If the directory doesn't exist, the CLI proceeds with defaults
- If `config.toml` is missing, the CLI proceeds with defaults
- Subdirectories (`jobs/`) are optional — missing ones are ignored

The **only** command that creates the directory is `func builtin config edit`:

```bash
$ func builtin config edit
# Creates ~/.config/functualize/ and config.toml (with template) if missing
# Then opens in $EDITOR
```

---

## XDG Resolution

| `$XDG_CONFIG_HOME` | Resolved Path |
|---|---|
| `/custom/config` | `/custom/config/functualize/config.toml` |
| (empty string) | `~/.config/functualize/config.toml` |
| (unset) | `~/.config/functualize/config.toml` |

Relative paths in `$XDG_CONFIG_HOME` are resolved against the user's home directory.

---

## Tilde Expansion

Paths in `extra_directories` support tilde expansion:

```toml
[discovery]
extra_directories = [
    "~/.config/functualize/jobs",
    "~/shared-jobs",
]
```

If an expanded path doesn't exist, it's silently skipped — no error.
