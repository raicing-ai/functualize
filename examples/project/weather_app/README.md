# Weather App — Flagship Project Example

The README Quick Start's weather jobs, graduated into a real scaffolded `FunctualizeApp` project (what `func builtin scaffold init weather-app` produces, filled in). Demonstrates the project layout, a console-script entry point, and layered config with environment overlays.

## Directory Structure

```
weather_app/
├── pyproject.toml            ← [project.scripts] weather-app entry point
├── config.base.toml           ← Base config, always loaded
├── config.prod.toml           ← Overlay merged when ENVIRONMENT=prod
├── src/weather_app/
│   ├── main.py               ← FunctualizeApp wiring (classic() preset)
│   └── jobs/
│       └── weather.py        ← forecast, alert, morning_report
└── tests/
    └── test_weather.py
```

## Usage

```bash
cd examples/project/weather_app
uv sync

# Run via the project entry point
uv run weather-app forecast --city Tokyo --days 5
uv run weather-app morning-report --city Tokyo

# Or install globally as a standalone command
uv tool install -e .
weather-app forecast --city Paris

# Layered config in action: the prod overlay changes api_url and days
ENVIRONMENT=prod uv run weather-app forecast --city Tokyo

# The same jobs also work with plain `func` (CWD discovery)
uv run func            # bare func → inline TUI / job listing
```

## What This Demonstrates

- The `func builtin scaffold init` project shape: `src/` layout, `main.py` wiring, `jobs/` directory
- A `[project.scripts]` console entry point (`weather-app`) — distribute your jobs as a CLI
- `classic()` config preset: CLI flags → env vars → `config.base.toml` + `ENVIRONMENT` overlay → defaults
- `@job_metadata` with `visibility="external"` — ready to serve over MCP by adding `functualize-mcp`
- `rc.invoke()` + `rc.track_phase()` pipelines inside a project

## Escalating further

- Add `functualize-mcp` to `dependencies` and run `uv run weather-app mcp serve` — your jobs become MCP tools
- Add `functualize-flow-viz` for a live execution tree on `morning-report`
- See plugin-specific examples in `plugins/<name>/examples/` (e.g. HTTP and Lambda delivery)

## Related Documentation

- [Usage Modes](../../../docs/guides/modes.md)
- [Scaffold Commands](../../../docs/cli/scaffold.md)
- [Configuration](../../../docs/guides/configuration.md)
