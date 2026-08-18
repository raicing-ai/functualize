# Monorepo Children — Child Projects Example

Demonstrates functualize's **child project composition**: a parent app that
composes jobs from multiple sub-projects under namespace prefixes, all sharing
a single Python environment.

## Directory Structure

```
monorepo_children/
├── pyproject.toml              ← Parent project (depends on functualize + all child deps)
├── config.base.toml            ← Parent config
├── src/platform_ops/
│   ├── main.py                 ← FunctualizeApp wiring with children={...}
│   └── jobs/
│       └── ops.py              ← Parent-level shared ops jobs
├── services/
│   ├── auth/                   ← Child project: auth service
│   │   ├── pyproject.toml      ← Metadata only (version compat check)
│   │   └── jobs/
│   │       └── auth_jobs.py    ← Auth jobs (namespace: "auth")
│   └── billing/                ← Child project: billing service
│       ├── pyproject.toml      ← Metadata only (version compat check)
│       └── jobs/
│           └── billing_jobs.py ← Billing jobs (namespace: "billing")
└── tests/
    └── test_children.py
```

## Usage

```bash
cd examples/project/monorepo_children
uv sync

# Run parent-level ops jobs
uv run platform-ops health_check
uv run platform-ops report

# Run child project jobs (namespaced)
uv run platform-ops auth.login
uv run platform-ops auth.rotate_keys
uv run platform-ops billing.invoice
uv run platform-ops billing.reconcile

# Show full CLI help — all 6 jobs (parent + children) listed
uv run platform-ops --help

# Show project info including mounted children table
uv run platform-ops show-info
```

## What This Demonstrates

- **`JobSources(children={...})`** — explicit namespace→path child mapping
- **Namespace prefixing** — child jobs appear as `auth.login`, `billing.invoice`
- **Shared Python environment** — all child deps installed in parent's venv
- **TUI integration** — child jobs appear in the job browser with "child" provenance badges
- **Validation** — `HierarchyValidator` checks version compatibility at boot
- **JOB_GROUP inside children** — child modules can define groups for nested CLI hierarchies

## How It Works

1. Parent's `FunctualizeApp` declares `children={"auth": "./services/auth", "billing": "./services/billing"}`
2. At boot, functualize scans each child's `jobs/` directory for `.py` modules
3. Discovered jobs are wrapped in a `NamespaceTransform(namespace)` — prefixing all names
4. The CLI/TUI sees them as regular jobs with dotted names (`auth.login`, `billing.invoice`)
5. Child `pyproject.toml` is read only for version-compatibility validation

## Key Concepts

- **Children share the parent's Python process and sys.path** — if a child job imports `boto3`, that package must be in the parent's environment
- **Child pyproject.toml is metadata, not an install target** — it declares `functualize>=X.Y.Z` for the validator to check; the parent's `pyproject.toml` is the actual source of truth for dependencies
- **Namespace isolation is name-only** — child jobs can still call `rc.invoke("billing.reconcile")` to reach sibling children

## Alternatives

- For dependency-isolated extensions, use the **plugin system** instead (`plugins/` examples)
- For auto-discovering child directories, use `children_glob="services/*/"`
- For truly independent projects with separate venvs, use entry-point plugins
