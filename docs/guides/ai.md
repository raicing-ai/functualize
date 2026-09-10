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

```toml
[ai]
provider = "pydantic"
model = "gpt-4o"
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
@app.hooks.on_event("ai.call.completed")
def log_usage(event):
    print(f"Tokens used: {event.payload['token_usage'].total_tokens}")
```

---

## Gate Strategies

The AI SDK registers one gate **strategy** and two gate **presets**. They are
different things, they are reached through different APIs, and mixing them up
is a `ValueError` at import time — so the distinction comes first.

### Strategies vs. presets

A **strategy** is one way to resolve a gate. A **preset** is a named fallback
ladder over several strategies.

| Name | Kind | Registered by |
|---|---|---|
| `resolve` | strategy | core, at boot |
| `prompt` | strategy | core, at boot |
| `ai_inbound` | strategy | `functualize-ai` |
| `ai_outbound` | strategy | `functualize-mcp` |
| `"ai_inbound"` | preset → `ai_inbound` → `prompt` → `resolve` | `functualize-ai` |
| `"ai"` | preset → `ai_outbound` → `ai_inbound` → `prompt` → `resolve` | `functualize-ai` |

Note that `"ai_inbound"` names **both** a strategy and a preset. Which one you
get depends on where you write it, and that is the trap the next section is
about.

### `Gate(strategy=...)` accepts only the four bare strategy names

```python
Gate(name="triage", awaits=Approval, strategy="ai_inbound")   # ok
Gate(name="triage", awaits=Approval, strategy="ai")           # ValueError
```

```
ValueError: Gate strategy must be one of
['ai_inbound', 'ai_outbound', 'prompt', 'resolve'], got 'ai'
```

`Gate` validates in `__post_init__`, against a fixed set — not against the
registry. That is deliberate: a `Gate` is part of a declaration that is read at
import time, long before any plugin has registered anything, so it cannot know
which presets exist. The cost is that presets are unreachable from a `Gate`.

A gate that names `ai_inbound` still gets the *ladder*, because the walker
expands it: `Gate(strategy="ai_inbound")` is walked as
`["ai_inbound", "prompt", "resolve"]`. So the common case needs no preset.

### Presets resolve through two APIs, neither of them `Gate`

```python
# From inside a job, via the Invoke capability
result = rc.invoke(review, awaits_input=Approval, force_gate=True, gate_strategy="ai")

# Directly on the app
approval = app.gates.resolve_gate(Approval, gate_strategy="ai", gate_name="triage")
```

Both accept a strategy name, a preset name, or an explicit list of strategy
names.

!!! warning "The `ai` preset needs **both** plugins, and fails hard without them"

    `functualize-ai` registers the `"ai"` preset, but that preset's first rung
    is `ai_outbound` — which `functualize-mcp` registers. A preset referencing
    an unregistered strategy raises rather than falling through:

    ```
    ValueError: Unregistered gate strategy 'ai_outbound' referenced in
    preset 'ai'. Register the strategy before using the preset.
    ```

    So with only `functualize-ai` installed, `gate_strategy="ai"` is an error,
    not a degraded ladder. Use `gate_strategy="ai_inbound"` — its preset
    references nothing `functualize-ai` does not itself register.

    This is the one place a missing plugin is *not* a graceful block, and it is
    intentional: a preset is a registry entry, so a dangling reference in one
    is a wiring mistake in the application rather than a capability that
    happens to be absent at this gate.

### What happens when the plugin is not installed

`ai_inbound` resolves to nothing until `functualize-ai` is installed, and
`ai_outbound` until `functualize-mcp` is. The walk **blocks** rather than
raising, and says which package it wanted:

```python
result = app.execute("review")

result.status                      # RunStatus.BLOCKED
result.metadata["blocked_on"]      # 'triage'
result.metadata["blocked_reason"]
# "unregistered gate strategy 'ai_inbound' (install functualize-ai to register
#  it); Cannot resolve model Approval from config chain: unresolved fields:
#  ['approved']"
```

The reason has two halves, `;`-separated: the unregistered strategies come
first because they are the actionable part, followed by the last rung's own
error. Here `resolve` was the last rung, and it failed for the ordinary reason
a gate exists — nothing had supplied `approved` yet.

`blocked_reason` appears only when there is something to say. A gate waiting
for a human by design carries `blocked_on` and no reason at all.

Two cases still raise instead of blocking, and both are deliberate:

- **A single explicitly-named strategy** — `gate_strategy="ai_inbund"` has no
  ladder to fall down, so a typo stays loud rather than becoming a silent
  block.
- **A preset referencing an unregistered strategy** — a preset is a registry
  entry, so a dangling reference in one is a wiring mistake in the
  application, not a missing capability at this gate.

### A note on *inbound* and *outbound*

This page uses the two words on **two different axes**, and any prose touching
both has to say which it means.

- **The scenario**, used everywhere else in this guide: *outbound* is a job
  calling an LLM; *inbound* is an external agent driving a job.
- **The gate strategy**, used in the table above: the direction the *answer*
  travels. `ai_inbound` is implemented by calling an LLM — which is the
  *outbound* scenario — because the resolved value comes back **in** to the
  gate.

Both namings are internally coherent. They collide only where the two axes
meet, which is exactly here.

---

## Related

- [AI Outbound Example](../examples/standalone/ai-outbound.md)
- [AI Inbound Example](../examples/standalone/ai-inbound.md)
- [ToolScope Builder](domain-sdks.md)
- [Workflows Guide](workflows.md)
- [Composing Capabilities](composition.md) — the combination matrix for using AI alongside `Fingerprint`, `Deps` and the guard pipeline
