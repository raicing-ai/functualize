# Contributing to Functualize

Thanks for your interest in contributing! This document explains how to get started.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/raicing-ai/functualize.git
cd functualize

# Install mise (manages python + uv from mise.toml)
# See https://mise.jdx.dev/getting-started.html
mise install

# Install dependencies (creates .venv, installs all workspace packages)
uv sync

# Install pre-commit hooks (BOTH types — the second validates commit messages,
# and `pre-commit install` alone silently skips it)
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

## Project Structure

```
functualize/
├── src/functualize/          ← Core library
│   ├── app/                  ← Public: FunctualizeApp, config, presets
│   ├── job/                  ← Public: RunContext, capabilities, decorators
│   ├── plugin/               ← Public: EventBus, protocols, metadata
│   ├── types/                ← Public: JobResult, JobDescriptor, enums
│   ├── workflow/             ← Public: @workflow, Step, Edge, END
│   ├── testing/              ← Public: test doubles for job unit testing
│   ├── _app/                 ← Internal: boot orchestration, state
│   ├── _cli/                 ← Internal: CLI adapter, scaffold
│   ├── _config/              ← Internal: resolution chain, providers
│   ├── _discovery/           ← Internal: job provider pipeline, cache
│   ├── _engine/              ← Internal: execution engine, middleware
│   ├── _events/              ← Internal: event bus, hooks, tracing
│   ├── _gate/                ← Internal: gate resolution algorithm
│   ├── _plugins/             ← Internal: plugin loader, domain registry
│   ├── _primitives/          ← Internal: DI, lazy, locator, resilient
│   └── _types/               ← Internal: shared type vocabulary
├── plugins/                  ← Workspace plugins (uv workspace members)
│   ├── functualize-state/
│   ├── functualize-state-sqlite/
│   ├── functualize-http/
│   ├── functualize-lambda/
│   ├── functualize-inline/
│   ├── functualize-flow-viz/
│   ├── functualize-fullscreen-tui/   ← source only, no pyproject.toml: not a workspace member
│   ├── functualize-ai/
│   ├── functualize-ai-pydantic/
│   ├── functualize-tasks/
│   ├── functualize-tasks-local/
│   └── functualize-mcp/
├── tests/                    ← Test suite
├── examples/                 ← Working examples (quickstart, standalone, project, plugins)
├── docs/                     ← MkDocs documentation source
└── scripts/                  ← Maintenance scripts
```

### Architecture rules

The codebase enforces strict import boundaries via [import-linter](https://github.com/seddonym/import-linter):

- **Public packages** (`app`, `job`, `plugin`, `types`, `workflow`, `testing`) are the user-facing API
- **Internal packages** (prefixed with `_`) never import from public packages
- **`_types`** imports nothing internal (leaf layer)
- **`_primitives`** imports only from `_types` (foundational utilities)
- **Peer internal layers** (`_discovery`, `_config`, `_engine`, `_plugins`) are independent of each other
- **`_cli`** uses only the public API (dogfoods the library)

Run `uv run lint-imports` to verify these constraints.

## Running Tests

The test suite is split into **fast** (unit) and **slow** (property-based / Hypothesis) tiers. By default, only fast tests run.

```bash
# Fast tests only (default, skips property-based tests)
uv run pytest

# Include property-based tests (full suite)
uv run pytest --run-slow

# Run with coverage and parallelism (mirrors CI)
uv run pytest --run-slow --cov=functualize -n auto

# Quick smoke-check of property tests with fewer examples
HYPOTHESIS_PROFILE=dev uv run pytest --run-slow
```

Run a specific test file:

```bash
uv run pytest tests/core/test_state.py
```

Run tests matching a pattern:

```bash
uv run pytest -k "test_discovery"
```

### Test tiers explained

| Command | What runs | When to use |
|---------|-----------|-------------|
| `uv run pytest` | Unit tests only | After every change |
| `uv run pytest --run-slow` | All tests including property-based | Before pushing |
| `HYPOTHESIS_PROFILE=dev uv run pytest --run-slow` | All tests, hypothesis uses 10 examples | Quick full check |
| `uv run pytest --run-slow --cov=functualize -n auto` | Full CI equivalent (parallel + coverage) | Replicate CI locally |

Property-based tests (files named `*_properties.py`, `*_props.py`, `*_property.py`) are auto-detected and skipped unless `--run-slow` is passed. You can also mark individual tests with `@pytest.mark.slow`.

## Testing Functualize in Other Projects

When developing functualize, you'll often want to test your local changes against a real project that depends on it.

### Option 1: `tool.uv.sources` path dependency (recommended)

In your other project's `pyproject.toml`:

```toml
[project]
dependencies = [
    "functualize>=0.1.0",
]

[tool.uv.sources]
functualize = { path = "/path/to/functualize", editable = true }
```

Then run `uv sync`. Changes to functualize source are reflected immediately.

> **Important:** `tool.uv.sources` must be in `pyproject.toml` — uv does not support `[sources]` in `uv.toml`. Do not mix `pip install -e` with `uv sync`.

### Option 2: Build and install the wheel

```bash
# In the functualize repo
uv build

# In your other project
uv pip install /path/to/functualize/dist/functualize-0.1.0-py3-none-any.whl
```

### Option 3: Scaffold a test project

```bash
uv run func scaffold init /tmp/my-test-app
cd /tmp/my-test-app
# Edit pyproject.toml to add tool.uv.sources pointing to your functualize checkout
uv sync
my-test-app --help
```

## Performance Testing (Non-Editable Install)

Editable installs (`uv sync`) add overhead from import hooks and `.pth` file resolution. To measure true production boot performance, test with a wheel-based install:

```bash
# run from the repository root
uv build && \
rm -rf /tmp/func-test && \
uv venv /tmp/func-test && \
uv pip install --no-cache --reinstall \
  "dist/functualize-0.1.0-py3-none-any.whl[cli]" --python /tmp/func-test/bin/python && \
uv pip install \
  plugins/functualize-ai \
  plugins/functualize-state \
  plugins/functualize-tasks \
  plugins/functualize-mcp \
  plugins/functualize-http \
  plugins/functualize-lambda \
  plugins/functualize-flow-viz \
  --python /tmp/func-test/bin/python && \
cd examples/quickstart/step1_basic && \
time /tmp/func-test/bin/func --perf-report text forecast
```

**Why this order matters:**
1. The core wheel with `[cli]` extras first — installs click, rich, textual, etc.
2. Remaining plugins second — they depend on `functualize` (already satisfied)

`--no-cache --reinstall` is not optional. The version stays `0.1.0` across rebuilds,
so uv will otherwise serve a stale cached wheel and you will measure the previous
build without noticing.

**What to compare:**
- `time` output = total wall clock (Python startup + uv overhead + framework)
- `--perf-report` Total = framework-tracked time (excludes interpreter startup)
- The gap between them is Python/OS overhead (~100-400ms depending on system)

### Using the perf report

```bash
# Text format (human-readable, sorted by duration)
func --perf-report text <job>

# JSON format (machine-parseable, includes raw timestamps)
func --perf-report json <job>

# Filter to specific phase prefix
func --perf-report text --perf-filter boot.plugins <job>
```

## Code Quality

```bash
# Lint
uv run ruff check src/ tests/

# Auto-fix lint issues
uv run ruff check --fix src/ tests/

# Format
uv run ruff format src/ tests/

# Check formatting without changing files
uv run ruff format --check src/ tests/

# Type check
uv run mypy src/

# Architecture enforcement
uv run lint-imports

# All pre-commit hooks
uv run pre-commit run --all-files
```

## CI Workflows

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| CI | Push to `master`, PRs | Ruff lint, ruff format, mypy, pytest, lint-imports |
| Security | Push to `master`, PRs, weekly cron | Gitleaks secret scan |
| Release | Tag push `v*` | Build → publish to PyPI → create GitHub Release |
| PR Title | PRs (opened, edited) | Lint the PR title as a conventional commit |
| Docs | Push to `master` | Build docs (strict) → deploy to GitHub Pages |

## Branching Strategy

Trunk-based development with release tags:

- `master` is the single source of truth — the repo default branch, and what
  every workflow triggers on
- Short-lived branches for PRs, named `<type>/<kebab-slug>` where `<type>` is
  one of the commit types below: `feat/group-options-panels`,
  `fix/warm-cache-display-discovery`, `docs/plugin-authoring`
- `sdd/<slug>` is also reserved, for spec-driven-development working branches
- Release tags (`v0.1.0`, `v0.2.0`) trigger PyPI publishing
- No `develop` or `release/*` branches

The slug describes the change, not the ticket — `fix/warm-cache-display-discovery`
tells you what broke, `fix/issue-42` makes you go look it up. Reference the issue
in the commit footer instead.

## Making Changes

1. Fork the repo and create a branch from `master`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. Make your changes. Write tests for new functionality.

3. Ensure all checks pass:
   ```bash
   uv run ruff check src/ tests/
   uv run ruff format --check src/ tests/
   uv run mypy src/
   uv run lint-imports
   uv run pytest
   ```

   These are the gates CI enforces. `uv run pytest --run-slow` additionally runs
   the property-based tier, which is **currently red** — see follow-up #7 in
   `.spec/STATUS.md`. Run it if you are touching the engine, but do not treat a
   pre-existing failure there as yours.

4. Commit with a clear message (see [Commit Message Convention](#commit-message-convention)):
   ```bash
   git commit -m "feat: add support for X"
   ```

5. Push and open a Pull Request against `master`.

## Release Process

```bash
# 1. Bump version in TWO places:
#    - pyproject.toml: version = "X.Y.Z"
#    - src/functualize/__init__.py: __version__ = "X.Y.Z"

# 2. Update CHANGELOG.md
#    - Move items from [Unreleased] to new [X.Y.Z] section
#    - Add date: ## [X.Y.Z] - YYYY-MM-DD
#    - Update comparison links at bottom

# 3. Commit and tag
git add -A
git commit -m "chore(release): vX.Y.Z"
git tag vX.Y.Z

# 4. Push (tag triggers release workflow → PyPI publish)
git push origin master
git push origin vX.Y.Z
```

The release workflow builds and publishes the core package **and every workspace
plugin** (`uv build --all-packages`). One-time setup: each PyPI project
(`functualize` plus all `functualize-*` plugins) must have a
[trusted publisher](https://docs.pypi.org/trusted-publishers/) configured for
`release.yml` in this repository, and the repo needs a `pypi` GitHub environment.
When bumping plugin versions, update each plugin's `pyproject.toml` as well.

## Commit Message Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>)!: <subject>

<body — why, not what>

<footer — Fixes #N, BREAKING CHANGE:, Co-Authored-By:>
```

| Type | Use for |
|------|---------|
| `feat` | New user-visible capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `perf` | Performance work with no behavior change |
| `ci` | Workflows, CI config, release automation |
| `build` | Build backend, packaging, dependency pins |
| `chore` | Maintenance that fits nothing above (incl. version bumps) |
| `revert` | Reverting a previous commit |

Rules:

- **Subject**: imperative mood, lowercase, no trailing period, ≤72 characters.
  "add group options panel", not "Added group options panel."
- **Scope** is optional and is a *single* token — `fix(engine):`, not
  `fix(cli,scaffold):`. If a change genuinely spans scopes, omit the scope; that
  is usually a sign it should be two commits.
- **`!`** before the colon marks a breaking change, and the footer must carry a
  `BREAKING CHANGE:` paragraph explaining the migration.
- **Body** explains *why* the change is right, and what a reader would otherwise
  have to re-derive. The diff already says what changed.

There is no `release:` type. A version bump is `chore(release): v0.2.0`.

### How this is enforced

| Gate | Checks | Where |
|------|--------|-------|
| `conventional-pre-commit` | Commit subject type and shape, at commit time | `.pre-commit-config.yaml` (needs `pre-commit install --hook-type commit-msg`) |
| PR Title workflow | PR title type, single-token scope, lowercase subject, no trailing period | `.github/workflows/pr-title.yml` |
| `master` ruleset | Changes arrive by PR; squash is the only merge method; `lint`, `lint-imports`, `typecheck`, `test-fast`, `gitleaks` and `lint-title` must pass; no force-push; no branch deletion | GitHub repository ruleset named `master` |

The first two overlap deliberately. The hook cannot see a PR title, and the PR
title is what becomes the commit on `master` — so the title is the one that must
be right. The local hook only catches mistakes earlier. Multi-token scopes pass
the hook and fail the workflow, because restricting scope shape locally would
mean enumerating every allowed scope.

The ruleset requires **zero approving reviews**. Its job is to guarantee that
every change reaches `master` through a PR with green CI, not to simulate a
review process that a single maintainer cannot perform on their own work.

`test-full` is deliberately *not* required. It is red for reasons unrelated to
any individual change (see `.spec/STATUS.md`), and a permanently-failing
required check trains people to merge past a red tick. Add it to the ruleset in
the same PR that turns it green.

Repository and organization admins can bypass the ruleset, so the release commit
described below can still be pushed straight to `master`. That bypass is a
convenience, not a licence: use a PR unless you are cutting a release.

### The changelog is written by hand

`CHANGELOG.md` is **not** generated from commit messages, and should not be.
Its entries explain consequences ("a job module's import-time side effects run
at first invocation rather than at boot") — the kind of thing a generator cannot
produce from a subject line. Conventional Commits are used here for navigation
and for grouping release notes, not as changelog source. Do not add a changelog
generator without an ADR.

## Pull Request Guidelines

**The PR title is the commit message.** This repo squash-merges, and the squash
commit takes the PR title verbatim — so the title must itself be a valid
conventional commit (`feat(tui): render group flags mid-path`). The PR body
becomes the commit body.

- Keep PRs focused on a single change
- Include tests for new functionality
- Update documentation if behavior changes
- Ensure CI passes before requesting review
- Reference issues in the body (`Fixes #123`), not in the title

Merge policy — squash only. Merge commits and rebase merges are disabled, and
branches are deleted on merge. One PR becomes exactly one commit on `master`,
which keeps history linear and makes `git log --oneline` a readable record of
what shipped.

## Key Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Package metadata, deps, tool config (ruff, mypy, pytest, import-linter) |
| `mise.toml` | Pins Python + uv versions |
| `uv.lock` | Locked dependency versions |
| `.pre-commit-config.yaml` | Local hooks: ruff, gitleaks, standard checks |
| `CHANGELOG.md` | Keep a Changelog format |
| `LICENSE` | MIT |

## Documentation

```bash
# Install docs dependencies
uv sync --group docs

# Live preview with hot reload (http://127.0.0.1:8000)
uv run mkdocs serve

# Build and validate (strict mode catches broken links)
uv run mkdocs build --strict
```

Automatic deployment: every push to `master` triggers `.github/workflows/docs.yml` which deploys to GitHub Pages.

## Reporting Issues

Use [GitHub Issues](https://github.com/raicing-ai/functualize/issues) with the provided templates for bug reports and feature requests.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

# Testing Guide

This document describes how to test functualize plugins with direct pytest
for fast local iteration.

## Quick Reference

```bash
# Test a specific plugin directly
pytest plugins/functualize-lambda/tests/ -v

# Test a plugin + its root tests
pytest plugins/functualize-mcp/tests/ tests/plugins/test_mcp_*.py -v

# Run all plugin tests
pytest tests/plugins/ -v

# Run everything (skipping slow property tests)
pytest tests/ -v

# E2E CLI integration tests
invoke --search-root tests/e2e test-cli

# Lint
ruff check .

# Typecheck
mypy src/functualize
```

## Architecture

```
plugins/functualize-{name}/
├── src/...                 # Plugin source
├── tests/
│   ├── __init__.py
│   ├── conftest.py         # Fixtures (fake app, helpers)
│   └── test_plugin.py     # Unit tests
├── README.md
└── pyproject.toml          # Has [project.optional-dependencies] dev = [...]
```

## Plugin Test Conventions

### Test Structure

Each plugin's `tests/` folder follows this pattern:

- `conftest.py` — Fake app objects and shared fixtures
- `test_plugin.py` — Core unit tests
- `test_integration.py` — (optional) Integration tests requiring services

### Writing Tests

Plugins should be testable without the full functualize runtime. Use fake
objects that satisfy the minimal interface:

```python
# conftest.py
class FakeApp:
    def get_jobs(self): ...
    def get_job(self, name): ...
    def execute(self, job_name, **kwargs): ...

@pytest.fixture
def fake_app():
    return FakeApp(descriptors=[...])
```

Then test the plugin's logic directly:

```python
# test_plugin.py
from functualize_http import HttpServerCore

class TestJobExecution:
    def test_execute_job(self, fake_app):
        core = HttpServerCore(fake_app)
        status, body = asyncio.run(
            core.handle_request("POST", "/jobs/greet/execute", b'{}')
        )
        assert status == 200
```

### Markers

- Tests in `*_properties.py` files are property-based (hypothesis) and
  skipped by default. Run with `--run-slow`.
- Use `@pytest.mark.integration` for tests needing external services.

## Known Quirks

### Running multiple plugin tests together locally

If you run `pytest plugins/*/tests/` in a single invocation, pytest may
complain about conftest path collisions (`ImportPathMismatchError`) because
multiple plugins have identically-named `tests/conftest.py`.

**Workarounds:**
- Run one plugin at a time: `pytest plugins/functualize-mcp/tests/ -v`
- Use a loop: `for p in plugins/*/tests; do pytest "$p" -v; done`

This is by design — each plugin is independently testable, not meant to be
collected as a single flat namespace.

## Adding Tests to a New Plugin

1. Create `plugins/functualize-{name}/tests/`:
   ```
   tests/__init__.py
   tests/conftest.py
   tests/test_plugin.py
   ```

2. Add dev dependencies to the plugin's `pyproject.toml`:
   ```toml
   [project.optional-dependencies]
   dev = ["pytest>=7.4.0", "pytest-cov>=4.1.0"]
   ```
