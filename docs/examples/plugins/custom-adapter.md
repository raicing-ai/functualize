# Custom Adapter — Plugin Example

Implement the `AdapterPlugin` protocol to create a custom delivery surface. This example builds a webhook adapter that POSTs job results to a configured URL.

## Source

[`examples/plugins/custom_adapter/`](https://github.com/raicing-ai/functualize/tree/master/examples/plugins/custom_adapter)

## The Protocol

An adapter needs:

```python
class MyAdapter:
    adapter_type: str = "webhook"

    def __call__(self, app) -> None:
        """Initialize with FunctualizeApp."""
        self._app = app

    def run(self, **kwargs) -> Any:
        """Execute and deliver results."""
        ...
```

## Usage

```python
from functualize.app import FunctualizeApp, JobSources
from functualize_webhook import WebhookAdapter

app = FunctualizeApp("my-app", job_sources=JobSources(directories=["./jobs"]))
adapter = WebhookAdapter(webhook_url="https://hooks.example.com/jobs")
adapter(app)
adapter.run(job_name="deploy", kwargs={"version": "v1.0.0"})
```

## Entry Point Registration

```toml
[project.entry-points."functualize.plugins"]
webhook = "functualize_webhook:WebhookAdapter"
```

## Key Concepts

- **`adapter_type`** — String identifier for the adapter
- **`__call__(app)`** — Receives the FunctualizeApp during boot
- **`app.execute()`** — Use the app's execution engine from within the adapter
- **Testable without network** — Track deliveries in a list for assertions

## Built-in Adapters

Functualize ships with:

| Adapter | Package | Delivery |
|---------|---------|----------|
| CLI | built-in | Click commands |
| TUI | built-in | Terminal forms |
| HTTP | `functualize-http` | REST API |
| Lambda | `functualize-lambda` | AWS Lambda |
| MCP | `functualize-mcp` | AI agent protocol |

## Related

- [Custom State Backend](custom-state-backend.md)
- [HTTP Service Example](../project/http-service.md)
- [Lambda Handler Example](../project/lambda-handler.md)
