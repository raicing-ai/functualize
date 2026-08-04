# Project Examples

Full applications using `FunctualizeApp`: the structure your jobs graduate into when they outgrow a folder of scripts.

## Examples

| Directory | Description |
|-----------|-------------|
| [`weather_app/`](weather_app/) | The flagship: the README Quick Start weather jobs as a scaffolded project — `src/` layout, console-script entry point, layered config with environment overlays |
| [`monorepo_children/`](monorepo_children/) | Child project composition: a parent app that composes jobs from multiple sub-projects under namespace prefixes, all sharing one Python environment |

Delivery-adapter projects (HTTP, Lambda) live with their plugins:

| Location | Description |
|----------|-------------|
| [`plugins/functualize-http/examples/http_service/`](../../plugins/functualize-http/examples/http_service/) | Jobs exposed as an HTTP API |
| [`plugins/functualize-lambda/examples/lambda_handler/`](../../plugins/functualize-lambda/examples/lambda_handler/) | Jobs deployed to AWS Lambda |

## Architecture

Project examples follow the scaffold shape (`func builtin scaffold init my-project`):

```
my_project/
├── pyproject.toml              # Dependencies + [project.scripts] entry point
├── config.base.ini             # Base config (+ config.<env>.ini overlays)
├── src/my_project/
│   ├── main.py                 # FunctualizeApp wiring
│   └── jobs/                   # Auto-discovered job functions
└── tests/
```

1. **`FunctualizeApp`** — wires job sources, config preset, and plugins
2. **Jobs** — business logic functions with Pydantic config models
3. **Entry point** — your project becomes an installable CLI (`uv tool install -e .`)
4. **Adapters** — the same jobs deliverable via CLI, HTTP, Lambda, or MCP

## Running

```bash
cd examples/project/weather_app
uv sync
uv run weather-app forecast --city Tokyo --days 5
```
