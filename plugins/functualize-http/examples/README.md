# functualize-http Examples

The HTTP delivery adapter: expose the same jobs as API endpoints and CLI commands.

| Directory | Demonstrates |
|-----------|--------------|
| [`http_service/`](http_service/) | A full project serving jobs over HTTP via `HttpAdapter`, with the same jobs runnable via CLI |

```bash
cd plugins/functualize-http/examples/http_service
uv sync
uv run python -m http_service        # starts on :8000

# Same jobs via CLI
uv run http-service healthcheck run --service-url https://example.com
```

Tests:

```bash
uv run pytest plugins/functualize-http/examples/ -v
```
