# Examples

Working examples demonstrating functualize features in realistic scenarios. Each example is self-contained, reproducible, and (where automatable) includes tests proving it works.

The examples are organized into four categories matching different usage patterns. View the full source at [`examples/`](https://github.com/raicing-ai/functualize/tree/master/examples).

## Quickstart (The README, Runnable)

- [Quickstart Steps 1–8](quickstart.md) — every step of the README Quick Start as runnable code: script → config → invoke → inline TUI → AI → MCP → workflows → scaffold.

## Standalone (Feature Reference)

Run jobs with the `func` CLI, no project structure needed.

- [Hello World](standalone/hello-world.md) — Single-file jobs (Mode A). One file, multiple functions, one command.
- [Inline Dependencies](standalone/inline-dependencies.md) — Jobs using Domain SDK packages (state, tasks) directly in a single file.
- [AI Inbound](standalone/ai-inbound.md) — A job driven by an external AI agent via the AI_INBOUND gate strategy.
- [AI Outbound](standalone/ai-outbound.md) — A job that calls an LLM using the AI capability for content generation.

Also in the repo (source-only): [`showcase/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/showcase) (the all-in-one project: CLI modes, inline TUI scenarios, surfaces, config inspector, AI jobs), [`discovery_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/discovery_lab) (all six discovery filters + global dirs from one jobs tree), [`config_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/config_lab) (the config precedence chain), [`secrets_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/secrets_lab) (declaring a credential with `Secret[str]`, and what every surface renders for it), [`group_options_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/group_options_lab) (flags that belong to a group rather than a job, typed mid-path), and [`deploy_tool/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/deploy_tool) (an app that is not `func`: its own command name, config table and env prefix).

## Project (Full Applications)

- [`weather_app/`](https://github.com/raicing-ai/functualize/tree/master/examples/project/weather_app) — the flagship: the Quick Start jobs as a scaffolded project with an entry point and layered config.
- [`monorepo_children/`](https://github.com/raicing-ai/functualize/tree/master/examples/project/monorepo_children) — one parent app mounting child projects as namespaced job groups.

Delivery-adapter projects live with their plugins:

- [HTTP Service](project/http-service.md) — Expose jobs as an HTTP API using the `functualize-http` adapter.
- [Lambda Handler](project/lambda-handler.md) — Deploy jobs to AWS Lambda with fat and thin Lambda patterns.

## Plugins (Extending Functualize)

Create your own plugins and adapters for the ecosystem.

- [Custom State Backend](plugins/custom-state-backend.md) — Implement the `StateBackend` protocol with TTL support.
- [Custom Adapter](plugins/custom-adapter.md) — Implement the `AdapterPlugin` protocol for webhook delivery.
- [File-Based Plugin](plugins/file-based-plugin.md) — Zero packaging: a single `.py` file in `.functualize/plugins/`.

Every first-party plugin also ships usage examples in its own folder: [`plugins/<name>/examples/`](https://github.com/raicing-ai/functualize/tree/master/plugins).

## Dev Container

All examples can be run in isolation using the provided [Dev Container](https://github.com/raicing-ai/functualize/tree/master/examples/.devcontainer) configuration. Open in VS Code with Dev Containers or GitHub Codespaces for a zero-setup experience.

```bash
# Or run locally from the repo root
uv sync --all-packages
uv run pytest examples/ -v
```
