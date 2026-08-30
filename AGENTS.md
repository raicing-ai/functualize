# AGENTS.md

Project context for AI coding agents. This file contains architecture, commands, and constraints — NOT workflow instructions.

## Commands

```bash
# Install dependencies
uv sync

# Lint & format (always run first)
uv run ruff check --fix src/ tests/ plugins/
uv run ruff format src/ tests/ plugins/

# Type check
uv run mypy src/

# Architecture enforcement
uv run lint-imports

# Fast tests (unit only)
uv run pytest -x -q --no-header

# Full tests (including property-based / hypothesis) — ~10 min, `ci` profile is what CI runs
HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q --no-header

# Run a single test file
uv run pytest tests/engine/test_execution_engine.py

# Run tests matching a keyword
uv run pytest -k "test_workflow"

# Run the CLI
uv run func --help
uv run functualize --help
```

All checks must pass before any change is complete: `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, `pytest`.

### Command discipline

- Commands already run from the project root — never prefix with `cd <project-root> &&`. Only `cd` into subdirectories when needed (e.g. `cd plugins/functualize-inline && uv sync`).
- After a change, run the **smallest relevant test scope** (specific file > `-k` keyword > directory > full suite). Run the full suite only when shared infrastructure changed.
- Maximum 2 pytest invocations per verification: run targeted tests; if a failure appears, fix and re-run only the failing test. If still failing, stop and explain rather than cycling flag variations.
- **Always redirect command output to a temp file** when the output may be long (pytest, linters, type checkers). Never pipe through `tail`/`head`/`sed` — truncation forces a re-run to see the full output. Use `/tmp/functualize-<command>.log` and read from it. Example: `uv run pytest tests/engine/ > /tmp/functualize-test.log 2>&1`.

### Git discipline

- The default branch is **`master`**, not `main`. All workflows trigger on it.
- Never commit directly to `master` for feature work. Branch as
  `<type>/<kebab-slug>` (`feat/group-options-panels`), `<type>` being a commit
  type below. `sdd/<slug>` is reserved for spec-driven working branches.
- `master` carries a GitHub ruleset: changes arrive by PR, squash is the only
  merge method, and `lint`, `lint-imports`, `typecheck`, `test-fast`, `gitleaks`
  and `lint-title` must pass. Admins can bypass it — do not, except for the
  release commit.
- Commit subjects are [Conventional Commits](https://www.conventionalcommits.org/):
  `<type>(<scope>)!: <subject>` with types `feat fix docs refactor test perf ci
  build chore revert`. Imperative, lowercase, no trailing period, ≤72 chars.
  Scope is a **single** token — `fix(engine):`, never `fix(cli,scaffold):`.
- The commit **body says why**, and what a reader would otherwise re-derive. The
  diff already says what changed.
- PRs are squash-merged and the squash subject is taken verbatim from the **PR
  title**, so a PR title must itself be a valid conventional commit. Issue
  references go in the body (`Fixes #123`), never the title.
- `CHANGELOG.md` is **hand-written prose, never generated** from commit
  messages. Do not add a changelog generator without an ADR.

Full rules and rationale: `CONTRIBUTING.md` §§ Branching Strategy, Commit
Message Convention, Pull Request Guidelines.

### Mandatory reading by task

| When you are... | Read first |
|---|---|
| Modifying import rules, layers, or inter-module dependencies | `contributor/reference/layer-rules.md` + `contributor/architecture/dependency-graph.md`; run `uv run lint-imports` before committing |
| Creating a new `src/functualize/` module | `contributor/guides/adding-internal-module.md` (needs `__init__.py` with `__all__` guard; internal modules documented in the dependency graph) |
| Working in `src/functualize/_cli/tui/` | `contributor/guides/steering_textual_tui.md` + `contributor/guides/tui-panels.md`; proofs in `tests/tui_audit/` |
| Debugging or manually verifying live TUI/CLI behavior (seeing the rendered screen, driving the app, trying examples) | `.agents/skills/observe-tui/SKILL.md` (PTY screen probe via pyte + tmux session driving). Manual/agent verification only — never wire it into automated tests or CI |
| Running E2E TUI validation after a milestone or kernel change | `.agents/skills/verify-e2e/SKILL.md` (reads a plan/spec, does blast-radius analysis, discovers scenarios, runs observe-tui probes). Invoked via `[verify-e2e:TIER]` task annotations mid-execute or unconditionally during `agentic-verify`. |
| Developing plugins in `plugins/` | `contributor/guides/plugin-development.md` (plugins are tested via `pytest plugins/<name>/tests/`, not collected by root pytest) |
| Wiring a new component in, or closing any task that added one | `contributor/guides/wiring-discipline.md` — name *every* production path (cold **and** warm-cache) that reaches your code, and break each once to prove a test notices. Three capabilities shipped built, unit-tested and unreachable before this existed; a fourth worked cold and silently did nothing warm |
| Verifying a change by breaking it on purpose (sabotage) | `contributor/guides/wiring-discipline.md` §3 — **commit first**, then sabotage, then `git checkout --`. That restore reverts everything uncommitted in the file, and has silently discarded finished work. Sabotage also catches vacuous *tests*, which running them cannot |
| Asking whether X happens before Y in a job run — or adding a step to `_execute_lifecycle` | `contributor/reference/execution-lifecycle.md` — the twenty steps and the constraint that fixes each one's position. Ordering constraints used to live only as comments inside a 323-line method; four of them are load-bearing, and `tests/engine/test_lifecycle_order.py` fails if the sequence moves |
| Writing tests | `contributor/reference/testing-strategy.md` (domain-mirrored dirs + `tests/_support/` fixtures; no `tests/unit/` or `tests/properties/` dirs) |
| Proposing a new layer, public API surface, or dependency-rule change | ADR is mandatory: record the decision in `contributor/adr/` (template: `contributor/adr/000-template.md`) |
| Opening a PR, writing a release commit, or unsure how to name a branch | `CONTRIBUTING.md` §§ Branching Strategy / Commit Message Convention / Pull Request Guidelines — the summary in **Git discipline** above covers the common case; read these for breaking changes, the release commit, and why the changelog is hand-written |
| Cutting a release, or bumping the version | `contributor/guides/docs-example-parity.md` — run the executable docs/examples parity pass. The release audit's doc scan is *static*: it checks that paths, symbols and syntax exist. A behavioural claim like "this field is masked" passes it while being false, which is how a breaking change reached ~50 doc pages and 20 example projects unnoticed |
| Understanding overall architecture | `contributor/architecture/overview.md` + `contributor/architecture/codemaps/` (module catalog, measured fan-in, entry points, data flow) |
| About to add a setting, filter, cache, registry, or TUI panel — or to debug one that "resolves but does nothing" | `contributor/reference/pitfalls.md` — 18 defects that already shipped here, each with the shape of the trap named. Several passed review *and* a test; four were only visible on the warm-cache or lazy-boot path |

## Architecture

**Functualize** is a Python CLI framework. Consumer projects install it and get auto-discovered job commands, layered config, lifecycle hooks, DI-powered execution, and a TUI with minimal boilerplate.

### Package structure (audience-separated)

```
src/functualize/
├── app/        # Public: application construction (FunctualizeApp, config, presets, adapters)
├── job/        # Public: job authoring (RunContext, capabilities: Log, Invoke, Prompt, Perf, State)
├── plugin/     # Public: plugin authoring (EventBus, JobProvider, AdapterPlugin)
├── testing/    # Public: test utilities (TestRunContext, CapturingLog, MockInvoke)
├── types/      # Public: shared vocabulary (JobResult, JobDescriptor, enums)
├── workflow/   # Public: workflow composition and patterns
├── _app/       # Internal: composition root — wires all peer layers via DI
├── _cli/       # Internal: CLI delivery — uses ONLY public API (dogfooding)
├── _config/    # Internal: ResolutionChain, sources, JobConfigView
├── _discovery/ # Internal: job finding, caching, providers, transforms
├── _engine/    # Internal: JobExecutionEngine, capabilities (Invoke, WorkflowTracker)
├── _events/    # Internal: EventBus, HookRegistry, PropagationContext, PerfTimeline
├── _gate/      # Internal: Gate resolution for workflow steps that pause for input collection
├── _plugins/   # Internal: plugin loading, dependency sort, PluginConfigRegistry
├── _primitives/# Internal: foundation utilities (DIRegistry, ResourceLocator, MiddlewareChain)
└── _types/     # Internal: shared protocols and frozen dataclasses (zero logic)
```

- **Public folders** (6): stable API, `__all__`-guarded. Users import from these.
- **Internal folders** (10): underscore-prefixed, off-limits to users. Contributors work here.
- Layer rules enforced by `import-linter` in CI (see `pyproject.toml` contracts).

### Job grouping

Jobs are organized into command hierarchies via the `JOB_GROUP` module-level variable:

```python
# jobs/infra.py
JOB_GROUP = "infra"

def provision(log: Log): ...
def teardown(log: Log): ...
```

This registers `"infra.provision"` and `"infra.teardown"` as qualified names, exposed as `func infra provision` and `func infra teardown` on the CLI. Nested groups (`JOB_GROUP = "infra.aws"`) create multi-level hierarchies. Modules without `JOB_GROUP` register functions by bare name as before.

### Two entry points (aliased)

`func` / `functualize` — unified CLI (both are aliases for `_cli.main:main`). Routes to built-in commands (`scaffold`, `cache`, `version`), single-file mode, group sub-command mode, or CWD-discovery mode.

### Boot sequence (fixed order)

`_app/boot.py` orchestrates boot in this order:

1. **core_infra** — HookRegistry, EventBus, DIRegistry
2. **provider_registry** — built-in TOML and INI format providers
3. **observability** — EventBus subscriptions, PerfTimeline
4. **plugins** — entry-point and file-based plugin loading (topological sort)
5. **config_entry_points** — discovers format/remote providers via entry points
6. **config_resolution** — `ResourceLocator` + `ResolutionChain` built once
7. **job_registration** — scan configured directories, build JobDescriptors
8. **children** — mount child FunctualizeApp projects
9. **REGISTRY_FROZEN** → **APP_READY** events — DI registry sealed, no runtime mutations

### Execution

`_engine/` contains `JobExecutionEngine` — the **single path** for all job execution (CLI, `rc.invoke()`, `func`). Never add a parallel execution path.

### DI model

Jobs declare dependencies via type-annotated parameters (FastAPI/pytest-fixture pattern):

```python
def deploy(log: Log, invoke: Invoke, config: DeployConfig):
    log("Deploying...")
    invoke("migrate")
```

### Config system

Layered resolution: **Override → CLI → Env → Files → Defaults**. Built once at boot via `ResolutionChain` (`boot.py:781-797`) — zero per-invocation file I/O. There is no remote tier: nothing in the shipped package constructs a `RemoteSource`, `remote_first()` notwithstanding. `Override` is a value `config.set()` deposits during a run, and it outranks CLI.

Presets are factory functions: `classic()`, `twelve_factor()`, `env_only()`, `remote_first()`. Any `(**kwargs) -> ConfigSources` function is a valid preset.

### Plugin system

- Entry-point auto-discovery: `pip install functualize-inline` → active immediately
- Monorepo workspace: `plugins/` directory with independent pyproject.toml per plugin
- `AdapterPlugin` protocol for delivery surfaces (CLI, HTTP, Lambda, MCP)
- Capability plugins register via DIRegistry

### Event model (non-overlapping)

- **HookRegistry** — interceptors that *control* lifecycle (block, modify). Synchronous, ordered.
- **EventBus** — observers that *observe* without modifying. Fire-and-forget notification.
- These two must NOT overlap. No pub/sub in HookRegistry. No lifecycle control in EventBus.

## Key constraints

- **Pre-release**: no backward compatibility obligation. Breaking changes are free until v1.0.0.
- **No god objects**: RunContext ≤500 LOC facade, FunctualizeApp ≤300 LOC facade.
- **Kernel/delivery split**: FunctualizeApp is delivery-agnostic. No `textual`/`rich`/`jinja2` imports in kernel layers (Typer/Trogon are gone entirely; `click` is permitted in the kernel — e.g. `_config/cli_adapter.py` — but `import functualize.app`/`job` still loads no CLI dependency). Enforced by `tests/test_typer_isolation.py`.
- **CLI deps are optional**: `functualize[cli]` extras group. Bare install has no CLI.
- **Protocols only**: all extension points use `@runtime_checkable Protocol` — no ABC.
- **No circular imports** between subpackages.
- **Peer layers independent**: `_discovery`, `_config`, `_engine`, `_plugins` never import each other. `_app/` is the sole composition root.
- **`_cli/` dogfoods public API**: if `_cli/` can't do something via public API, add it to a public folder first.
- **No unreachable capabilities**: a capability a user can declare must have a test that declares it and observes the effect through the public entry point — not one that calls the component directly. A green suite does not prove anything is wired (`contributor/guides/wiring-discipline.md`).
- **Transitional changes are disclosed, not disguised**: an intentionally non-final state whose completion is a later step must be marked in code (`# TRANSITIONAL(<step>): …`) and described in the spec/tasks as *current behavior + planned end-state* — never as already-final. A task is `[x]` only when its own acceptance gate is green against the code as it stands; otherwise it is partial, and the remainder is carried forward explicitly. See `.spec/CONSTITUTION.md` → *Transitional Changes*.
- Mypy strict; `ignore_missing_imports` only for `textual.*`.
- **TUI work** (`_cli/tui/`): read `contributor/guides/steering_textual_tui.md` (Textual architecture/testing HARD rules + compliance audit) and `contributor/guides/tui-panels.md` before changing panels, key handling, workers, or overlays. Proofs live in `tests/tui_audit/` (`uv run pytest tests/tui_audit/ -v`).

## Workflow

This project uses spec-driven development. The contract is in
`.claude/rules/spec-workflow.md` — phases, what is enforced, the exemption, and
the version-control lifecycle. This section covers only what is specific to
running it.

- **Claude Code**: invoke via `--agent spec-driven-developer` or `/agentic-*` commands
- **Other agents**: see `.claude/agents/spec-driven-developer.md` for the full workflow reference

### Plan mode in VS Code

`.claude/settings.json` sets `permissions.defaultMode: "plan"`, but **the VS Code
extension ignores it** — conversations it starts do not read project settings for
the starting permission mode. If you drive this repo from VS Code, set

```
claudeCode.initialPermissionMode: "plan"
```

in your **VS Code user settings**. No file in this repository can set it for you.

This is a convenience only. The workflow enforcement does not depend on plan
mode, and plan mode is read-only, so the Specify and Plan phases cannot run
inside it.

### .spec/ directory

Committed reference: `ARCHITECTURE.md`, `CONSTITUTION.md`, `TESTING.md`,
`STATUS.md`, `exemptions.log`.

Committed **on the branch only**, cleared before merge: `features/<name>/` —
`spec.md`, `contracts.md`, `plan.md`, `schema.md`, `research.md`, `tasks.md`.
The required `spec-artifacts-cleared` CI check blocks merging while any remain.

Gitignored: `STATE.md` (per-session; if absent, treat as no work in flight),
`plans/`, `proposals/`, `scrutiny-reports/`, `archive/`.

## Plugin tests

Plugin-specific tests live in each plugin's own `tests/` directory (e.g. `plugins/functualize-inline/tests/`).
Run them directly with `pytest plugins/<name>/tests/`; they are not collected
by the root `pytest` invocation.
