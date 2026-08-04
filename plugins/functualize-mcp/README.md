# functualize-mcp

> **Status: Published** — Independently installable from PyPI.

MCP delivery adapter plugin for functualize — exposes jobs as MCP tools via FastMCP. External AI agents (Goose, Claude, Cursor) can discover and invoke functualize jobs through the standardized [Model Context Protocol](https://modelcontextprotocol.io/) interface without any manual wiring.

## Installation

```bash
pip install functualize-mcp
```

## Quick Start

```python
from functualize_mcp import JobToolTranslator, MCPToolDef, SchemaExporter

# Translate a job descriptor into an MCP tool definition
translator = JobToolTranslator()
tool_def = translator.translate(my_job_descriptor)
print(tool_def.name, tool_def.description)

# Export all job schemas as OpenAI function calling JSON
exporter = SchemaExporter(translator)
openai_json = exporter.export_openai(descriptors)
```

## Features

- Automatic job-to-tool translation with JSON Schema input generation from config models
- Dual transport support: stdio (default) and HTTP+SSE for networked agents
- Job visibility filtering via include/exclude tags and job name exclusion lists
- Multi-format schema export: JSON (MCP), Markdown, OpenAI function calling, TypeScript
- Multi-server management: start, list, and stop background HTTP servers
- Workflow inspection and advancement tools for paused workflow steps
- Async job execution with polling via `run_job_async` / `get_execution_status`
- AI outbound gate strategy for workflow checkpoint serialization

## API Reference

Public classes and functions exported by this plugin:

- `MCPAdapterPlugin` — Plugin entry point implementing the AdapterPlugin protocol; registers MCP tools at boot
- `MCPConfig` — Pydantic configuration model controlling transport, port, host, tag filters, and management features
- `MCPServer` — FastMCP wrapper that discovers jobs, registers tools, and serves via stdio or HTTP+SSE
- `JobToolTranslator` — Translates JobDescriptors into MCPToolDef instances using docstrings and config schemas
- `MCPToolDef` — Frozen dataclass representing an MCP tool (name, description, input_schema, annotations)
- `SchemaExporter` — Exports job schemas in JSON, Markdown, OpenAI, and TypeScript formats
- `MCPToolRegistry` — Registers core MCP tools (discover_jobs, get_job_schema, run_job, run_job_async, get_execution_status)
- `MCPHistoryToolRegistry` — Registers execution history inspection tools
- `MCPManagementToolRegistry` — Registers multi-server management meta-tools
- `MCPTaskToolRegistry` — Registers task-domain MCP tools
- `WorkflowToolProvider` — Registers workflow state inspection and resume tools
- `ServerManager` — Manages background MCP HTTP server processes (start, list, stop)
- `ServerInfo` — Dataclass describing a managed server (name, directory, port, pid, status)
- `AIOutboundGateResolver` — Gate strategy resolver for AI outbound workflow checkpoints
- `register_ai_outbound_gate_strategy()` — Registers the ai_outbound gate strategy and preset with an app

## Development

Run plugin tests:

```bash
uv run pytest plugins/functualize-mcp/tests/ -v
```
