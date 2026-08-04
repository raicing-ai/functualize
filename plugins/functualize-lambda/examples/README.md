# functualize-lambda Examples

The AWS Lambda delivery adapter: run jobs serverless.

| Directory | Demonstrates |
|-----------|--------------|
| [`lambda_handler/`](lambda_handler/) | "Fat Lambda" (one function routing all jobs) and "thin Lambda" (one function per job) deployment patterns |

```bash
cd plugins/functualize-lambda/examples/lambda_handler
uv sync
```

Tests:

```bash
uv run pytest plugins/functualize-lambda/examples/ -v
```
