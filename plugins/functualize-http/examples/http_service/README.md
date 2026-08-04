# HTTP Service — Project Example

A functualize project deployed as an HTTP API using the `functualize-http` adapter. Same jobs, different delivery surface — no code changes required.

## Setup

```bash
cd plugins/functualize-http/examples/http_service
uv sync
```

## Running

```bash
# Start the HTTP server
uv run python -m http_service

# Or use the CLI adapter (same jobs)
uv run http-service --help
```

## Endpoints

Once the server is running:

```bash
# Health check
curl http://localhost:8000/health

# List available jobs
curl http://localhost:8000/jobs

# Execute a job
curl -X POST http://localhost:8000/jobs/healthcheck/execute \
  -H "Content-Type: application/json" \
  -d '{"service_url": "https://api.example.com", "timeout": 5}'
```

## What This Demonstrates

- `FunctualizeApp` with `JobSources` and `twelve_factor()` config preset
- `HttpAdapter` for HTTP API delivery
- Same jobs work via CLI and HTTP without modification
- Pydantic config models become JSON request schemas
- `@job_metadata` tags control which jobs are exposed
