# Custom Adapter — Plugin Example

Demonstrates implementing the `AdapterPlugin` protocol to create a custom delivery surface. This example builds a webhook adapter that POSTs job results to a configured URL.

## What This Demonstrates

- Implementing the `AdapterPlugin` protocol
- Entry point registration as a delivery adapter
- Plugin boot class with configuration
- Adapter initialization via `__call__(app)`
- The `run()` method for adapter-driven execution
- Testing adapter behavior without network calls

## Plugin Structure

```
custom_adapter/
├── README.md
├── pyproject.toml
├── src/functualize_webhook/
│   ├── __init__.py
│   ├── _adapter.py         # AdapterPlugin implementation
│   └── _config.py          # Adapter configuration model
└── tests/
    └── test_adapter.py
```

## Entry Point Registration

```toml
[project.entry-points."functualize.plugins"]
webhook = "functualize_webhook:WebhookAdapter"
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
