# functualize-mcp Examples

The full MCP reference example: exposing jobs as MCP tools that AI agents (Claude, Cursor, Goose) can discover and call. For the minimal narrative version, see [`examples/quickstart/step6_mcp/`](../../../examples/quickstart/step6_mcp/).

| Directory | Demonstrates |
|-----------|--------------|
| [`weather_tools/`](weather_tools/) | Visibility control, rich `@job_metadata`, and the served tool surface |
| [`grouped_tools/`](grouped_tools/) | Grouped jobs (`JOB_GROUP`) served as dotted MCP tools, incl. typed args, internal visibility, and docstrings that resist source injection |

## Serving grouped jobs

A `JOB_GROUP` module exposes each external job under its full dotted name —
`probe.echo`, not `echo` — matching `func mcp schema` and `func mcp tools`.
Dotted names are legal MCP tool names; an agent calls the job by the same
name functualize uses everywhere else:

```bash
cd plugins/functualize-mcp/examples/grouped_tools
func mcp serve
```

The server performs no FastMCP update check and prints no banner on boot
(no network egress); set `FASTMCP_CHECK_FOR_UPDATES` /
`FASTMCP_SHOW_SERVER_BANNER` to opt back into FastMCP's defaults.

## Serving

```bash
cd plugins/functualize-mcp/examples/weather_tools
func mcp serve                 # stdio transport (default)
```

Wire into Claude Code:

```json
{
  "mcpServers": {
    "weather": {
      "command": "func",
      "args": ["mcp", "serve"],
      "cwd": "/path/to/weather_tools"
    }
  }
}
```

## The tool surface agents see

Beyond one tool per `visibility="external"` job, the server exposes framework tools:

| Tool | Purpose |
|------|---------|
| `discover_jobs` | List external jobs with descriptions and tags |
| `get_job_schema` | Full input schema (from the job's Pydantic config) |
| `run_job` / `run_job_async` | Execute synchronously or in the background |
| `get_execution_status` | Poll an async execution |
| `get_workflow_state` / `resume_workflow` | Drive gated workflows across turns |

Inspect what would be served without starting the server:

```bash
func mcp tools
```

## Tests

```bash
uv run pytest plugins/functualize-mcp/examples/ -v
```
