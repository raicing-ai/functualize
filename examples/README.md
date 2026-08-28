# Functualize Examples

Working examples demonstrating functualize usage patterns — from single-file scripts to full project deployments to building your own plugins.

## Directory Structure

```
examples/
├── .devcontainer/          ← Codespaces / Dev Container config (run examples in isolation)
├── quickstart/             ← The README Quick Start, step by step (1–8)
├── standalone/             ← Feature reference: discovery, config, AI, inline TUI
├── project/                ← Full FunctualizeApp projects
└── plugins/                ← Creating your own plugins
```

## Categories

### [quickstart/](quickstart/)

Runnable code for every step of the [README Quick Start](../README.md#quick-start) — the escalation from a plain script to an AI-enabled, MCP-served, scaffolded project.

`step1_basic` → `step2_config` → `step3_invoke` → `step4_tui` → `step5_ai` → `step6_mcp` → `step7_workflow` → `step8_scaffold`

### [standalone/](standalone/)

Feature reference, no project setup needed — six self-contained directories,
each README a step-by-step verification checklist:

- **showcase/** — the all-in-one project: CLI modes A/B/C, the full inline TUI
  (SmartBar, panels, completions, config inspector, displays), every rendering
  surface, unix-style args + stdin, and AI in both directions
- **discovery_lab/** — all six discovery filters + global dirs, flipped per-run
  via env vars / CLI flags over one jobs tree
- **config_lab/** — the config precedence chain (CLI > env > project > global > defaults)
- **secrets_lab/** — declaring a credential with `Secret[str]`, what `func builtin
  env` reveals, and the set / unset / required-missing distinction, with a decoy
  field beside it that no heuristic should mask
- **group_options_lab/** — flags that belong to a group rather than a job, typed
  mid-path (`deploy --env prod web --region eu-west-1 run v1.2`), two levels deep
- **deploy_tool/** — an app that is *not* `func`: its own command name, config
  table, `DEPLOY_TOOL_*` env prefix and generated root flags

### [project/](project/)

Full applications using `FunctualizeApp`:

- **weather_app** — The flagship: Quick Start jobs as a scaffolded project with an entry point and layered config
- **monorepo_children** — One parent app mounting child projects as namespaced job groups

### [plugins/](plugins/)

Create your own plugins for the functualize ecosystem:

- **custom_state_backend** — Implement the `StateBackend` protocol
- **custom_adapter** — Implement the `AdapterPlugin` protocol
- **file_based_plugin** — Zero-packaging plugin in `.functualize/plugins/`

### Plugin usage examples

Examples of *using* each first-party plugin live inside the plugin itself: `plugins/<name>/examples/` — e.g. [`functualize-mcp`](../plugins/functualize-mcp/examples/), [`functualize-http`](../plugins/functualize-http/examples/), [`functualize-flow-viz`](../plugins/functualize-flow-viz/examples/).

## Running Examples

All examples can be run inside the provided Dev Container for full isolation. Alternatively, install dependencies locally:

```bash
# From the repo root — installs all workspace packages (required for AI/plugin examples)
uv sync --all-packages

# Run any standalone example
cd examples/standalone/showcase
func scripts/hello.py greet --name World

# Run the flagship project example
cd examples/project/weather_app
uv sync
uv run weather-app forecast --city Tokyo
```

## Tests

```bash
# All example tests (requires uv sync --all-packages first)
uv run pytest examples/ -v

# Per-plugin example tests run explicitly, like plugin tests
uv run pytest plugins/functualize-mcp/examples/ -v
```

## Dev Container

Open this folder in VS Code with the Dev Containers extension, or use GitHub Codespaces. The `.devcontainer` configuration provides:

- Python 3.11+
- uv package manager
- All functualize packages pre-installed
- Port forwarding for HTTP examples
