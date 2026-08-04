# Hello World — Standalone Job

The simplest functualize job. One file, one function, run with `func`.

## Source

[`examples/standalone/showcase/scripts/hello.py`](https://github.com/raicing-ai/functualize/blob/master/examples/standalone/showcase/scripts/hello.py)

## Running

```bash
cd examples/standalone/showcase
func scripts/hello.py greet --name World
func scripts/hello.py greet --name Alice --enthusiasm 3
```

## The Code

```python
from pydantic import BaseModel, Field
from functualize.job.context import RunContext
from functualize.job.decorators import job_metadata


class GreetConfig(BaseModel):
    name: str = Field(description="Name of the person to greet")
    enthusiasm: int = Field(default=1, ge=1, le=5, description="Enthusiasm level (1-5)")


@job_metadata(
    ai_description="Greet a person with configurable enthusiasm",
    tags=["demo", "safe"],
    visibility="external",
)
def greet(config: GreetConfig, rc: RunContext) -> str:
    exclamation = "!" * config.enthusiasm
    message = f"Hello, {config.name}{exclamation}"
    rc.log(message)
    return message
```

## Key Concepts

- **Pydantic config model** — `GreetConfig` defines typed parameters with validation and descriptions
- **Function name = job name** — `func scripts/hello.py greet` routes to `def greet`
- **`@job_metadata`** — Optional decorator adding AI discoverability and MCP exposure metadata
- **`RunContext`** — Structured logging and execution context (injected by the engine)

## Related

- [Getting Started](../../getting-started/quickstart.md)
- [Jobs and Auto-Discovery Guide](../../guides/jobs-discovery.md)
- [CLI Reference](../../cli/index.md)
