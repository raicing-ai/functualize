# User App Commands

Commands and global options available in every application built with Functualize. When you scaffold a project with `func builtin scaffold init` and install it as a CLI, these are automatically registered alongside your custom job commands.

## Global Options

```
<your-app> [OPTIONS] COMMAND [ARGS]...
```

Global options are processed before any sub-command runs. They control logging verbosity, environment variable loading, and configuration directory resolution.

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--log-level` | `string` | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL. |
| `--dotenv-file` | `path` | `None` | Path to the .env file to load environment variables from. |
| `--config-directory` | `path` | `None` (auto-discovered) | Path to the config directory. When not specified, searches upward from CWD for config files, then falls back to the OS-specific user config directory. |

---

## `show-info`

```
<your-app> show-info [OPTIONS]
```

Show current CLI configuration, discovered jobs, and resolved config values. This introspection command displays general info (log level, environment, config directory), loaded config files with interpolated values, discovered jobs, mounted child projects, and dotenv file status.

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--job` | `string` | `None` | Show resolved JobConfig values for a specific job, including the source of each value (env var, config file, or model default). |
| `--show-env-vars` | `bool` | `False` | Display all current process environment variables. |

---

## Interactive TUI

```
<your-app>
```

There is no `tui` subcommand. Running the app **bare** (no arguments) in an
interactive terminal launches the inline TUI automatically — a SmartBar where
you type a job name and see a live pre-flight form built from the job's
metadata, letting you fill in parameters visually and run without memorizing
option names. When stdin/stdout are not a TTY (piped, CI, MCP), the same bare
invocation prints the job list instead of launching the TUI.
