# Quickstart Examples

Runnable code for every step of the [README Quick Start](https://github.com/raicing-ai/functualize#quick-start) — the escalation from a plain script to an AI-enabled, MCP-served, scaffolded project.

Source: [`examples/quickstart/`](https://github.com/raicing-ai/functualize/tree/master/examples/quickstart)

| Step | Directory | Demonstrates |
|------|-----------|--------------|
| 1 | `step1_basic/` | Run a Python script — `RunContext`, `rc.log()` |
| 2 | `step2_config/` | Typed configuration — Pydantic models, layered resolution |
| 3 | `step3_invoke/` | `rc.invoke()` + `rc.track_phase()` pipelines |
| 4 | `step4_tui/` | The inline TUI — bare `func`, SmartBar, panel rings |
| 5 | `step5_ai/` | `ai.complete()` with structured output (`MockAI`, no keys) |
| 6 | `step6_mcp/` | `@job_metadata` visibility + `func mcp serve` |
| 7 | `step7_workflow/` | `@workflow` graphs with gates |
| 8 | `step8_scaffold/` | `func builtin scaffold init` walkthrough → the finished project in [`examples/project/weather_app/`](https://github.com/raicing-ai/functualize/tree/master/examples/project/weather_app) |

## Running

```bash
# From the repo root
uv sync --all-packages
uv run pytest examples/quickstart/ -v

# Any step directly
func examples/quickstart/step1_basic/weather.py forecast
```

Each step directory is self-contained; see [`examples/quickstart/README.md`](https://github.com/raicing-ai/functualize/blob/master/examples/quickstart/README.md) for per-step CLI commands.
