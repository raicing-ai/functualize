# functualize-lambda

> **Status: Published** — Independently installable from PyPI.

AWS Lambda adapter plugin for [functualize](https://github.com/raicing-ai/functualize).

Supports two deployment patterns:

1. **Fat Lambda** — Single Lambda function with internal routing via `event["job"]`
2. **Thin Lambda** — One Lambda per job via `make_handler(job_name)`

## Installation

```bash
pip install functualize-lambda
```

## Usage

### Fat Lambda (internal routing)

```python
from functualize.app import FunctualizeApp, JobSources
from functualize_lambda import LambdaAdapter

app = FunctualizeApp("my-app", job_sources=JobSources(functions=[deploy, rollback]))
adapter = LambdaAdapter()
adapter(app)

def handler(event, context):
    return adapter.run(event, context)
```

Events should have the shape: `{"job": "job_name", "kwargs": {"key": "value"}}`

### Thin Lambda (per-job handler)

```python
from functualize.app import FunctualizeApp, JobSources
from functualize_lambda import LambdaAdapter

app = FunctualizeApp("my-app", job_sources=JobSources(functions=[deploy]))
adapter = LambdaAdapter()
adapter(app)

handler = adapter.make_handler("deploy")
```
