# Hierarchical Projects

Functualize supports two methods for composing jobs from multiple sources into a single CLI application: **flat inclusion** (via `JobSources.directories`) and **hierarchical inclusion** (via `JobSources.children` / `[children]` config). Both can be used together.

## Overview

| Aspect | Flat (`JobSources.directories`) | Hierarchical (`JobSources.children`) |
|--------|--------------------------|---------------------------|
| Namespacing | Jobs appear at top-level (or grouped by `JOB_NAME`) | Jobs are nested under a namespace sub-command |
| Configuration | Uses the **parent's** config exclusively | Each child can have its **own** config directory |
| Identity | Jobs become part of the parent — no separate project boundary | Children retain their project identity and path |
| Discovery | Scans Python module paths (dotted or filesystem) | Scans full project directories for `src/<pkg>/jobs/` layout |
| Use case | Internal modules, tightly coupled jobs | External projects, loosely coupled tools, ticket workspaces |
| Duplicate handling | Warns and skips duplicates at the same level | Each namespace is isolated — no cross-namespace conflicts |

## Flat Inclusion (`JobSources.directories`)

Jobs from these directories are registered directly on the parent app. They share the parent's configuration, hooks, and namespace.

```python
from functualize.app import FunctualizeApp, JobSources

app = FunctualizeApp(
    name="ops-cli",
    job_sources=JobSources(directories=["ops_cli.jobs", "ops_cli.maintenance"]),
)
```

**CLI result:**
```
ops-cli deploy        # from ops_cli.jobs
ops-cli backup        # from ops_cli.maintenance
ops-cli show-info
```

**When to use:**
- Jobs that are part of the same logical application
- Modules within the same repository
- Jobs that share configuration sections and environment variables
- You want a flat, simple command structure

**Configuration behavior:**
- All jobs use the parent's `config.base.ini` and environment overlay
- Environment variables follow the parent's `SECTION_KEY` convention
- `RunContext.config` points to the parent's config directory

## Hierarchical Inclusion (`children`)

Child projects are mounted as namespaced sub-commands. Each child is a standalone functualize project with its own directory structure.

### Configuration-driven (recommended for dynamic setups)

In your parent's `config.base.ini`:

```ini
[children]
# Each key becomes the CLI namespace, value is the path
difftastic = /home/user/code/tickets/dnadvo-3759/difftastic_filter
infra-tools = /home/user/code/tickets/dnadvo-4001/infra-tools
# Glob patterns work too — each matched directory becomes a child
# using its directory name as the namespace
tickets = ~/code/tickets/*/
```

### Programmatic (in `main.py`)

```python
from functualize.app import FunctualizeApp, JobSources

app = FunctualizeApp(
    name="ops-cli",
    job_sources=JobSources(
        directories=["ops_cli.jobs"],
        children={
            "difftastic": "/home/user/code/tickets/dnadvo-3759/difftastic_filter",
            "infra-tools": "../infra-tools",
        },
    ),
)
```

### Glob-based (auto-discover all children matching a pattern)

```python
from functualize.app import FunctualizeApp, JobSources

app = FunctualizeApp(
    name="ops-cli",
    job_sources=JobSources(
        directories=["ops_cli.jobs"],
        children_glob="~/code/tickets/*/",
    ),
)
```

**CLI result:**
```
ops-cli deploy                    # parent's own job
ops-cli difftastic filter         # child's job, namespaced
ops-cli difftastic transform      # another child job
ops-cli infra-tools provision     # different child
ops-cli show-info                 # shows parent + children info
```

**When to use:**
- Separate repositories or project directories
- Ticket-based workflows where each ticket gets its own project
- Team members contributing independent tool projects
- You want namespace isolation between projects
- Children may be added/removed dynamically without modifying parent code

**Configuration behavior:**
- Each child's jobs use the **parent's** config for `RunContext` resolution (the parent is the running app)
- Children can have their own `config.base.ini` for reference (shown in `show-info`)
- The parent's `[children]` section defines the mapping
- No config key collisions between children since they're namespaced

## Child Project Structure

A valid child project must have the standard functualize layout:

```
my-child-project/
├── config.base.ini          # optional — child's own config
├── pyproject.toml
└── src/
    └── my_child_project/
        ├── __init__.py
        ├── main.py          # optional — child can also run standalone
        └── jobs/
            ├── __init__.py
            ├── deploy.py
            └── cleanup.py
```

The hierarchy loader looks for `src/<package>/jobs/` directories. If found, it scans them using the same `JobRegistry` mechanism as flat inclusion.

## Combining Both Methods

You can use both flat and hierarchical inclusion in the same app:

```python
from functualize.app import FunctualizeApp, JobSources

app = FunctualizeApp(
    name="ops-cli",
    # Flat: these jobs appear at top-level
    job_sources=JobSources(
        directories=["ops_cli.jobs"],
        # Hierarchical: these appear under their namespace
        children={
            "difftastic": "~/code/tickets/dnadvo-3759/difftastic_filter",
        },
    ),
)
```

Result:
```
ops-cli deploy                    # flat — from ops_cli.jobs
ops-cli difftastic filter         # hierarchical — from child
```

## Your Use Case: ops-cli with Ticket Projects

For your workflow where `ops-cli` is the parent and each ticket gets a new child project:

**Parent: `ops-cli/config.base.ini`**
```ini
[general]
app_name = ops-cli

[children]
# Add new ticket projects here as you create them
difftastic = ~/code/ticket-workspace/dnadvo-3759/difftastic_filter
# Or use a glob to auto-discover all ticket projects:
# tickets = ~/code/ticket-workspace/*/
```

**Child: `difftastic_filter/`** — scaffold with `func builtin scaffold init difftastic-filter` in a fresh directory, then move/develop your code there.

**Running:**
```bash
# From anywhere (config is discovered by walking up from CWD)
ops-cli difftastic filter --input myfile.txt

# The child can also run standalone if it has its own entry point
difftastic-filter filter --input myfile.txt
```

## Path Resolution

Paths in the `[children]` config section support:
- **Absolute paths:** `/home/user/code/my-project`
- **Home expansion:** `~/code/my-project`
- **Environment variables:** `$WORKSPACE/my-project`
- **Relative paths:** Resolved from the config directory (where `config.base.ini` lives)
- **Glob patterns:** `~/code/tickets/*` — each matched directory becomes a child

## Introspection

Run `ops-cli show-info` to see all mounted children, their paths, and discovered jobs.
