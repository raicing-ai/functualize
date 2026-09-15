# functualize-http

> **Status: Published** — Independently installable from PyPI.

HTTP delivery adapter plugin for functualize using Python's stdlib asyncio.

## Installation

```bash
pip install functualize-http
```

## Usage

### As an Adapter

```python
from functualize.app import FunctualizeApp
from functualize_http import HttpAdapter

app = FunctualizeApp("myapp", job_sources=...)
adapter = HttpAdapter()
adapter(app)
adapter.run(host="0.0.0.0", port=8000)
```

### As a CLI Plugin

```python
from functualize.app import FunctualizeApp
from functualize_http import HttpServerPlugin

app = FunctualizeApp("myapp", job_sources=...)
plugin = HttpServerPlugin()
plugin(app)
# The 'serve' command is now available in the CLI
```

## Endpoints

- `GET /health` — Health check
- `GET /jobs` — List available jobs
- `POST /jobs/{job_name}/execute` — Execute a job with the envelope below

## The request envelope

**Breaking change in this release.** A job's parameters used to *be* the body;
they are now nested under `arguments`, and the control inputs sit beside them.

```jsonc
// Before — a flat body
{"target": "prod", "retries": 3}

// After — an envelope
{
  "arguments":            {"target": "prod", "retries": 3},
  "group_option_values":  {"env": "staging"},
  "scope_id":             "run-42",
  "force":                true
}
```

The nesting is the fix, not decoration. With a flat body a caller's key could
bind to a control parameter — sending `{"scope_id": "x"}` chose the workflow
scope the run joined rather than passing an argument. Nested, a job parameter
genuinely named `scope_id` arrives as an argument and the scope stays a
separate, deliberate choice.

| field | meaning |
|---|---|
| `arguments` | the job's own parameters |
| `group_option_values` | the group flags a CLI would have typed mid-path |
| `scope_id` | the workflow scope to join — this is what makes a gated workflow **resumable over HTTP**: start it, read the id back from the result metadata, answer the gate, send the same id again |
| `force` | run even when the fingerprint says the job is fresh |

All four are optional. One parser (`functualize.types.request_from_envelope`)
serves every wire surface, so HTTP and Lambda cannot drift apart on what a
payload means.
