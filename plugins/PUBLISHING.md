# Plugin Publishing Tiers

This document defines the maturity classification system for functualize plugins, governing which plugins are ready for independent PyPI publication and what quality bar must be met before publishing.

## Maturity Tiers

### Tier 1 — Published (PyPI)

Independently installable from PyPI. Meets full quality bar for public distribution.

**Criteria checklist:**

- [ ] `py.typed` marker file exists at `src/<package_name>/py.typed` (0-byte, PEP 561)
- [ ] README.md ≥30 lines with all required sections (see [README Template](#readme-template-tier-1))
- [ ] ≥3 functional tests with real assertions covering >50% of public API surface
- [ ] All non-functualize dependencies at version ≥1.0 or well-established (≥10M PyPI downloads/year)
- [ ] `uv build --package <name>` exits with code 0 and produces a `.whl` file
- [ ] All declared entry points are importable and callable in an isolated environment
- [ ] PyPI classifiers present: Development Status, License, Python versions (3, 3.11, 3.12, 3.13), Typing :: Typed
- [ ] `examples/` folder with a README and at least one runnable scenario (see the "Examples" section in [`contributor/guides/plugin-development.md`](../contributor/guides/plugin-development.md))

### Tier 2 — Bundled (monorepo-only)

Feature-complete implementation available via workspace install. Not yet published to PyPI.

**Criteria checklist:**

- [ ] Feature-complete implementation for its core use case
- [ ] ≥1 test file with real assertions (not just import checks)
- [ ] README.md exists (can be minimal)

### Tier 3 — Experimental

Prototype or incomplete implementation. Explicitly unstable.

**Criteria checklist:**

- [ ] Implementation exists (may be incomplete)
- [ ] Package installs without error (`uv sync` resolves)

## Graduation Process

Graduation is self-service. A contributor opens a PR satisfying all criteria for the target tier.

### Graduating from Tier 3 → Tier 2

1. Complete the core feature implementation
2. Add at least one test file with real assertions
3. Ensure a README.md exists in the plugin root

**Verification:**

```bash
# Test file exists and passes
uv run pytest plugins/<name>/tests/ -v

# README exists
test -f plugins/<name>/README.md
```

### Graduating from Tier 2 → Tier 1

1. Add `py.typed` marker: create a 0-byte file at `plugins/<name>/src/<package_name>/py.typed`
2. Expand README to ≥30 lines with all required sections (see template below)
3. Write ≥3 functional tests covering >50% of public API
4. Add mandatory PyPI classifiers to `pyproject.toml`
5. Verify the package builds independently

**Verification:**

```bash
# py.typed exists
test -f plugins/<name>/src/<package_name>/py.typed

# README meets minimum length
wc -l plugins/<name>/README.md  # must be ≥30

# Tests pass with sufficient count
uv run pytest plugins/<name>/tests/ -v --co -q | tail -1  # must show ≥3 tests
uv run pytest plugins/<name>/tests/ -v  # must exit 0

# Classifiers present
grep "Development Status :: 3" plugins/<name>/pyproject.toml
grep "Typing :: Typed" plugins/<name>/pyproject.toml

# Build succeeds
uv build --package <name>  # must exit 0, produces .whl
```


## Dependency Topology

Plugins have inter-dependencies that dictate PyPI publishing order. Publish Level 0 first, then Level 1.

```
Level 0 — No plugin dependencies (publish first)
├── functualize-interactivity
├── functualize-state
├── functualize-http
├── functualize-lambda
├── functualize-flow-viz
├── functualize-ai
└── functualize-tasks

Level 1 — Depends on Level 0 plugins (publish second)
├── functualize-inline          → depends on: functualize-interactivity
├── functualize-fullscreen-tui  → depends on: functualize-interactivity
├── functualize-state-sqlite    → depends on: functualize-state
├── functualize-tasks-local     → depends on: functualize-tasks, functualize-state
├── functualize-ai-pydantic     → depends on: functualize-ai
└── functualize-mcp             → depends on: (none currently, but integrates with core)
```

**Publishing order:** All Level 0 plugins can be published in parallel. Level 1 plugins must wait until their Level 0 dependencies are available on PyPI.

## README Template (Tier 1)

All Tier 1 plugins must include a README.md with the following sections:

```markdown
# functualize-<name>

> **Status: Published** — Independently installable from PyPI.

<Description paragraph explaining what the plugin does and when to use it.>

## Installation

\```bash
pip install functualize-<name>
\```

## Quick Start

\```python
# Minimal usage example (5–15 lines)
\```

## Features

- Feature 1 description
- Feature 2 description
- Feature 3 description (minimum 3 items)

## API Reference

Public classes and functions exported by this plugin:

- `ClassName` — brief description
- `function_name()` — brief description

## Development

Run plugin tests:

\```bash
uv run pytest plugins/functualize-<name>/tests/ -v
\```
```

**Rules:**

- Minimum 30 lines total
- Each section must appear as a distinct markdown heading (## or ###)
- Code examples must use valid Python syntax (parseable by `ast.parse()`)
- The `pip install` package name must match `[project] name` in `pyproject.toml`
- Import statements in examples must reference symbols from the plugin's public API

## Current Classification

| Plugin | Tier | Level | Notes |
|--------|------|-------|-------|
| functualize-interactivity | 1 — Published | 0 | Prompt/input/output protocols |
| functualize-state | 1 — Published | 0 | State management capability |
| functualize-http | 1 — Published | 0 | HTTP adapter (FastAPI/Starlette) |
| functualize-lambda | 1 — Published | 0 | AWS Lambda adapter |
| functualize-flow-viz | 1 — Published | 0 | Workflow execution visualization |
| functualize-ai | 1 — Published | 0 | AI/LLM capability |
| functualize-tasks | 1 — Published | 0 | Task queue domain protocol |
| functualize-inline | 1 — Published | 1 | Inline interactivity (Textual) |
| functualize-fullscreen-tui | 1 — Published | 1 | Full-screen TUI (Textual) |
| functualize-state-sqlite | 1 — Published | 1 | SQLite state backend |
| functualize-tasks-local | 1 — Published | 1 | Local state-backed task queue |
| functualize-ai-pydantic | 1 — Published | 1 | PydanticAI provider bridge |
| functualize-mcp | 1 — Published | 1 | MCP (Model Context Protocol) integration |

## Plugin-to-Package Mapping

| Plugin Directory | PyPI Package Name | Python Import |
|-----------------|-------------------|---------------|
| functualize-interactivity | functualize-interactivity | `functualize_interactivity` |
| functualize-state | functualize-state | `functualize_state` |
| functualize-state-sqlite | functualize-state-sqlite | `functualize_state_sqlite` |
| functualize-http | functualize-http | `functualize_http` |
| functualize-lambda | functualize-lambda | `functualize_lambda` |
| functualize-inline | functualize-inline | `functualize_inline` |
| functualize-flow-viz | functualize-flow-viz | `functualize_flow_viz` |
| functualize-fullscreen-tui | functualize-fullscreen-tui | `functualize_fullscreen_tui` |
| functualize-ai | functualize-ai | `functualize_ai` |
| functualize-ai-pydantic | functualize-ai-pydantic | `functualize_ai_pydantic` |
| functualize-tasks | functualize-tasks | `functualize_tasks` |
| functualize-tasks-local | functualize-tasks-local | `functualize_tasks_local` |
| functualize-mcp | functualize-mcp | `functualize_mcp` |
