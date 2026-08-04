# Lambda Handler — Project Example

A functualize project deployed as AWS Lambda functions. Demonstrates both "fat Lambda" (single function with routing) and "thin Lambda" (one function per job) patterns.

## Source

[`plugins/functualize-lambda/examples/lambda_handler/`](https://github.com/raicing-ai/functualize/tree/master/plugins/functualize-lambda/examples/lambda_handler)

## Setup

```bash
cd plugins/functualize-lambda/examples/lambda_handler
uv sync
```

## Deployment Patterns

### Fat Lambda

Single Lambda function that routes internally:

```python
from lambda_service.app import fat_handler

def handler(event, context):
    return fat_handler(event, context)
```

Event: `{"job": "process_order", "kwargs": {"order_id": "ORD-123", "amount": 49.99}}`

### Thin Lambda

One Lambda per job for simpler IAM and monitoring:

```python
from lambda_service.app import process_order_handler
handler = process_order_handler
```

## Key Concepts

- **`JobSources(functions=[...])`** — Explicit registration (no filesystem scanning for fast cold starts)
- **`LambdaAdapter`** — Translates Lambda events to job execution
- **`twelve_factor()`** — Env vars only (Lambda has no filesystem config files)
- **`make_handler(name)`** — Creates a per-job Lambda handler function
- **Testable locally** — Jobs work without AWS; test with plain function calls

## Testing Locally

```bash
uv run pytest tests/ -v

# Or simulate a Lambda invocation
python -c "
from lambda_service.app import fat_handler
result = fat_handler({'job': 'process_order', 'kwargs': {'order_id': 'ORD-001', 'amount': 99.99}}, None)
print(result)
"
```

## Related

- [HTTP Service Example](http-service.md) — Same pattern with HTTP adapter
- [Plugins Guide](../../guides/plugins.md)
