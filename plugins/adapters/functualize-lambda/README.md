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

### The event envelope

**Breaking change in this release.** A job's parameters used to sit under
`kwargs`; they are now under `arguments`, with the control inputs beside them.

```jsonc
// Before
{"job": "deploy", "kwargs": {"target": "prod"}}

// After
{
  "job":                  "deploy",
  "arguments":            {"target": "prod"},
  "group_option_values":  {"env": "staging"},
  "scope_id":             "run-42",
  "force":                true
}
```

The nesting is the fix, not decoration: with the parameters flat against the
control inputs, an argument named `scope_id` chose the workflow scope the run
joined instead of reaching the job.

`scope_id` is what makes a gated workflow **resumable over Lambda** — invoke,
read the id back from the result, answer the gate, invoke again with the same
id. All fields but `job` are optional, and one parser
(`functualize.types.request_from_envelope`) serves every wire surface, so
Lambda and HTTP cannot drift apart on what a payload means.

### Thin Lambda (per-job handler)

```python
from functualize.app import FunctualizeApp, JobSources
from functualize_lambda import LambdaAdapter

app = FunctualizeApp("my-app", job_sources=JobSources(functions=[deploy]))
adapter = LambdaAdapter()
adapter(app)

handler = adapter.make_handler("deploy")
```
