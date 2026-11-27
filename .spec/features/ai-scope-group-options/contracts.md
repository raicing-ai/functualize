# AI scope group-option contracts

## Scope resolution

`ToolScope.to_tool_defs(job_registry, *, group_context=None) -> list[ToolDef]` accepts optional cached group declarations. Without context, it preserves the current descriptor-only job schema and existing function-tool behavior. With context, each job tool uses the core `job_input_schema` renderer with the group declaration map and its class names. No new required argument or missing-context error is introduced.

## AI capability construction and run

`AI.__init__(..., _job_registry=None, _group_context=None)` stores optional app data. `PydanticAI` forwards both values to the base class, which is their single owner. The plugin supplies both from its app at readiness.

`AI.run(prompt, *, tools=scope, job_registry=registry)` gives an explicitly supplied registry priority, including `[]`; otherwise it uses the stored app registry or `[]`. It passes the stored group context when resolving the scope. `PydanticAI._resolve_tool_defs(scope)` uses the same stored pair through the base resolution path. A directly constructed AI with neither field set retains the existing result.

## Published job schema

For a job with inherited `GroupOptions` declarations, the app-wired `ToolDef.parameters_schema` equals the `inputSchema` of `func builtin info schema` and MCP `tools/list` for that job. Inherited fields appear in `properties`, never in `required`; injected group-instance parameters are excluded, and a job's own field takes precedence on collision. The core renderer determines exact JSON Schema fragments.

## Compatibility and documentation

`ToolScope.to_tool_defs(registry)` and standalone `AI.run(..., job_registry=registry)` remain valid and descriptor-only when no group context exists. `to_tool_defs([])` has no job tools. App-injected `ai.run(prompt, tools=scope)` now offers matching jobs without a caller registry; this is recorded in `CHANGELOG.md` and the AI guide.
