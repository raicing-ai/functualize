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
- [ ] PyPI classifiers present: Development Status, Python versions (3, 3.11, 3.12, 3.13), Typing :: Typed
- [ ] SPDX `license = "MIT"` field present, and **no** `License ::` trove classifier — PEP 639 makes the two mutually exclusive and PyPI rejects any distribution carrying both. Note that `twine check --strict` does *not* catch this
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

# SPDX license field present, legacy classifier absent (PEP 639)
grep '^license = ' plugins/<name>/pyproject.toml
! grep "License ::" plugins/<name>/pyproject.toml

# Build succeeds
uv build --package <name>  # must exit 0, produces .whl
```


## Dependency Topology

Levels below count **plugin-to-plugin** dependencies only. A dependency on the
`functualize` core package does not create a level, since core is always published
in the same run.

```
Level 0 — No plugin dependencies
├── functualize-state           → pydantic          (no core dep)
├── functualize-tasks           → pydantic          (no core dep)
├── functualize-http            → core
├── functualize-lambda          → core
├── functualize-inline          → core, textual
├── functualize-flow-viz        → core, textual
└── functualize-mcp             → core, fastmcp

Level 1 — Depends on Level 0 plugins
├── functualize-ai              → functualize-state
├── functualize-state-sqlite    → functualize-state, core
└── functualize-tasks-local     → functualize-tasks, functualize-state

Level 2 — Depends on Level 1 plugins
└── functualize-ai-pydantic     → functualize-ai, pydantic-ai, litellm
```

**Publishing order in practice:** ordering is informational. `.github/workflows/release.yml`
builds every workspace package with `uv build --all-packages` and hands the whole
`dist/` to `pypa/gh-action-pypi-publish` in a single step, so all levels go up in one
action. The graph matters when publishing a package by hand, or when reasoning about
which installs break during a partial release.

**Version pinning:** cross-plugin dependencies are pinned `>=0.1.0,<1.0.0`, except
`functualize-ai`'s dependency on `functualize-state` and `functualize-ai-pydantic`'s
on `functualize-ai`, which are unpinned. So is every plugin named in the core
package's `[all]` extra. Unpinned names are also unclaimed names — see the note in
Current Classification.

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

**Nothing is on PyPI yet.** All 12 names — core plus the 11 plugins — are
unregistered as of the v0.1.0 release preparation. "Tier 1" below means *meets the
Tier 1 bar*, not *currently downloadable*.

| Plugin | Tier | Level | Notes |
|--------|------|-------|-------|
| functualize-state | 1 — Ready | 0 | State management capability |
| functualize-tasks | 1 — Ready | 0 | Task queue domain protocol |
| functualize-http | 1 — Ready | 0 | HTTP adapter (FastAPI/Starlette) |
| functualize-lambda | 1 — Ready | 0 | AWS Lambda adapter |
| functualize-inline | 1 — Ready | 0 | Inline interactivity (Textual) |
| functualize-flow-viz | 1 — Ready | 0 | Workflow execution visualization |
| functualize-mcp | 1 — Ready | 0 | MCP (Model Context Protocol) integration |
| functualize-ai | 1 — Ready | 1 | AI/LLM capability |
| functualize-state-sqlite | 1 — Ready | 1 | SQLite state backend |
| functualize-tasks-local | 1 — Ready | 1 | Local state-backed task queue |
| functualize-ai-pydantic | 1 — Ready | 2 | PydanticAI provider bridge |
| functualize-fullscreen-tui | 3 — Experimental | — | **Not a package.** No `pyproject.toml`, so it is not a uv workspace member and is never built or published. Source and tests only |

All eleven Tier 1 entries were verified against the Tier 1 checklist: each has a
`py.typed` marker, a README of 43–114 lines, and an `examples/` directory.

**Publish all 12 together, including the ones nobody imports directly.** Two things
break otherwise. The core package's `[all]` extra names all 11 plugins, so
`pip install functualize[all]` fails against any name that is missing. And an
unregistered name referenced by an unpinned dependency is a name someone else can
claim and have resolved into your users' environments. Publishing claims them.

`functualize-interactivity` appeared in earlier revisions of this document. No such
package has ever existed in this repository.

## Plugin-to-Package Mapping

These are the eleven distributions built by `uv build --all-packages`, alongside the
`functualize` core package.

| Plugin Directory | PyPI Package Name | Python Import |
|-----------------|-------------------|---------------|
| functualize-state | functualize-state | `functualize_state` |
| functualize-state-sqlite | functualize-state-sqlite | `functualize_state_sqlite` |
| functualize-http | functualize-http | `functualize_http` |
| functualize-lambda | functualize-lambda | `functualize_lambda` |
| functualize-inline | functualize-inline | `functualize_inline` |
| functualize-flow-viz | functualize-flow-viz | `functualize_flow_viz` |
| functualize-ai | functualize-ai | `functualize_ai` |
| functualize-ai-pydantic | functualize-ai-pydantic | `functualize_ai_pydantic` |
| functualize-tasks | functualize-tasks | `functualize_tasks` |
| functualize-tasks-local | functualize-tasks-local | `functualize_tasks_local` |
| functualize-mcp | functualize-mcp | `functualize_mcp` |

`functualize-fullscreen-tui` is deliberately absent: it has no `pyproject.toml`, so
it is not a workspace member and produces no distribution.

## Trusted Publishing

Every name above, plus `functualize`, needs its own PyPI trusted publisher — twelve
in total, all sharing this configuration:

| Field | Value |
|-------|-------|
| Owner | `raicing-ai` |
| Repository name | `functualize` |
| Workflow name | `release.yml` — the *filename*, not the `name:` key inside it |
| Environment name | `pypi` |

The `pypi` GitHub environment must also exist on the repository, matching the
`environment: pypi` key in `release.yml`. A name mismatch is the most common
first-release failure.

### Bootstrapping the twelve projects

They cannot all be created by this workflow. A **pending** publisher — the kind that
may create a project that does not exist yet — is unique on the tuple
`(owner, repo, workflow, environment)`, because PyPI has to know which single project
to create when it fires. All twelve packages share that tuple, so registering a second
one fails with:

> A pending trusted publisher matching this configuration has already been registered
> for a different project name.

This is a known monorepo limitation ([warehouse#16920](https://github.com/pypi/warehouse/issues/16920)).
Ordinary trusted publishers carry no such constraint — any number of *existing*
projects may share one repo, workflow, and environment. So the projects are created
once by hand, and trusted publishing takes over from the next release:

1. Create an API token scoped to **the entire account** — a project-scoped token
   cannot create new projects.
2. `uv build --all-packages`, then `twine upload dist/*`. This creates all twelve
   projects and publishes the first version.
3. For each of the twelve, add an ordinary trusted publisher at
   `https://pypi.org/manage/project/<name>/settings/publishing/` using the table above.
4. Delete the account-scoped token.

From then on, a `v*` tag publishes through OIDC with no stored credential. The
`skip-existing: true` flag on the publish step exists for this handover: the first
tag's artifacts are already on the index by the time the workflow runs.

**A pending publisher does not reserve the name.** Until a project is actually
created, anyone may claim it — which is the other reason to run step 2 for all twelve
at once rather than publishing the core package alone.
