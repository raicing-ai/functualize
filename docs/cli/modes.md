# CLI Execution Modes

The `func` CLI operates in three distinct execution modes, automatically determined by how you invoke it. Each mode uses the same discovery and configuration system but applies it differently.

> **Note:** `func` and `functualize` are aliases for the same CLI. All examples use `func`.

## Mode A: Single-File Execution

Run a specific Python file directly, bypassing project-level discovery.

```bash
func script.py              # Execute the default job in script.py
func script.py deploy       # Execute the 'deploy' function in script.py
func deploy.py --dry-run    # Pass flags to the job
```

### When It Triggers

Mode A activates when the first argument is a path to an existing `.py` file.

### Behavior

- Only the specified file is scanned for jobs — no directory discovery
- Discovery filters (`--require-file-import`, `--exclude`, etc.) still apply to determine which functions in the file qualify as jobs
- If the file contains exactly one qualifying job, it runs immediately
- If the file contains multiple qualifying jobs, you must specify which one to run

### Use Cases

- Quick one-off scripts
- Testing a job file in isolation
- Running a file that lives outside the configured jobs directory

> **See also:** [`examples/standalone/showcase/scripts/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/showcase/scripts/) for working examples.

---

## Mode B: Project Discovery

Discover and run jobs from the current project by name.

```bash
func deploy                 # Run the 'deploy' job discovered from project
func data-sync --verbose    # Run with flags passed to the job
```

### When It Triggers

Mode B activates when the first argument is not a `.py` file path and matches a discovered job name.

### Behavior

- The CLI resolves configuration from the full precedence chain (CLI flags → env vars → project config → global config → defaults)
- Constructs a `DiscoveryConfig` and builds the pre-filter stack
- Scans configured `jobs_directories` (from `pyproject.toml` or `.functualize.toml`)
- Applies all enabled discovery filters (file-level AND job-level)
- Registers qualifying functions as available jobs
- Executes the named job

### Use Cases

- Day-to-day project workflow (the most common mode)
- Running named jobs defined in your project's `jobs/` directory
- Working with team-standard job collections

> **See also:** [`examples/standalone/showcase/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/showcase/) for a working example.

---

## Mode C: Listing and Help

List available jobs or show help information.

```bash
func                        # List all discovered jobs
func --help                 # Show CLI help
func builtin cache show             # Run a built-in subcommand
func builtin config show            # Show resolved configuration
func builtin parallel a b           # Run jobs concurrently
func builtin history                # Recent runs, newest first
func builtin env deploy             # A job's config as env vars
func builtin shell-init bash        # Emit a shell completion script
```

### When It Triggers

Mode C activates when:
- No arguments are provided (lists available jobs)
- `--help` is passed
- A built-in subcommand is invoked. The first-party commands under `builtin`
  are `cache`, `state`, `config`, `domains`, `scaffold`, `workflow`,
  `parallel`, `history`, `env`, `shell-init`, `why`, `version`, and `info`.

### Behavior

- For listing: performs full discovery using the active filter configuration, displays all qualifying jobs
- For help: shows CLI usage, available commands, and global options
- For builtins: executes the built-in command directly under the `builtin` subtree. These are registered as standard Click commands via the `GroupTrie` namespace authority. Builtins are auto-discovered at boot and include `cache`, `state`, `config`, `domains`, `scaffold`, `workflow`, `parallel`, `history`, `env`, `shell-init`, `why`, `version`, and `info`

### Use Cases

- Exploring what jobs are available in a project
- Checking configuration and debugging discovery
- Project scaffolding and cache management

> **See also:** [`examples/standalone/showcase/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/showcase/) for a working example.

---

## Mode Selection Summary

| Invocation | Mode | Trigger Condition |
|---|---|---|
| `func script.py` | A | First arg is a `.py` file that exists |
| `func deploy` | B | First arg matches a discovered job name via `GroupTrie` resolution |
| `func` (no args) | C | No arguments provided — opens inline TUI or lists jobs |
| `func --help` | C | Help flag |
| `func --version` | C | Version flag (pre-boot fast path) |
| `func builtin config show` | C | Built-in subcommand under the `builtin` namespace |
| `func my-alias` | B* | First arg is a configured alias (resolves to job name) |

*Aliases are resolved via the [FallbackCommand chain](config.md) before job lookup.

---

## Group Options: Flags Before the Group Name

A job group can declare flags that every job beneath it accepts. They are typed
**before** the group segment that owns them:

```console
func deploy --env prod web run --image custom
     └─ group ─┘└─ group flag ─┘└─ path ─┘└── the job's own flags ──┘
```

Position is the scope delimiter. A flag after the job name binds to the *job*,
even if a group declares the same name — the `docker` / `kubectl` / `gh`
convention. A group's flags are inherited down the whole path, so `--env` may be
given at any point before its command is reached.

`func <group>` (or `func <group> --help`) lists the options available at that
node, inherited ones included. Values resolve as
`flag > DEPLOY__ENV > [deploy] in the config file > default`.

Everything else mid-path is still an error: a misplaced global option says
"must come before the group name", an undeclared flag says "unknown option
before a command", and both exit 2.

See the [Group Options guide](../guides/group-options.md) for declaring them.

---

## Plugin-Registered Commands

Capability plugins can contribute their own CLI commands — for example the MCP
plugin registers the `mcp` group (`func mcp serve`, `func mcp tools`, …). These
are registered late, at the `APP_READY` boot phase, so pre-boot mode detection
never sees them and classifies `func mcp …` as an unknown command.

Rather than teaching pre-boot classification about plugin groups (which would
require booting or a richer routing cache), `func` resolves them **after boot**,
at zero extra cost — the unknown-command path already boots the full app before
erroring:

- The group listing/execution path (`func <group> [sub]`) and the
  unknown-command fallback both merge `app.get_plugin_commands()` with the
  discovered job groups.
- **Precedence:** a real `.py` file, a built-in, a job group, a job name, and an
  alias all still win first. Within a group, a **job wins** over a plugin
  command on an exact sub-command name conflict (your code overrides a plugin's).
- Plugin commands execute through the same ad-hoc Click path the scaffolded
  project `CliAdapter` uses, so typed options and `--output` behave identically.

Disabling a plugin (via `plugins.disabled`) makes its commands fall back to the
normal "unknown command" error.

---

## How Modes Interact with Discovery

All modes share the same configuration resolution and filter construction pipeline:

1. `resolve_cli_config()` merges settings from all sources
2. `build_pre_filter_from_config()` constructs the filter stack
3. The filter stack is passed to the discovery pipeline

The difference is **scope**:

- **Mode A** — filters apply to a single file
- **Mode B/C** — filters apply to all files in configured directories

See [Discovery Filtering](discovery.md) for the full filter system and [Configuration](config.md) for how settings are resolved.
