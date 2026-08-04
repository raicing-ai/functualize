# AI Inbound — Standalone Job

A job designed to be driven by an external AI agent. The AI_INBOUND gate strategy allows an LLM to resolve job configuration automatically.

## Source

[`examples/standalone/showcase/jobs/ai_jobs.py`](https://github.com/raicing-ai/functualize/blob/master/examples/standalone/showcase/jobs/ai_jobs.py) (the `ai_review` job)

## Running

```bash
# Manual execution with explicit config
cd examples/standalone/showcase
func ai-review --repo my-org/my-repo --focus security

# Expose as MCP tool for AI agents
func mcp serve
```

## Key Concepts

- **AI_INBOUND gate** — An LLM resolves unset config fields from conversation context
- **`visibility="external"`** — Marks the job for MCP exposure to AI agents
- **`MockAI`** — Deterministic AI testing double (no API keys needed)
- **`ToolScope.only()`** — Restrict which tools the AI can use during execution
- **Structured output** — `response_model=ReviewResult` returns typed Pydantic objects

## How AI_INBOUND Works

When this job is exposed via MCP and an external AI agent calls it:

1. Agent calls `run_job("ai_review")` without providing all config fields
2. The gate system detects unresolved fields (e.g., `repo` is missing)
3. AI_INBOUND strategy asks the LLM to resolve them from conversation context
4. If AI can't resolve, falls back to PROMPT (or config chain defaults)
5. Job executes with the fully resolved config

## Related

- [AI Outbound Example](ai-outbound.md)
- [MCP Delivery Adapter](../../guides/plugins.md)
