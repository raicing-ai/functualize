# Guides

These guides provide in-depth documentation on Functualize's core systems and features. Each guide covers a specific topic with explanations, configuration details, and code examples to help you get the most out of the framework.

Whether you're configuring layered settings, building auto-discovered jobs, extending the framework with plugins, building AI-powered workflows, or creating custom Domain SDKs, you'll find detailed coverage here.

## Topics

- [Usage Modes](modes.md) — Single-file, directory, library, and adapter modes — when to use each, how to scaffold, and feature comparison
- [Architecture](architecture.md) — Boot sequence, three-layer job pipeline, config resolution, interactivity layer, and extension points overview
- [Configuration System](configuration.md) — Layered INI-based configuration with environment overlays, upward directory search, and per-job sections
- [Jobs and Auto-Discovery](jobs-discovery.md) — How jobs are discovered via `pkgutil`, registered as CLI commands, and grouped into sub-commands
- [JobConfig with Pydantic](job-config.md) — Declarative, typed job configuration with automatic CLI option generation and multi-source resolution
- [RunContext Lifecycle](run-context.md) — Lifecycle hooks for setup, teardown, and error handling with metadata tracking and workflow steps
- [Domain SDKs](domain-sdks.md) — Lightweight capability packages (AI, State, Tasks, Interactivity) with protocols, types, and testing doubles
- [AI Capability](ai.md) — LLM interaction (complete, run, stream, extract), ToolScope restrictions, budget enforcement, and MockAI testing
- [Workflows](workflows.md) — Declarative multi-step job graphs with `@workflow`, conditional branching, gates, and scope tracking
- [Shell Capability](shell.md) — Run external commands with lifecycle management, secret redaction, context managers, and FakeShell testing
- [Task Runner](task-runner.md) — `@job` decorator with dependencies, fingerprint caching, guard pipeline, parallel execution, and pipeline mode
- [MCP Adapter](mcp.md) — Expose jobs as MCP tools for external AI agents, schema export, multi-server management
- [Plugins](plugins.md) — Extending Functualize with entry-point-based plugins and the PluginMetadata protocol
- [Interactivity](interactivity.md) — the Surface and PromptCollector protocols, the TTY and Live job capabilities, rc.prompt(), and rc.emit()
- [TUI Integration](tui.md) — Interactive terminal interfaces: the inline SmartBar TUI (auto-generated from job metadata) and Textual full-screen applications
- [Hooks](hooks.md) — Cross-cutting lifecycle hook system with global and job-scoped registration, PRE_EXECUTE gating, and signature-adaptive dispatch
- [Hooks vs Plugins](hooks-vs-plugins.md) — When to use hooks vs plugins, and how to share reusable behavior with colleagues
- [Hierarchical Projects](../hierarchy.md) — Flat and hierarchical job composition with parent-child project relationships
- [Hierarchy Validation](hierarchy-validation.md) — Version compatibility checking and cycle detection for hierarchical project structures
