# functualize-ai-pydantic

> **Status: Published** — Independently installable from PyPI.

PydanticAI-backed AI implementation plugin for functualize. Bridges the PydanticAI agent framework and LiteLLM model routing into functualize's AI capability system, providing tool calling, streaming, structured output, multi-turn agent loops, and conversation history continuation — all wired automatically via entry-point discovery.

## Installation

```bash
pip install functualize-ai-pydantic
```

## Quick Start

Once installed, the plugin registers itself via the `functualize.ai_providers` entry point. Configure it in your project config:

```toml
[ai]
provider = "pydantic"
model = "claude-sonnet-4-20250514"
```

Then use the AI capability in any functualize job:

```python
from functualize_ai import AI, AIConfig
from functualize_ai_pydantic import PydanticAIProvider

config = AIConfig(model="claude-sonnet-4-20250514", max_tokens=1024)
provider = PydanticAIProvider(config)

result = provider.run("Summarize this document in 3 bullet points.")
print(result.output)
print(f"Tokens used: {result.usage.total_tokens}")
```

## Features

- **Tool calling** — Translates functualize `ToolDef` instances into PydanticAI's native `Tool` format via `ToolScopeTranslator`, enabling LLM-driven function invocation
- **Structured output** — Pass a Pydantic model as `response_model` to get typed, validated responses directly from the LLM
- **Streaming** — Iterate over response tokens as they arrive using `PydanticAIProvider.stream()`
- **Multi-turn agent loops** — `PydanticAI.run_agent_loop()` executes iterative tool-calling workflows with configurable iteration limits
- **Conversation history** — `PydanticAI.run_with_history()` continues conversations from prior message history
- **Auto-registration** — Plugin hooks into `APP_READY` to resolve `AIConfig`, create the provider, and register both `AI` and `PydanticAI` types with DI
- **Budget tracking** — Integrates with functualize's state system for token usage and cost tracking across calls

## API Reference

Public classes exported by this plugin:

- `PydanticAIPlugin` — Entry-point plugin class that registers the provider with functualize's DI system at boot. Implements the plugin callable protocol.
- `PydanticAIProvider` — `AIProvider` protocol implementation backed by PydanticAI and LiteLLM. Methods: `complete()`, `run()`, `stream()`, `extract()`.
- `PydanticAI` — Extended `AI` capability subclass with PydanticAI-specific methods: `run_agent_loop()` for multi-turn execution and `run_with_history()` for conversation continuation.
- `ToolScopeTranslator` — Converts a list of functualize `ToolDef` instances into PydanticAI `Tool` objects using `Tool.from_schema()`.

## Development

Run plugin tests:

```bash
uv run pytest plugins/functualize-ai-pydantic/tests/ -v
```

Lint and format:

```bash
uv run ruff check plugins/functualize-ai-pydantic/
uv run ruff format plugins/functualize-ai-pydantic/
```
