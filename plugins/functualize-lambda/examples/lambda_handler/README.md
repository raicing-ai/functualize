# Lambda Handler — Project Example

A functualize project deployed as AWS Lambda functions using the `functualize-lambda` adapter. Demonstrates both "fat Lambda" (single function with routing) and "thin Lambda" (one function per job) patterns.

## Setup

```bash
cd plugins/functualize-lambda/examples/lambda_handler
uv sync
```

## Deployment Patterns

### Fat Lambda (Internal Routing)

Single Lambda function that routes to different jobs based on the event payload:

```python
# handler.py
from lambda_service.app import fat_handler

def handler(event, context):
    return fat_handler(event, context)
```

Event format: `{"job": "process_order", "kwargs": {"order_id": "ORD-123"}}`

### Thin Lambda (Per-Job)

One Lambda function per job — simpler IAM, clearer monitoring:

```python
# handlers/process_order.py
from lambda_service.app import process_order_handler

handler = process_order_handler
```

## Testing Locally

```bash
# Test job functions directly
uv run pytest tests/ -v

# Simulate a Lambda invocation
uv run python -c "
from lambda_service.app import fat_handler
result = fat_handler({'job': 'process_order', 'kwargs': {'order_id': 'ORD-001', 'amount': 99.99}}, None)
print(result)
"
```

## What This Demonstrates

- `FunctualizeApp` with `JobSources(functions=[...])` for explicit registration
- `LambdaAdapter` for AWS Lambda delivery
- Fat Lambda pattern with event routing
- Thin Lambda pattern with `make_handler()`
- `twelve_factor()` config preset (env vars only — no files in Lambda)
- Same jobs testable locally without AWS
