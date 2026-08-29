# Format Specification — Doc-V Scenario Files

Version: 1
Format: TOML v1.0
Extension: `.toml`
Location: `examples/docs/scenarios/`

## Top-level structure

```toml
[scenario]
name = "unique-name"
version = 1
description = "Human-readable description"

[source]
file = "docs/path/to/file.md"
lines = "start-end"          # or "single-line"
description = "What this verifies"
# block = "code-block-id"    # optional: specific code block label

requires = ["other-scenario"] # optional

[env]
# Global env vars (optional)

[[steps]]
engine = "shell|docker|pty"
description = "Step description"
# ... engine-specific fields
```

## `[scenario]` section

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | str | yes | Unique identifier, kebab-case. Used in reports and `requires` references. |
| `version` | int | yes | Format version. Currently `1`. |
| `description` | str | yes | What this scenario verifies. Shown in reports. |

## `[source]` section

This is the **traceability anchor**. Every scenario MUST have one.

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | str | yes | Path to the doc file being verified, relative to project root. |
| `lines` | str | yes | Line range: `"42"` or `"42-47"`. Refers to the doc's line numbers. |
| `description` | str | yes | What code block or statement is being tested. |
| `block` | str | no | Identifier for a named code block (e.g. fence label, tab heading). Useful when a doc has multiple code blocks at the same line range. |

When the doc file moves or line numbers shift, update this section.
The runner does NOT open the doc file — it uses `[source]` purely for
traceability in reports.

## `[[steps]]` — Action steps

Each step executes one test. Steps run sequentially. A step fails, the
scenario stops (no subsequent steps execute).

### Common fields (all engines)

| Field | Type | Required | Description |
|---|---|---|---|
| `engine` | str | yes | `"shell"`, `"docker"`, or `"pty"` |
| `description` | str | yes | What this step does |
| `timeout` | int | no | Max seconds before step is killed. Default is the run's `--timeout` (120) for every engine — there are no per-engine defaults. A step declaring this wins over the flag. |
| `expected` | dict | yes* | Assertions (required unless `steps` sub-steps are present) |
| `env` | dict | no | Step-specific env vars (merged with scenario-level) |
| `steps` | array | no | Sub-steps for multi-command sequences within a single engine session |

### `expected` assertions

At least one assertion is required per step that has a `command` (not
applicable to steps with `steps` sub-array, which have their own assertions).

| Field | Type | Example |
|---|---|---|
| `exit_code` | int | `0` |
| `stdout_contains` | str | `"Usage:"` |
| `stdout_not_contains` | str | `"Error"` |
| `stderr_contains` | str | `"WARNING"` |
| `stderr_empty` | bool | `true` |
| `stdout_regex` | str | `"(?i)usage:"` |
| `stdout_exact` | str | exact match (rare — prefer `stdout_contains`) |

### Engine: `shell`

Runs a command on the **host** in a subprocess. Use for non-destructive
verification that doesn't need isolation.

```toml
[[steps]]
engine = "shell"
command = "func --help"
expected = { stdout_contains = "Usage:", exit_code = 0 }
timeout = 5
```

| Field | Type | Required | Description |
|---|---|---|---|
| `command` | str | yes | Shell command to run. |
| `cwd` | str | no | Working directory, relative to project root. |

### Engine: `docker`

Runs a command inside an **ephemeral Docker/Podman container**. Use for
installation testing, destructive operations, or clean environments.

```toml
[[steps]]
engine = "docker"
image = "python:3.11-slim"
command = "pip install /dist/*.whl && functualize --version"
expected = { stdout_contains = "functualize", exit_code = 0 }
timeout = 120
volumes = { "/tmp/doc-verify-dist" = "/dist:ro" }
```

| Field | Type | Required | Description |
|---|---|---|---|
| `image` | str | yes | Docker image to use. |
| `command` | str | yes | Command to run inside the container. |
| `volumes` | dict | no | Host path → container path with mode. e.g. `{ "/host/path" = "/container:ro" }` |
| `network` | str | no | `"none"` or omitted (default: bridge). |
| `build_wheel` | bool | no | If true, builds `dist/*.whl` first and mounts `/dist:ro`. Shortcut for the common pattern. |
| `workdir` | str | no | Working directory inside container. Default: `/tmp`. |

Container detection: prefers `podman` (rootless), falls back to `docker`.
The runner also attempts `docker-py` (Python SDK) as primary, falling back to
subprocess calling the CLI.

### Engine: `pty`

Drives a real PTY (pseudo-terminal) using the observe-tui pyte probe. Use for
TUI interaction, TTY-dependent behavior, or interactive prompts.

```toml
[[steps]]
engine = "pty"
description = "TUI SmartBar recognizes ping"
cwd = "examples/standalone/showcase"
command = "uv run func"
cols = 100
rows = 30
actions = [
  { type = "wait", text = "Type a command", timeout = 20 },
  { type = "send", keys = "ping" },
  { type = "wait", text = "● Ready" },
]
```

| Field | Type | Required | Description |
|---|---|---|---|
| `command` | str | yes | Command to run in the PTY. |
| `cwd` | str | no | Working directory, relative to project root. |
| `cols` | int | no | Terminal columns (default: 100). |
| `rows` | int | no | Terminal rows (default: 30). |
| `actions` | array | yes | Ordered action sequence (see below). |

**PTY action types:**

| Type | Params | Description |
|---|---|---|
| `wait` | `text` (str), `timeout` (int, seconds) | Block until `text` appears on screen. Exits with failure on timeout. |
| `send` | `keys` (str) | Type keys. Tokens: `<enter>`, `<tab>`, `<esc>`, `<space>`, `<backspace>`, `<ctrl+X>`, arrow keys. |
| `snap` | `label` (str, optional) | Capture current screen for the report. |
| `sleep` | `duration` (int, seconds) | Wait while output streams. |

The pyte probe is invoked via:
```bash
uv run --with pyte python .agents/skills/observe-tui/scripts/tui_probe.py \
  --cwd <cwd> --cols <cols> --rows <rows> --timeout <timeout> \
  --step "wait:<text>" --step "send:<keys>" \
  -- <command>
```

### Multi-step (sub-steps within a step)

Use when commands must run sequentially in the same environment (shell or
container):

```toml
[[steps]]
engine = "shell"
description = "Scaffold, add job, run"
steps = [
  { command = "cd /tmp/test && rm -rf myapp && func scaffold myapp", expected = { exit_code = 0 } },
  { command = "cd /tmp/test/myapp && func sample run --target test", expected = { stdout_contains = "hello-world", exit_code = 0 } },
]
```

Each sub-step has its own `command` and `expected` block. Sub-steps inherit
the parent's `engine`, `timeout`, `env`, and (for docker) `image`, `volumes`,
etc.

## Scenario dependencies

```toml
requires = ["build-wheel", "installation"]
```

When scenario A `requires` scenario B, B runs first. If B fails, A is skipped.
This is purely ordering — no state is shared between scenarios (each docker
step is a fresh container).

The `requires` field is a list of scenario **names** (not file paths). The
runner resolves them from the `scenarios/` directory.

## Environment variables

Scenarios can define env vars at two levels:

```toml
[env]              # scenario-level, applies to ALL steps
ENVIRONMENT = "prod"

[[steps]]
engine = "shell"
command = "func forecast"
env = { FORECAST_API_URL = "https://staging.example.com" }
# Effective env for this step: { ENVIRONMENT: prod, FORECAST_API_URL: ... }
```

Step-level env merges with/overrides scenario-level env.

## Validation rules

The runner validates scenarios before execution:

1. `[source]` block must exist with `file`, `lines`, `description`
2. `[[steps]]` must have at least one step
3. Each step with `command` must have `expected` with ≥1 assertion
4. Step with `steps` sub-array must not have `command` or `expected`
5. PTY steps must have `actions` array with ≥1 action
6. Docker steps must have `image`
7. `requires` names must reference existing scenario names (warning, not error)

## Versioning

| Version | Changes |
|---|---|
| 1 | Initial format |
