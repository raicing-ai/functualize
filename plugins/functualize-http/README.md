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
- `POST /jobs/{job_name}/execute` — Execute a job with JSON body as kwargs
