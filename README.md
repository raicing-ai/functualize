<p align="center">
  <img
    src="https://raw.githubusercontent.com/raicing-ai/functualize/master/docs/assets/brand/functualize-banner.png"
    alt="Functualize — From functions to action."
    width="100%"
  />
</p>

<p align="center">
  <strong>From functions to action.</strong>
</p>

<p align="center">
  Python operations and verifiable workflows for humans, automation, and AI agents.
</p>

<p align="center">
  <a href="https://raicing-ai.github.io/functualize/">Docs</a>
  ·
  <a href="#quick-start">Quick Start</a>
  ·
  <a href="#agents-and-workflows">Agents</a>
  ·
  <a href="#installation">Install</a>
</p>

[![CI](https://github.com/raicing-ai/functualize/actions/workflows/ci.yml/badge.svg)](https://github.com/raicing-ai/functualize/actions/workflows/ci.yml)
[![Docs](https://github.com/raicing-ai/functualize/actions/workflows/docs.yml/badge.svg)](https://github.com/raicing-ai/functualize/actions/workflows/docs.yml)
[![Python Versions](https://img.shields.io/pypi/pyversions/functualize)](https://pypi.org/project/functualize/)
[![PyPI version](https://badge.fury.io/py/functualize.svg)](https://pypi.org/project/functualize/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

## What is Functualize?

**Functualize turns ordinary Python functions into discoverable, configurable,
composable operations and verifiable workflows.**

Use the same underlying jobs from the TUI, CLI, Python, MCP, HTTP, Lambda,
CI, an AI agent, or another workflow.

```text
function → job → workflow → evaluation → outcome
```

The CLI is only one surface. The underlying operation stays the same.

## Quick Start

Drop a function into your workspace:

```python
# deploy.py
from functualize.job import RunContext


def deploy(environment: str = "staging", rc: RunContext | None = None) -> None:
    if rc:
        rc.log(f"Deploying to {environment}...")
```

From that directory:

```bash
func
```

`func` discovers the workspace and opens the interactive TUI, where you can
find jobs, inspect/configure parameters, see where values come from, and run them.

Or invoke directly:

```bash
func deploy --environment production
```

No command-registration boilerplate is required.

## Why Functualize?

A useful function is easy to write. Making it operational usually adds:

- discovery and invocation
- typed configuration
- secret and credential provisioning
- local and remote config / secret sources
- dependency injection
- structured logging and execution context
- state and resumability
- workflows and conditional execution
- human or AI gates
- verification and completion criteria
- multiple delivery surfaces

Functualize provides that layer while keeping domain logic as ordinary Python.

## Workspace-native operations

Functualize can attach an operational layer to an existing repository without
taking over its application structure.

```text
workspace/
├── src/
├── docs/
├── AGENTS.md
└── .functualize/
    ├── jobs/
    ├── lib/
    └── plugins/
```

This works whether the repository itself is Python, Go, Rust, Terraform,
research code, or a mixed agent workspace.

Functualize can combine workspace-local jobs with user-global jobs under
`~/.config/functualize/jobs/`, following the XDG configuration convention.
Additional job directories can also be configured explicitly.

### Built for the agent workspace

An emerging pattern in agent systems is to treat the **workspace itself as a
first-class interface**: files hold context and artifacts, directories provide
structure, and agents use the filesystem and shell to understand and act on
their environment.

You can see this direction in [ICMP / Model Workspace Protocol](https://arxiv.org/abs/2603.16021),
[OpenClaw](https://docs.openclaw.ai/agent-workspace),
[Hermes Agent](https://github.com/NousResearch/hermes-agent), and
[Vercel's filesystem-first agent work](https://vercel.com/blog/how-to-build-agents-with-filesystems-and-bash).

Functualize makes the executable side of that pattern straightforward: keep
context and artifacts in the workspace, put reusable operations under
`.functualize/`, and let humans or agents discover and invoke them from the same
place.

**The workspace provides context. Functualize gives it executable, composable
operations.**

## Agents and workflows

Functualize complements agents rather than replacing them.

> **Keep your agent. Give it reliable workflows.**

The agent supplies reasoning. Functualize supplies the procedure, state,
gates, allowed transitions, deterministic checks, and completion criteria.

```text
Agent / harness
      │
      ▼
Functualize workflow
      │
      ├── deterministic step
      ├── agent step
      ├── verification gate
      ├── correction
      └── evaluator
      │
      ▼
verified outcome
```

### Drive a workflow over CLI

Start the workflow like any other job:

```bash
func release
```

If it blocks on a gate in non-interactive mode, Functualize persists the scope.
Inspect, answer, and resume the same workflow:

```bash
func builtin workflow list
func builtin workflow show <workflow-id>
func builtin workflow answer <workflow-id> <gate> --input '{"approved": true}'
func builtin workflow resume <workflow-id>
```

Or answer and advance in one command:

```bash
func builtin workflow resume <workflow-id> --input '{"approved": true}'
```

Completed steps are not re-run; recorded branches and gate inputs remain stable
when the workflow resumes.

### Or drive the same workflow over MCP

Expose the workspace:

```bash
func mcp serve
```

An agent can discover and start a workflow through the normal MCP job tools:

```text
discover_jobs()
get_job_schema("release")
run_job("release")
```

If it blocks:

```text
list_workflows()
get_workflow_state("<workflow-id>")
```

The agent can inspect the pending gate, use tools offered by that gate, provide
input, and advance the same workflow:

```text
call_gate_tool("<workflow-id>", "inspect_artifact", {...})
answer_gate({...}, workflow_id="<workflow-id>", gate="review")
resume_workflow("<workflow-id>")
```

Or provide the gate input directly while resuming:

```text
resume_workflow(
    "<workflow-id>",
    input={"approved": true, "reason": "checks passed"}
)
```

The distinction is simple:

```text
answer_gate(...)      records gate input
resume_workflow(...)  advances the workflow
```

This gives agents a stable loop:

```text
discover → start → inspect → act → resume → verify → complete
```

without requiring a specific agent framework or model.

> **Bring your own agent. Bring your own model. Bring your own harness.
> Standardize the workflow.**

## What you get

- **Discovery** — CWD, `.functualize/`, explicit directories, and user-global jobs
- **Configuration** — typed config, layering, remote sources, secrets
- **Execution** — `RunContext`, DI, lifecycle, stable exit semantics
- **Workflows** — DAGs, gates, state, resume, `AgentStep`, evaluation
- **Agents** — MCP tools, AI gates, agent-backed steps, verifiable execution
- **Surfaces** — TUI, CLI, Python, MCP, HTTP, Lambda
- **Extensibility** — plugins, providers, adapters, domain SDKs

## Installation

### Standalone — no system Python required

```bash
curl -LsSf \
  https://raw.githubusercontent.com/raicing-ai/functualize/master/install.sh \
  | sh
```

Windows:

```powershell
irm https://raw.githubusercontent.com/raicing-ai/functualize/master/install.ps1 | iex
```

The standalone distribution includes its own Python runtime and first-party
Functualize components.

Then simply run:

```bash
func
```

### With Python

```bash
uv tool install "functualize[cli]"
```

or:

```bash
pipx install "functualize[cli]"
```

### As a library

```bash
uv add functualize
```

Use `FunctualizeApp` when you want to build your own named CLI/application on
top of the runtime, with explicit job sources, configuration, plugins, and
delivery adapters.

```python
from functualize.app import FunctualizeApp, JobSources, classic

app = FunctualizeApp(
    name="my-ops",
    job_sources=JobSources(directories=["my_ops.jobs"]),
    config_sources=classic(),
)


def run() -> None:
    app.run()
```

### Extend Functualize

Functualize supports packaged plugins through Python entry points, and a
workspace can keep project-local extensions under `.functualize/plugins/` so
shared behavior can live with the repository and augment operations contributed
by multiple job authors.

Plugins can add lifecycle hooks, CLI commands, dynamic jobs, providers,
adapters, and other integrations without changing Functualize core.

## Core concepts

| Concept | Meaning |
| --- | --- |
| **Function** | Ordinary Python domain logic |
| **Job** | A discoverable, configurable executable function |
| **Workflow** | Jobs and agent steps composed into a bounded procedure |
| **Evaluation** | Gates, checks, tests, and postconditions |
| **Operation** | Useful work that can be invoked and executed reliably |
| **Delivery surface** | TUI, CLI, Python, MCP, HTTP, Lambda, or another adapter |

## Documentation

- [Getting Started](https://raicing-ai.github.io/functualize/getting-started/)
- [Jobs and Discovery](https://raicing-ai.github.io/functualize/guides/jobs-discovery/)
- [Configuration](https://raicing-ai.github.io/functualize/guides/configuration/)
- [Workflows](https://raicing-ai.github.io/functualize/guides/workflows/)
- [MCP](https://raicing-ai.github.io/functualize/guides/mcp/)
- [Plugins](https://raicing-ai.github.io/functualize/guides/plugins/)
- [Architecture](https://raicing-ai.github.io/functualize/guides/architecture/)

## Project status

Functualize is currently **alpha** and actively evolving around workflows,
agent interoperability, evaluation, secrets/configuration, and adapters.

## Contributing

See [Contributing](docs/contributing.md).

## License

[Apache 2.0](LICENSE) © 2025-2026 Mohammad Hakim Adiprasetya
