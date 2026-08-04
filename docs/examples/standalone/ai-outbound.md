# AI Outbound — Standalone Job

A job that actively calls an LLM using functualize's AI capability. Demonstrates outbound AI usage — the job is the caller, not the callee.

## Source

[`examples/standalone/showcase/jobs/ai_jobs.py`](https://github.com/raicing-ai/functualize/blob/master/examples/standalone/showcase/jobs/ai_jobs.py) (the `ai_write` job)

## Running

```bash
pip install "functualize[cli]" functualize-ai
cd examples/standalone/showcase
func ai-write --topic "Python async patterns" --style concise
func ai-write --topic "Error handling" --max-tokens 500
```

## Key Concepts

- **`AI.complete()`** — Call an LLM with optional structured output (`response_model`)
- **`AI.run()`** — Multi-turn AI execution with tool access
- **`ToolScope.functions()`** — Expose plain Python callables as AI tools
- **`AILimits`** — Budget and token limits (`max_tokens`, `max_tool_calls`, `timeout_seconds`)
- **`MockAI`** — Glob-pattern matching for deterministic test responses

## Testing Without API Keys

The example uses `MockAI` which matches prompts to responses using glob patterns:

```python
ai = MockAI(responses={
    "*concise*": GeneratedContent(title="Quick Guide", ...),
    "*detailed*": GeneratedContent(title="Deep Dive", ...),
    "*": GeneratedContent(title="Default", ...),
})
```

This makes tests fast, deterministic, and free of external dependencies.

## Related

- [AI Inbound Example](ai-inbound.md)
- [Custom Plugin Example](../plugins/custom-state-backend.md)
