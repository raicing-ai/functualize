# functualize-ai

> **Status: Published** — Independently installable from PyPI.

AI Domain SDK for functualize — provider-agnostic LLM interaction capabilities.

Provides the `AI` capability class with structured output, tool calling, streaming,
and extraction methods backed by a pluggable `AIProvider` protocol. Includes
deny-by-default tool visibility via `ToolScope`, cumulative budget enforcement,
lifecycle event emission, and a deterministic `MockAI` testing double for unit
testing without network calls or API keys.

## Installation

```bash
pip install functualize-ai
```

## Quick Start

```python
from functualize_ai import AI, ToolScope, AILimits
from functualize_ai.testing import MockAI

# Use MockAI for deterministic testing (no API key needed)
ai = MockAI(responses={"*summarize*": "A brief summary of the document."})

# Simple text completion
result = ai.complete("Please summarize this text")
print(result)  # "A brief summary of the document."

# Run with tool scope and budget limits
scope = ToolScope.only(["search", "calculate"])
limits = AILimits(budget_usd=1.00, max_tool_calls=5)
ai_result = ai.run("Find the answer", tools=scope, limits=limits)
print(ai_result.output)
```

## Features

- **Provider-agnostic AI class** with `complete()`, `run()`, `stream()`, and `extract()` methods for text, structured output, tool calling, and streaming
- **ToolScope builder** implementing deny-by-default tool visibility — restrict tools by name, tag, group, or plain callables with composable `+` operator
- **Budget enforcement** tracking cumulative USD spend across calls with automatic `BudgetExceeded` errors when limits are reached
- **Structured output validation** with automatic retry (up to 3 attempts) against Pydantic models or dataclasses
- **MockAI testing double** using glob-pattern matching for deterministic, network-free testing with full call recording
- **Lifecycle event emission** (`AI_CALL_STARTED`, `AI_CALL_COMPLETED`, `AI_CALL_FAILED`, `AI_BUDGET_EXCEEDED`, `AI_TOOL_CALLED`) for observability and audit logging
- **AIProvider protocol** enabling custom backend implementations (PydanticAI, LiteLLM, or any LLM SDK)

## API Reference

Public classes and functions exported by this plugin:

### Capability

- `AI` — Provider-agnostic LLM interaction class with `complete()`, `run()`, `stream()`, `extract()` methods

### Protocol

- `AIProvider` — Runtime-checkable protocol that AI backend implementations must satisfy

### Tool Scope

- `ToolScope` — Deny-by-default tool visibility builder with `only()`, `tagged()`, `group()`, `functions()` factory methods

### Types

- `AIResult` — Result of an AI run containing `output`, `tool_calls`, `usage`, and `duration_ms`
- `TokenUsage` — Token usage statistics (`prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`)
- `ToolDef` — Provider-agnostic tool definition with name, description, and parameters schema
- `AILimits` — Budget and constraint caps (`max_tool_calls`, `max_tokens`, `budget_usd`, `timeout_seconds`)
- `ToolCallRecord` — Record of a single tool call with name, args, result, and duration

### Configuration

- `AIConfig` — Pydantic model for AI domain configuration (provider, model, max_tokens, budget_usd, timeout_seconds)

### Errors

- `AINotAvailable` — Raised when no AI provider is configured
- `BudgetExceeded` — Raised when cumulative spend reaches the budget limit
- `ToolNotPermitted` — Raised when a tool call is not permitted by the current ToolScope

### Events

- `AI_CALL_STARTED` — Emitted when an AI call begins
- `AI_CALL_COMPLETED` — Emitted when an AI call completes successfully
- `AI_CALL_FAILED` — Emitted when an AI call fails
- `AI_BUDGET_EXCEEDED` — Emitted when budget is exceeded
- `AI_TOOL_CALLED` — Emitted when a tool is called during a run

### Testing

- `MockAI` — Pattern-matching AI mock for deterministic testing
- `MockAICall` — Record of a single MockAI call (prompt, response_model, response)

### Provider Discovery

- `discover_ai_providers()` — Discover available AI provider entry points
- `select_ai_provider()` — Select a provider by name from discovered providers
- `resolve_ai_provider()` — Resolve and instantiate the configured AI provider

### State Fallback

- `EphemeralStateBackend` — In-memory state backend for when no persistent state is available
- `StrictStateBackendWrapper` — Wrapper enforcing strict key access on a state backend
- `resolve_ai_state_backend()` — Resolve the AI state backend from context

## Development

Run plugin tests:

```bash
uv run pytest plugins/functualize-ai/tests/ -v
```
