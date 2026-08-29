# Scaffold Commands

The `func builtin scaffold` (or `functualize builtin scaffold`) sub-command provides project scaffolding for creating new Functualize projects and adding components to existing ones.

> **Note:** `func` and `functualize` are aliases for the same CLI. All examples below use `func` but `functualize` works identically.

!!! info "Internal Implementation"
    The scaffold system is implemented in `functualize/_cli/scaffold/` (internal to the CLI package). It is not part of the public Python API — interact with it exclusively through the `func builtin scaffold` CLI command.

## Command Tree

```
func builtin scaffold
├── init <project_name> [--template simple|full-interactivity|plugin-project|job-folder] [--directory .]
└── add
    ├── job <name> [--jobs-dir <path>]
    ├── plugin <name> [--target-dir <path>]
    └── tui-screen <name> [--target-dir <path>]
```

## `func builtin scaffold`

```
func builtin scaffold [OPTIONS] COMMAND [ARGS]...
```

Top-level entry point for project scaffolding. Displays help when invoked without arguments.

### Commands

| Command | Description |
|---------|-------------|
| `init` | Create a new functualize project from a template |
| `add` | Add a component to an existing functualize project |

---

## `func builtin scaffold init`

```
func builtin scaffold init [OPTIONS] PROJECT_NAME
```

Initialize a new functualize project from a template. Creates a complete project directory with configuration, entry point, sample jobs, and documentation appropriate for the chosen template archetype.

### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `PROJECT_NAME` | `string` | Yes | Name of the new project (PEP 508 compliant: lowercase, starts with a letter, contains only letters/digits/hyphens/underscores, max 64 characters). |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--template`, `-t` | `string` | `simple` | Project template to use. |
| `--directory`, `-d` | `path` | `.` (current directory) | Parent directory where the project will be created. |

### Available Templates

| Template | Description |
|----------|-------------|
| `simple` | Minimal project with one sample job and layered configuration |
| `full-interactivity` | All interactivity plugins with samples demonstrating prompts, events, and workflow steps |
| `plugin-project` | Starter for building a functualize plugin with a Surface and PromptCollector |
| `job-folder` | Standalone jobs directory with file-based plugins (no FunctualizeApp, no main.py) |

### Examples

```bash
# Create a minimal project with the default (simple) template
func builtin scaffold init my-project

# Create a project with full interactivity demos
func builtin scaffold init my-app --template full-interactivity

# Create a plugin development project in a specific directory
func builtin scaffold init my-plugin --template plugin-project --directory ~/projects
```

---

## `func builtin scaffold add`

```
func builtin scaffold add COMMAND [ARGS]...
```

Add a component to an existing functualize project. All `add` sub-commands are context-aware — they detect whether you are inside a functualize project (`src/<package>/` structure) or a bare directory and adjust output paths accordingly.

### Sub-commands

| Command | Description |
|---------|-------------|
| `job` | Add a new job file |
| `plugin` | Add a new plugin file |
| `tui-screen` | Add a new TUI screen (Textual Screen subclass + TCSS) |

---

### `func builtin scaffold add job`

```
func builtin scaffold add job [OPTIONS] JOB_NAME
```

Add a new job file. Context-aware: in a project context creates a project-style job module; in a bare context creates a standalone executable file.

#### Context Behavior

| Context | Output Path | Template Style |
|---------|-------------|----------------|
| Project (`src/<package>/` exists) | `src/<package>/jobs/<name>.py` | Project job with `JOB_NAME` and `RunContext` |
| Bare (no project structure) | `./<name>.py` in CWD | Standalone function discoverable by `func` CLI |

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `JOB_NAME` | `string` | Yes | Name of the job to add (PEP 508 compliant). |

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--jobs-dir`, `-j` | `path` | `None` (auto-detected from context) | Path to the jobs directory. Overrides context detection — always uses the project job template. |

#### Examples

```bash
# Inside a project: creates src/<package>/jobs/data_sync.py
func builtin scaffold add job data-sync

# In a bare directory: creates ./data_sync.py as standalone
func builtin scaffold add job data-sync

# Explicit directory override
func builtin scaffold add job data-sync --jobs-dir ./my-jobs
```

---

### `func builtin scaffold add plugin`

```
func builtin scaffold add plugin [OPTIONS] PLUGIN_NAME
```

Add a new plugin file. Context-aware: in a project context creates in the package plugins directory; in a bare context creates a file-based plugin.

#### Context Behavior

| Context | Output Path | Template Style |
|---------|-------------|----------------|
| Project (`src/<package>/` exists) | `src/<package>/plugins/<name>.py` | Entry-point plugin |
| Bare (no project structure) | `.functualize/plugins/<name>.py` | File-based plugin with callable class |

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `PLUGIN_NAME` | `string` | Yes | Name of the plugin to add (PEP 508 compliant). |

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--target-dir`, `-t` | `path` | `None` (auto-detected from context) | Directory where the plugin file will be created. Overrides context detection. |

#### Examples

```bash
# Inside a project: creates src/<package>/plugins/my_renderer.py
func builtin scaffold add plugin my-renderer

# In a bare directory: creates .functualize/plugins/my_renderer.py
func builtin scaffold add plugin my-renderer

# Explicit directory override
func builtin scaffold add plugin my-renderer --target-dir ./custom/plugins
```

---

### `func builtin scaffold add tui-screen`

```
func builtin scaffold add tui-screen [OPTIONS] SCREEN_NAME
```

Add a new TUI screen. Generates a Textual `Screen` subclass and an associated TCSS stylesheet file. Requires a project context or explicit `--target-dir`.

#### Context Behavior

| Context | Output Path | Notes |
|---------|-------------|-------|
| Project (`src/<package>/` exists) | `src/<package>/screens/<name>.py` + `<name>.tcss` | Auto-detected |
| Bare (no project structure) | Error — must specify `--target-dir` | Cannot auto-detect screen location |

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `SCREEN_NAME` | `string` | Yes | Name of the TUI screen to add (PEP 508 compliant). |

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--target-dir`, `-t` | `path` | `None` (auto-detected from context) | Directory where the screen files will be created. Required in bare context. |

#### Examples

```bash
# Inside a project: creates src/<package>/screens/
func builtin scaffold add tui-screen dashboard

# With explicit target directory
func builtin scaffold add tui-screen dashboard --target-dir ./src/myapp/screens
```

---

## Context Detection

The scaffold system automatically detects your working context to determine output paths:

- **Project Context**: The current working directory contains a `src/` subdirectory with at least one child directory containing an `__init__.py` file. The first such package (sorted alphabetically) is used.
- **Bare Context**: Any directory that does not match the project context criteria.

Context detection can always be overridden with explicit path options (`--jobs-dir`, `--target-dir`).

---

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Invalid project/component name | Error to stderr, exit code 1 |
| Target directory already exists (`init`) | Error to stderr, exit code 1 |
| Target file already exists (`add *`) | Error to stderr, exit code 1 |
| Invalid `--template` value | Error listing valid templates, exit code 1 |
| `tui-screen` in bare context without `--target-dir` | Error suggesting `--target-dir`, exit code 1 |
