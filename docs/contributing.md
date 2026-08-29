# Contributing

Thanks for your interest in contributing to Functualize! This guide covers everything you need to get started with development.

## Required Toolchain

Before contributing, ensure you have the following tools installed:

| Tool | Minimum Version | Purpose | Installation |
|------|----------------|---------|--------------|
| Python | 3.11+ | Runtime and development | [python.org](https://www.python.org/downloads/) or via mise |
| uv | latest | Package and environment management | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| mise | latest | Tool version management | [mise.jdx.dev](https://mise.jdx.dev/getting-started.html) |
| pre-commit | 4.0+ | Git hook management | Installed via dev dependencies |

!!! tip "Using mise"
    mise manages Python and uv versions from the project's `mise.toml`. Running `mise install` after cloning ensures you have the correct tool versions.

## Development Setup

### 1. Clone the repository

```bash
git clone https://github.com/raicing-ai/functualize.git
cd functualize
```

### 2. Install tool versions with mise

```bash
mise install
```

This installs the correct Python and uv versions defined in `mise.toml`.

### 3. Install dependencies

```bash
uv sync --group dev
```

This creates a virtual environment (`.venv`) and installs all runtime and development dependencies, including all workspace plugin packages.

### 4. Install pre-commit hooks

```bash
uv run pre-commit install
```

!!! warning "Required step"
    You **must** install pre-commit hooks after cloning the repository. These hooks run automatically on every commit to enforce code quality standards before code reaches CI.

The pre-commit configuration (`.pre-commit-config.yaml`) includes the following hooks:

| Hook | Purpose |
|------|---------|
| `trailing-whitespace` | Removes trailing whitespace |
| `end-of-file-fixer` | Ensures files end with a newline |
| `check-yaml` | Validates YAML syntax |
| `check-toml` | Validates TOML syntax |
| `check-added-large-files` | Prevents files larger than 500KB |
| `check-merge-conflict` | Detects unresolved merge conflict markers |
| `detect-private-key` | Prevents committing private keys |
| `ruff` | Lints Python code (with auto-fix) |
| `ruff-format` | Formats Python code |
| `gitleaks` | Scans for secrets and credentials |

---

## Workspace Structure

The repository is a **uv workspace** with multiple packages:

```
functualize/                          ← Root workspace
├── src/functualize/                  ← Core framework
├── plugins/
│   ├── functualize-state/            ← Domain SDK: StateBackend, ExecutionStore
│   ├── functualize-ai/               ← Domain SDK: AI capability
│   ├── functualize-tasks/            ← Domain SDK: Tasks capability
│   ├── functualize-ai-pydantic/      ← Implementation: PydanticAI + LiteLLM
│   ├── functualize-state-sqlite/     ← Implementation: SQLite persistence
│   ├── functualize-tasks-local/      ← Implementation: StateBackend-backed tasks
│   ├── functualize-mcp/              ← Delivery: MCP adapter (FastMCP)
│   ├── functualize-http/             ← Delivery: HTTP adapter
│   ├── functualize-lambda/           ← Delivery: AWS Lambda adapter
│   ├── functualize-inline/           ← Interactivity: CLI inline prompts (PromptCollector)
│   └── functualize-flow-viz/         ← Visualization utility
├── examples/                         ← Working examples (quickstart, standalone, project, plugins)
├── tests/                            ← Core framework tests
└── docs/                             ← Documentation (MkDocs Material)
```

Each plugin in `plugins/` is a standalone Python package with its own `pyproject.toml`, registered as a workspace member. Install everything with:

```bash
uv sync --all-packages
```

---

## Internal Architecture

This section is for **framework contributors** — people working on functualize internals. It explains the layer dependency graph, enforcement rules, and how to safely modify the codebase.

### Package Layout Overview

The source tree at `src/functualize/` is split into **5 public directories** (stable API for users) and **9 internal directories** (underscore-prefixed, implementation details):

```
src/functualize/
├── app/              # Public: app construction, adapters, presets
├── job/              # Public: job author API (RunContext, capabilities)
├── plugin/           # Public: plugin author API (EventBus, protocols)
├── types/            # Public: shared types (JobDescriptor, enums)
├── testing/          # Public: test utilities (TestRunContext, mocks)
├── workflow/         # Public: @workflow decorator, Step, Edge, ConditionalEdge, END
├── _types/           # Internal: shared vocabulary (frozen dataclasses, enums, protocols)
├── _primitives/      # Internal: zero-dep foundation utilities
├── _events/          # Internal: cross-cutting event system
├── _discovery/       # Internal: job finding, caching, hierarchy
├── _config/          # Internal: config resolution chain, sources
├── _engine/          # Internal: execution lifecycle, capabilities
├── _plugins/         # Internal: plugin loading machinery
├── _gate/            # Internal: gate resolution system
├── _app/             # Internal: composition root (boot, wiring)
├── _cli/             # Internal: CLI delivery (uses PUBLIC API only)
├── __init__.py       # Re-exports: FunctualizeApp, RunContext, workflow types, gate types
└── __main__.py       # Entry point
```

### Layer Dependency Graph

The dependency rules flow strictly downward. Each layer may only import from layers above it in this diagram:

```
┌─────────────────────────────────────────────────────────────┐
│                      _types/                                  │
│   Frozen dataclasses, Enums, Protocols — zero logic          │
│   Imports: stdlib ONLY                                       │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                    _primitives/                               │
│   DIRegistry, ResourceLocator, MiddlewareChain, lazy_cached, │
│   resilient — zero third-party deps                          │
│   Imports: _types/, stdlib                                   │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     _events/                                  │
│   EventBus, HookRegistry, PropagationContext, PerfTimeline   │
│   Imports: _types/, _primitives/                             │
└───┬──────────────┬───────────────┬──────────────┬───────────┘
    │              │               │              │
┌───▼────┐   ┌────▼─────┐   ┌────▼────┐   ┌────▼─────┐
│_discovery│  │ _config/ │   │_engine/ │   │_plugins/ │  ← PEER LAYERS
│         │  │          │   │         │   │          │    (independent)
└───┬─────┘  └────┬─────┘   └────┬────┘   └────┬─────┘
    │              │              │              │
    │   Each imports ONLY from: _types/, _primitives/, _events/
    │   Each NEVER imports from another peer layer
    │              │              │              │
┌───▼──────────────▼──────────────▼──────────────▼────────────┐
│                       _app/                                   │
│   Composition root — sole cross-layer wiring point           │
│   Imports: ALL internal layers (except _cli/)                │
└──────────────────────────────┬──────────────────────────────┘
                               │
                   (public API boundary)
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                       _cli/                                   │
│   CLI delivery — uses PUBLIC API ONLY                        │
│   Imports: app/, job/, plugin/, types/, testing/             │
│   NEVER imports from any _-prefixed package                  │
└─────────────────────────────────────────────────────────────┘
```

### What Each Internal Package Does

| Package | Responsibility | Key Contents |
|---------|---------------|--------------|
| `_types/` | Shared vocabulary — zero logic | Frozen `@dataclass` (JobDescriptor, FieldDescriptor, JobResult, CacheInfo), Enums (RunStatus, RunType, JobPhase), Protocols (JobProvider, AdapterPlugin, Surface, PromptCollector, etc.) |
| `_primitives/` | Foundation utilities with zero third-party deps | `di.py` (DIRegistry), `locator.py` (ResourceLocator), `middleware.py` (MiddlewareChain), `lazy.py` (lazy_cached descriptor), `resilient.py` (resilient generator wrapper), `modules.py` (iter_module_files) |
| `_events/` | Cross-cutting event system | `bus.py` (EventBus — trie-based topic router), `hooks.py` (HookRegistry), `tracing.py` (PropagationContext), `perf.py` (PerfTimeline) |
| `_discovery/` | Job finding + caching | `providers.py` (DirectoryScan, Cached, Static, EntryPoint), `transforms.py` (Namespace, GroupByModule), `cache.py` (persistence + sync), `hierarchy.py` (child projects), `pipeline.py` (ResolutionPipeline) |
| `_config/` | Configuration resolution | `chain.py` (ResolutionChain), `sources.py` (Cli/Env/File/Remote/Default), `job_config.py` (JobConfigView), `providers/` (`TomlFormatProvider` registered by default; `IniFormatProvider` in-tree, plugin-registered only — ADR-007) |
| `_engine/` | Execution lifecycle | `executor.py` (JobExecutionEngine), `middleware.py` (execution middleware), `context.py` (ExecutionContext), `capabilities/invoke.py` (Invoke), `capabilities/workflow.py` (WorkflowTracker) |
| `_plugins/` | Plugin loading machinery | `loader.py` (discovery + dependency sort + loading), `config.py` (PluginConfigRegistry) |
| `_app/` | Composition root — boot orchestration | `boot.py` (provider wiring, config chain, plugin loading), `impl.py` (FunctualizeApp internals), `state.py` (AppState) |
| `_cli/` | CLI delivery layer | `main.py` (entry point), `builtins.py` (cache/version commands), `scaffold/` (scaffold sub-command with Click + Jinja2) |

### Import-Linter Contracts

Layer dependencies are **enforced in CI** via [import-linter](https://import-linter.readthedocs.io/). Five contracts are configured in `pyproject.toml`:

| Contract | Type | What It Enforces |
|----------|------|-----------------|
| "Peer layers are independent" | `independence` | `_discovery`, `_config`, `_engine`, `_plugins` cannot import from each other |
| "Primitives import nothing internal" | `forbidden` | `_primitives` cannot import `_events`, `_discovery`, `_config`, `_engine`, `_plugins`, `_app`, `_cli` |
| "Types import nothing internal" | `forbidden` | `_types` cannot import any other `_`-prefixed package |
| "Internal never imports public" | `forbidden` | `_types` through `_app` cannot import `app/`, `job/`, `plugin/`, `types/`, `testing/` |
| "_cli uses public API only" | `forbidden` | `_cli` cannot import any `_`-prefixed internal package |

#### Running lint-imports Locally

```bash
uv run lint-imports
```

Run this before pushing any change that adds or modifies imports. A contract violation looks like:

```
functualize._discovery imports functualize._config
  (violates contract "Peer layers are independent")
```

If you see a violation, it means your import breaks the architecture. The fix is always one of:

1. Move the shared code to a lower layer (`_types/`, `_primitives/`, or `_events/`)
2. Define a Protocol in `_types/` and inject the implementation via `_app/`
3. Use the EventBus for cross-layer communication

### The Composition Root Pattern

`_app/` is the **only** internal package allowed to import from all peer layers. This is where dependency injection wiring happens:

- `_app/boot.py` — constructs providers from `_discovery`, builds the resolution chain from `_config`, initializes the engine from `_engine`, loads plugins from `_plugins`
- `_app/impl.py` — heavy internal methods that the public `FunctualizeApp` facade delegates to
- `_app/state.py` — application state container

**Why this matters:** If two peer layers need to communicate (e.g., `_engine` needs a discovered job list from `_discovery`), they don't import each other. Instead, `_app/boot.py` passes the data between them during construction.

This means:
- Peer layers are independently testable (no hidden coupling)
- Refactoring one peer layer doesn't cascade to others
- The wiring logic is consolidated in one auditable location

### `_types/` Rules

The `_types/` package is special — it's the **shared vocabulary** that every layer can depend on. Strict rules apply:

1. **No logic.** Function/method bodies may only contain `...`, `pass`, or `return self.<field>` (trivial property accessors)
2. **No internal imports.** `_types/` cannot import from any other `_`-prefixed package
3. **Only data + protocols.** Allowed contents:
    - Frozen `@dataclass` definitions
    - `Enum` classes
    - `Protocol` definitions (abstract interfaces)

This prevents circular imports and ensures the shared vocabulary layer has zero coupling to implementations.

### CLI Dependency Isolation

The CLI layer is **click-native** — the framework no longer depends on Typer
(or Trogon) at all. Isolation is enforced by `tests/test_typer_isolation.py`
and has two rules:

1. **Public-API boundary.** Importing `functualize.app` or `functualize.job`
   must not pull `typer`, `click`, `rich`, or `textual` into `sys.modules`.
   Lambda, HTTP, and programmatic deployments stay free of CLI dependencies.

2. **Kernel packages.** The internal packages (`_types/`, `_primitives/`,
   `_events/`, `_discovery/`, `_config/`, `_engine/`, `_plugins/`, `_app/`)
   must have **zero runtime imports** of `textual`, `rich`, or `jinja2`
   (and `typer`, which no longer exists in the tree). `click` is the one
   exception: it is a lightweight argument-parsing library that a kernel
   module may use directly — `_config/cli_adapter.py` reads explicit values
   off a `click.Context`. It stays out of the public-API boundary above, so
   `import functualize.app` still never loads it.

Command trees are built from `JobDescriptor` metadata in the delivery layer —
`app/adapters/click_params.py` (schema → `click.Parameter`s), `cli.py`
(`CliAdapter` → `click.Group`), `lazy_command.py` (cached-metadata commands),
`_cli/main.py`, and `_cli/scaffold/cli.py`.

`TYPE_CHECKING`-guarded imports of these libraries (for type annotations only)
are permitted anywhere since they have no runtime effect.

### How to Add a New Internal Module

When you need a new internal module, follow this decision process:

1. **Determine which layer it belongs to** based on its dependencies:

    | If it needs... | It belongs in... |
    |----------------|-----------------|
    | Nothing (stdlib only) | `_types/` (if data/protocol) or `_primitives/` (if utility) |
    | Only `_types/` | `_primitives/` |
    | `_types/` + `_primitives/` | `_events/` (if event-related) |
    | `_types/` + `_primitives/` + `_events/` | One of the peer layers (`_discovery/`, `_config/`, `_engine/`, `_plugins/`) based on domain |
    | Multiple peer layers | `_app/` (composition root) |

2. **Create the module** in the appropriate package directory

3. **Verify the layer rules** by running:

    ```bash
    uv run lint-imports
    ```

4. **Never** create a module that needs to import from two peer layers — if you find yourself needing this, the abstraction belongs in a lower layer or should be wired through `_app/`

#### Example: Adding a caching utility

If you're adding a generic caching decorator with no domain-specific logic:
- It goes in `_primitives/` (zero third-party deps, used by multiple layers)
- It may import from `_types/` for type definitions
- It must not import from `_events/` or any peer layer

If you're adding a cache for discovered jobs specifically:
- It goes in `_discovery/` (domain-specific to job finding)
- It may import from `_types/`, `_primitives/`, `_events/`
- It must not import from `_config/`, `_engine/`, `_plugins/`, `_app/`, or `_cli/`

### How to Add a New Public API Symbol

Public API symbols are what users import. Adding one requires updates in multiple places:

1. **Implement the symbol** — typically a class, function, or type in the appropriate internal package

2. **Export from the correct public directory** — choose based on audience:

    | Audience | Public directory |
    |----------|-----------------|
    | App constructors | `app/` |
    | Job authors | `job/` |
    | Plugin authors | `plugin/` |
    | Shared types | `types/` |
    | Test utilities | `testing/` |

3. **Add to `__all__`** in that directory's `__init__.py`:

    ```python
    # e.g., in src/functualize/types/__init__.py
    __all__ = [
        "JobResult",
        "JobDescriptor",
        "FieldDescriptor",
        "RunStatus",
        "RunType",
        "JobPhase",
        "CacheInfo",
        "YourNewType",  # ← add here
    ]
    ```

4. **Verify `_cli/` can use it** — since `_cli/` operates exclusively through the public API, any symbol needed by the CLI must be exported publicly. If you're adding a symbol that the CLI will use, confirm it's reachable via a public import path.

5. **Run the checks:**

    ```bash
    uv run lint-imports       # Verify no contract violations
    uv run mypy src/          # Verify type correctness
    uv run pytest             # Verify nothing broke
    ```

!!! warning "The `_cli/` dogfooding rule"
    The `_cli/` package is not allowed to import from any `_`-prefixed internal package. If you find that `_cli/` needs functionality that isn't available through the public API, the correct solution is to **add it to the public API** — not to break the import rule. This ensures the public API is complete enough for any external consumer (GUI, HTTP runner, CI tool) to do everything the CLI does.

---

## Running Tests

The test suite is split into **fast** (unit) and **slow** (property-based / Hypothesis) tiers. By default, only fast tests run — giving you quick feedback during development.

### Fast tests (default)

```bash
uv run pytest
```

This skips all property-based tests (files named `*_properties.py`, `*_props.py`, `*_property.py`) and runs only unit/integration tests. Target: under 10 seconds.

### Full test suite

```bash
uv run pytest --run-slow
```

Includes property-based tests with the default Hypothesis profile (100 examples per test).

### CI-equivalent run

```bash
HYPOTHESIS_PROFILE=ci uv run pytest --run-slow --cov=functualize -n auto
```

Runs all tests in parallel across CPU cores with coverage measurement.

The `HYPOTHESIS_PROFILE=ci` prefix is what makes this equivalent to CI, not a refinement
of it. The `ci` profile draws 200 examples per property where the default draws 100, so
it reaches inputs a plain `--run-slow` never generates — a suite that passes locally
without it can still fail on CI.

### Quick smoke-check of property tests

```bash
HYPOTHESIS_PROFILE=dev uv run pytest --run-slow
```

Runs property tests with only 10 examples each — useful for a quick sanity check before pushing.

### Test tiers summary

| Command | What runs | When to use |
|---------|-----------|-------------|
| `uv run pytest` | Unit tests only | After every change |
| `uv run pytest --run-slow` | All tests including property-based | Before pushing |
| `HYPOTHESIS_PROFILE=dev uv run pytest --run-slow` | All tests, 10 hypothesis examples | Quick full check |
| `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow --cov=functualize -n auto` | Full CI equivalent | Replicate CI locally |

!!! tip "Hypothesis profiles"
    The project defines three Hypothesis profiles:

    - **dev** — 10 examples (quick smoke-check)
    - **default** — 100 examples (balanced)
    - **ci** — 200 examples (thorough, used in GitHub Actions)

    Set the profile via environment variable: `HYPOTHESIS_PROFILE=dev`

### Targeting specific tests

Run a specific test file:

```bash
uv run pytest tests/core/test_state.py
```

Run tests matching a name pattern:

```bash
uv run pytest -k "test_discovery"
```

Run tests with verbose output:

```bash
uv run pytest -v
```

## Code Quality

### Linting

Check for code issues with ruff:

```bash
uv run ruff check src/ tests/
```

Auto-fix linting issues:

```bash
uv run ruff check --fix src/ tests/
```

### Formatting

Check formatting without making changes:

```bash
uv run ruff format --check src/ tests/
```

Apply formatting:

```bash
uv run ruff format src/ tests/
```

### Type Checking

Run mypy for static type analysis:

```bash
uv run mypy src/
```

### Import Linting

Verify layer dependency contracts:

```bash
uv run lint-imports
```

!!! note "Run all checks before pushing"
    Ensure all checks pass before pushing your branch:

    ```bash
    uv run ruff check src/ tests/
    uv run ruff format --check src/ tests/
    uv run mypy src/
    uv run lint-imports
    HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto
    ```

## Commit Message Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/). Every commit message must use one of the allowed type prefixes:

| Type | Description |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation-only changes |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `chore` | Maintenance tasks (CI, dependencies, tooling) |

### Format

```
<type>: <short description>

[optional body]

[optional footer]
```

### Examples

```bash
git commit -m "feat: add support for custom config file patterns"
git commit -m "fix: resolve race condition in plugin loading"
git commit -m "docs: update configuration guide with new examples"
git commit -m "refactor: simplify job discovery module"
git commit -m "test: add property tests for config resolution"
git commit -m "chore: update ruff to v0.9.0"
```

## Pull Request Guidelines

### Branch Naming

Create a branch from `main` using the convention `<type>/<short-description>`:

```bash
git checkout -b feat/my-feature
git checkout -b fix/config-resolution-bug
git checkout -b docs/update-api-reference
```

### Before Submitting

1. Ensure all checks pass locally:

    ```bash
    uv run ruff check src/ tests/
    uv run ruff format --check src/ tests/
    uv run mypy src/
    uv run lint-imports
    uv run pytest
    ```

2. Write tests for any new functionality.

3. Update documentation if behavior changes.

### CI Requirements

All pull requests must pass the CI pipeline before merging. The pipeline runs:

- **Linting** — ruff check and format verification
- **Type checking** — mypy
- **Import linting** — lint-imports (layer dependency enforcement)
- **Fast tests** — unit tests only (immediate feedback)
- **Full tests** — property-based tests + coverage across Python 3.11, 3.12, 3.13 (parallel via pytest-xdist)

!!! failure "Blocked on CI failure"
    PRs with failing CI checks cannot be merged. Fix all issues before requesting review.

### Review Process

1. Open a pull request against `main`.
2. Keep PRs focused on a single change.
3. Provide a clear description of what changed and why.
4. Address reviewer feedback with additional commits (do not force-push during review).
5. Once approved and CI passes, the PR will be merged.

## Reporting Issues

Use [GitHub Issues](https://github.com/raicing-ai/functualize/issues) with the provided templates:

- **Bug reports** — describe the issue, steps to reproduce, and expected behavior
- **Feature requests** — describe the use case and proposed solution

## Contributing to Domain SDK Packages

Domain SDK packages live in `plugins/` and follow a consistent structure:

```
plugins/functualize-{domain}/
├── pyproject.toml                    # hatchling build, pydantic-only deps
├── src/functualize_{domain}/
│   ├── __init__.py                   # Re-exports all public API
│   ├── _types.py                     # Frozen dataclasses, shared types
│   ├── _protocols.py                 # @runtime_checkable Protocol definitions
│   ├── _errors.py                    # Domain-specific exceptions
│   ├── _events.py                    # Event name constants
│   ├── _metadata.py                  # DomainMetadata entry point
│   ├── _{capability}.py             # Capability class implementation
│   └── testing/                      # Testing doubles (MockX, FakeX)
│       └── __init__.py
└── tests/
```

### Rules for Domain SDKs

1. **No heavy dependencies** — Only `pydantic` (for type definitions)
2. **Export everything from root `__init__.py`** — Capability class, protocols, types, errors, events, testing doubles
3. **Register a DomainMetadata entry point** under `functualize.domains`
4. **Include testing doubles** usable without implementation plugins
5. **Raise a domain-specific error with install instructions** when no provider is registered

### Rules for Implementation Plugins

1. **Depend on the Domain SDK** — Not on functualize core internals
2. **Register via the domain's entry point group** — e.g., `functualize.state_providers`
3. **Implement the provider protocol** from the Domain SDK
4. **Register with DI** via `app.provide()` in the plugin boot class

---

## Contributing to Examples

Examples live in `examples/` and are organized by usage pattern:

- **`quickstart/`** — The README Quick Start, step by step (1–8)
- **`standalone/`** — Feature reference: discovery, config, AI, inline TUI
- **`project/`** — Full `FunctualizeApp` projects
- **`plugins/`** — Custom plugin implementations (packaged and file-based)

Examples of *using* a specific first-party plugin belong in that plugin's own folder: `plugins/<name>/examples/` (see the "Examples" section in `contributor/guides/plugin-development.md`).

### Example Requirements

1. **Include a test file** (`test_*.py`) proving the example works (interactive TUI scenarios document manual steps instead)
2. **Include a `README.md`** explaining the use case and how to run
3. **Keep dependencies minimal** — Use testing doubles (MockAI, InMemoryState) instead of real backends
4. **Keep tests green** — Run `uv run pytest examples/ -v` before submitting (requires `uv sync --all-packages`). CI runs this too, in the `examples` job, so a broken example fails the pull request.

### Running Example Tests

```bash
# Install workspace packages first (AI/plugin examples import them)
uv sync --all-packages

# All examples
uv run pytest examples/ -v

# Standalone only
uv run pytest examples/standalone/ -v

# Specific example
uv run pytest examples/standalone/showcase/ -v

# Per-plugin examples (run explicitly, like plugin tests)
uv run pytest plugins/functualize-mcp/examples/ -v
```

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
