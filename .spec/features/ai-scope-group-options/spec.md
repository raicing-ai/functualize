# AI tool scope publishes inherited group options

## Authority and problem

The approved shape is [Shape Intent, SD/30343171 v5](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/30343171) (`Authority: Approved`). A job may accept options declared by a `GroupOptions` class on its group path, but an AI tool definition currently omits them. An app-injected `AI.run(prompt, tools=scope)` also has no registry unless the caller passes one, so it offers no job tools on that documented call path.

The model must see the same job inputs that `func builtin info schema` and MCP publish. The core job schema renderer owns classification, injection-point exclusion, inherited option merging, collision precedence, and requiredness.

## User stories

- As a job author, I can declare inherited group options and have the app-injected AI capability offer them to the model with the same input schema as info and MCP.
- As a caller of the app-injected AI capability, I can pass a tool scope without repeating the app's job registry.
- As a standalone library caller, I can continue constructing an AI capability or resolving a scope without app context and receive the existing descriptor-only schema.

## Behavior

1. At app readiness, the injected AI capability captures this app's job registry and group declarations from the app-fingerprinted discovery cache used by the CLI and MCP.
2. Both inherited `AI.run` and the Pydantic capability's tool resolver publish job tools using that captured registry and group context. A caller-supplied registry takes precedence, including an explicitly empty registry.
3. A job tool's schema equals the corresponding info and MCP input schemas. Inherited group options are present and optional. The injection parameter is absent, and the job's own field wins a name collision. Nested groups contribute inherited options.
4. A scope or directly constructed AI without group context retains its current descriptor-only result. An empty registry resolves no job tools. Plain Python functions in a scope remain available as before.
5. The documented app-injected `ai.run(prompt, tools=scope)` call now offers the scope's jobs. The changelog states this visible behavior change.

## Acceptance criteria

- A real app fixture with a `GroupOptions` list field and a job accepting that group instance produces an AI job tool with the list field in `properties`, absent from `required`, and absent as an injection parameter. Its full schema equals info and MCP for the same job.
- The existing group-options surface parity harness gains an AI cell alongside its real MCP cell, covering inherited options on a nested path and a job-field collision.
- On the app-injected capability, a provider recorder observes the job tool from `AI.run(prompt, tools=scope)` without `job_registry=`; the Pydantic resolver observes the same schema.
- On the base commit, the same recorder observes no job tool from that call. The before and after outputs are recorded with the implementation result.
- Focused compatibility tests show contextless scope resolution and directly constructed AI retain descriptor-only schemas, and an explicit empty registry yields no job tool.
- Relevant focused tests and repository quality gates pass; the production call path is demonstrated by a failing test when the new handoff is deliberately removed after a commit, then restored.

## Boundary

`workflow_view.tool_summaries` remains a separate caller-facing projection and is outside this repair. The issue's parity claim is for AI `ToolDef.parameters_schema`, info schema, and MCP input schema.
