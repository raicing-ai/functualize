# functualize-ai-pydantic Examples

The PydanticAI/LiteLLM-backed provider for the AI domain. These examples hit a **real LLM** — set an API key first:

```bash
export OPENAI_API_KEY=sk-...
# Or: export ANTHROPIC_API_KEY=sk-ant-...
```

| Directory | Demonstrates |
|-----------|--------------|
| [`travel_plan/`](travel_plan/) | The injected `AI` capability: `ai.complete()` with structured output against a real model |

There is deliberately no automated test here — network calls don't belong in the test suite. For key-free AI examples use [`functualize-ai/examples/`](../../functualize-ai/examples/) (MockAI).
