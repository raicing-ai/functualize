# Step 8 — Scaffold and Distribute as a CLI

This step is a walkthrough rather than checked-in code: `func builtin scaffold init` *generates* a new project, so run it yourself.

```bash
func builtin scaffold init weather-app
cd weather-app
uv sync
```

Generated layout:

```
weather-app/
├── pyproject.toml        # [project.scripts] weather-app entry point
├── config.base.toml
└── src/weather_app/
    ├── __init__.py
    ├── main.py           # FunctualizeApp wiring
    └── jobs/
        └── sample_job.py
```

Move your quickstart weather jobs into `src/weather_app/jobs/weather.py`, then install it as a global command:

```bash
uv tool install -e .
weather-app forecast --city Tokyo --days 5
```

Add `functualize-mcp` to `dependencies` in `pyproject.toml` and the MCP commands appear automatically:

```bash
weather-app mcp serve
```

## The finished result, checked in

A completed version of this step — the weather jobs living in a real project with layered config and an entry point — is [`examples/project/weather_app/`](../../project/weather_app/).

## Related Documentation

- [Scaffold Commands](../../../docs/cli/scaffold.md)
- [Usage Modes](../../../docs/guides/modes.md)
