# AI Capability

The AI domain SDK (`functualize-ai`) provides LLM interaction for jobs — structured output, tool calling, streaming, and budget enforcement. It works with any provider via the `AIProvider` protocol.

---

## Quick Start

```python
from functualize_ai import AI, ToolScope, AILimits
from functualize.job import RunContext

def summarize(ai: AI, rc: RunContext):
    summary = ai.complete("Summarize this document...", response_model=Summary)
    rc.log(f"Summary: {summary.title}")
```

The `AI` capability is injected via DI when an AI provider plugin is installed.

---

## Methods

### `ai.complete(prompt, response_model=None)`

Call the LLM and optionally parse structured output:

```python
# Raw text response
text = ai.complete("What is Python?")

# Structured output (validated against Pydantic model)
from pydantic import BaseModel

class Summary(BaseModel):
    title: str
    key_points: list[str]

result = ai.complete("Summarize...", response_model=Summary)
# result is a validated Summary instance
```

### `ai.run(prompt, tools=ToolScope)`

Multi-turn execution with tool access:

```python
scope = ToolScope.only(["search", "read-file"])
result = ai.run("Find and summarize the README", tools=scope)
# result is an AIResult with output, tool_calls, token_usage, duration
```

### `ai.stream(prompt)`

Streaming response as an iterator:

```python
for chunk in ai.stream("Write a long essay..."):
    print(chunk, end="")
```

### `ai.extract(text, model=T)`

Extract structured data from unstructured text:

```python
class Contact(BaseModel):
    name: str
    email: str

contact = ai.extract("Email john@example.com, he's John Smith", model=Contact)
```

---

## ToolScope

Restrict which tools the AI can access (deny-by-default):

```python
from functualize_ai import ToolScope

# By job name
scope = ToolScope.only(["read-file", "search-docs"])

# By tag
scope = ToolScope.tagged("safe", "read-only")

# By group
scope = ToolScope.group("utilities")

# Plain Python functions
def search(query: str) -> str:
    return f"Results for {query}"

scope = ToolScope.functions([search])

# Combine scopes
combined = scope_a + scope_b

# Add instructions and approval requirements
scope = scope.with_instructions("Only search public docs")
scope = scope.approval_required()
```

---

## Budget Enforcement

Control AI spending with `AILimits`:

```python
from functualize_ai import AILimits

limits = AILimits(
    budget_usd=1.00,       # Max cumulative spend per scope
    max_tool_calls=10,     # Stop after N tool calls
    timeout_seconds=60,    # Wall-clock timeout
    max_tokens=4096,       # Max response tokens
)

result = ai.run("Complex analysis...", tools=scope, limits=limits)
```

Budget is tracked per `WorkflowScope` via the `ai:budget_spent` state key.

---

## Configuration

Configure via the `[ai]` section in your config file:

```ini
[ai]
provider = pydantic
model = gpt-4o
max_tokens = 4096
budget_usd = 5.00
timeout_seconds = 120
```

Or via environment variables:

```bash
export FUNCTUALIZE_AI_PROVIDER=pydantic
export FUNCTUALIZE_AI_MODEL=gpt-4o
```

---

## Testing

Use `MockAI` for fast, deterministic tests without API keys:

```python
from functualize_ai.testing import MockAI

ai = MockAI(responses={
    "*summarize*": Summary(title="Test", key_points=["point1"]),
    "*": "Default response",
})

result = ai.complete("Please summarize...", response_model=Summary)
assert result.title == "Test"
assert ai.call_count == 1
assert "summarize" in ai.last_prompt
```

MockAI matches prompts using glob patterns against the `responses` dict.

---

## Events

The AI capability emits structured events:

| Event | Payload |
|-------|---------|
| `ai.call.started` | prompt_length, model, tools_count |
| `ai.call.completed` | TokenUsage, duration_ms, tool_calls_count |
| `ai.call.failed` | error message, duration_ms |
| `ai.budget.exceeded` | limit, actual_spend, job_name |
| `ai.tool.called` | tool_name, args, duration_ms, status |

Subscribe via the event bus:

```python
@app.on_event("ai.call.completed")
def log_usage(event):
    print(f"Tokens used: {event.payload['token_usage'].total_tokens}")
```

---

## Gate Strategies

The AI SDK registers gate strategies for workflow integration:

- **`ai_inbound`** — LLM resolves gate inputs from conversation context
- **Gate preset `"ai_inbound"`** — Tries: `ai_inbound` → `prompt` → `resolve`
- **Gate preset `"ai"`** — Tries: `ai_outbound` → `ai_inbound` → `prompt` → `resolve`

---

## Related

- [AI Outbound Example](../examples/standalone/ai-outbound.md)
- [AI Inbound Example](../examples/standalone/ai-inbound.md)
- [ToolScope Builder](domain-sdks.md)
- [Workflows Guide](workflows.md)
