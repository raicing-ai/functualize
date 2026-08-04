# Quickstart Examples

Working examples for each step in the [README Quick Start](../../README.md#quick-start). Each sub-directory is self-contained; steps with runnable code have tests proving it works.

## Structure

| Directory | README Step | Description |
|-----------|-------------|-------------|
| `step1_basic/` | Step 1 | Run a Python script — basic RunContext, rc.log() |
| `step2_config/` | Step 2 | Typed configuration — Pydantic models, config resolution |
| `step3_invoke/` | Step 3 | Invoke + phase tracking — rc.invoke(), rc.track_phase() |
| `step4_tui/` | Step 4 | Browse and run jobs interactively — the inline TUI (bare `func`) |
| `step5_ai/` | Step 5 | AI with structured output — ai.complete() + response_model (MockAI, no keys) |
| `step6_mcp/` | Step 6 | Expose jobs to AI agents — @job_metadata visibility + `func mcp serve` |
| `step7_workflow/` | Step 7 | Workflow checkpoints — @workflow, Step, Edge, gates |
| `step8_scaffold/` | Step 8 | Scaffold and distribute as a CLI (walkthrough — the generated result lives in [`examples/project/weather_app/`](../project/weather_app/)) |

## Running Tests

```bash
# From the repo root (step5 needs the workspace plugins installed)
uv sync --all-packages
uv run pytest examples/quickstart/ -v
```

## Running via CLI

```bash
# Step 1
func examples/quickstart/step1_basic/weather.py forecast

# Step 2
func examples/quickstart/step2_config/weather.py forecast --city Tokyo --days 5

# Step 3
func examples/quickstart/step3_invoke/weather.py morning_report --city Tokyo --days 5

# Step 4 — bare func opens the inline TUI
cd examples/quickstart/step4_tui && func

# Step 5
func examples/quickstart/step5_ai/weather.py travel_plan --city Tokyo

# Step 6 — serve jobs as MCP tools (Ctrl+C to stop)
cd examples/quickstart/step6_mcp && func mcp serve

# Step 7 — runs until the preferences gate pauses it
func examples/quickstart/step7_workflow/weather.py trip_planner --city Tokyo
```
