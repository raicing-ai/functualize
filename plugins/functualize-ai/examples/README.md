# functualize-ai Examples

The AI domain SDK: provider-agnostic `AI` capability with structured output, `ToolScope`, `AILimits`, and the `MockAI` testing double.

| Directory | Demonstrates |
|-----------|--------------|
| [`summarize/`](summarize/) | A job calling `ai.complete()` with a Pydantic `response_model`, runnable without API keys via `MockAI` |

```bash
uv run pytest plugins/functualize-ai/examples/ -v
```

For a real LLM backend, see [`functualize-ai-pydantic/examples/`](../../functualize-ai-pydantic/examples/).
