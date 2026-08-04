# HTTP Service — Project Example

A full functualize project deployed as an HTTP API using the `functualize-http` adapter. Same jobs work via CLI and HTTP — write once, deliver everywhere.

## Source

[`plugins/functualize-http/examples/http_service/`](https://github.com/raicing-ai/functualize/tree/master/plugins/functualize-http/examples/http_service)

## Setup and Running

```bash
cd plugins/functualize-http/examples/http_service
uv sync
uv run python -m http_service   # starts on :8000
```

## Endpoints

```bash
GET  /health                         # Health check
GET  /jobs                           # List available jobs
POST /jobs/healthcheck/execute       # Execute healthcheck
POST /jobs/deploy/execute            # Execute deploy
```

## Project Structure

```
http_service/
├── pyproject.toml
├── src/http_service/
│   ├── __init__.py
│   ├── app.py              # FunctualizeApp + HttpAdapter wiring
│   ├── __main__.py         # python -m entry point
│   └── jobs/
│       ├── healthcheck.py  # GET-style monitoring job
│       └── deploy.py       # POST-style mutation job
└── tests/
    └── test_jobs.py
```

## Key Concepts

- **`FunctualizeApp`** — Wires job sources, config, and the adapter together
- **`HttpAdapter`** — Delivers the same jobs over HTTP (no code changes to jobs)
- **`twelve_factor()`** — Config preset using env vars only (no config files)
- **`JobSources(directories=[...])`** — Auto-discovers jobs from the filesystem
- **Same jobs via CLI** — `uv run http-service --help` works alongside HTTP

## Related

- [Lambda Handler Example](lambda-handler.md) — Same pattern, different adapter
- [Architecture Guide](../../guides/architecture.md)
- [Configuration Guide](../../guides/configuration.md)
