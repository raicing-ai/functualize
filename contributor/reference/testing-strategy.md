# Testing Strategy

## Two-Tier Test Split

| Tier | What | When to Run | Command |
|------|------|-------------|---------|
| **Fast** (unit) | Unit tests, integration tests | After every change | `uv run pytest` |
| **Slow** (property-based) | Hypothesis tests (100+ examples) | Before pushing / pre-release | `uv run pytest --run-slow` |

Property-based test files are detected by naming convention: `*_properties.py`, `*_props.py`, `*_property.py`.

## Commands

```bash
# Always run lint first
uv run ruff check --fix src/ tests/ plugins/
uv run ruff format src/ tests/ plugins/

# Fast tests only (default)
uv run pytest

# Full suite including property-based
uv run pytest --run-slow

# CI-equivalent (parallel + coverage). The profile is part of the equivalence:
# `ci` draws 200 examples, the default draws 100.
HYPOTHESIS_PROFILE=ci uv run pytest --run-slow --cov=functualize -n auto

# Quick smoke-check (10 hypothesis examples)
HYPOTHESIS_PROFILE=dev uv run pytest --run-slow
```

## Hypothesis Profiles

| Profile | Examples | Use Case |
|---------|----------|----------|
| `dev` | 10 | Quick sanity check |
| `default` | 100 | Normal development |
| `ci` | 200 | GitHub Actions |

Set via: `HYPOTHESIS_PROFILE=dev`

## Test Organization

Tests mirror the source domain structure under `src/functualize/`. Each domain has its own test directory:

```
tests/
├── adapters/                # Tests for src/functualize/adapters/
│   └── test_*.py
├── config/                  # Tests for src/functualize/_config/
│   └── test_*.py
├── core/                    # Tests for src/functualize/_core/ (if applicable)
│   └── test_*.py
├── discovery/               # Tests for src/functualize/_discovery/
│   └── test_*.py
├── execution/               # Tests for src/functualize/_engine/
│   └── test_*.py
├── hooks/                   # Tests for src/functualize/_events/hooks
│   └── test_*.py
├── observability/           # Tests for src/functualize/_events/
│   └── test_*.py
├── perf/                    # Performance tests
│   └── test_*.py
├── plugins/                 # Plugin-specific tests
│   └── test_*.py
├── validation/              # Tests for src/functualize/_validation/
│   └── test_*.py
├── tui/                     # Tests for src/functualize/_cli/tui/
│   └── test_*.py
├── cli/                     # Tests for src/functualize/_cli/
│   └── test_*.py
├── _cli/                    # Tests for src/functualize/_cli/ (other components)
│   └── test_*.py
├── integration/             # Integration tests (real components)
│   └── test_*.py
├── e2e/                     # End-to-end tests
│   ├── fixtures/            # Test data and project fixtures
│   └── test_*.py
├── hierarchy/               # Tests for project hierarchy
│   └── test_*.py
├── context/                 # Tests for execution context
│   └── test_*.py
├── standalone/              # Tests for standalone mode
│   └── test_*.py
├── scaffold/                # Tests for scaffold command
│   └── test_*.py
├── _support/                # Shared test fixtures and helpers
│   ├── configs/
│   ├── projects/
│   ├── jobs/
│   └── conftest.py
├── test_*.py                # Top-level unit/integration tests
└── conftest.py              # Root fixture configuration
```

**Property-based tests** are identified by filename suffix and live colocated in their domain directory:
- `test_*_properties.py` — full Hypothesis property test
- `test_*_props.py` — abbreviated property test
- `test_*_property.py` — singular property test

## What to Test Where

| Type of Code | Test Approach | Tier |
|---|---|---|
| `_primitives/` utilities | Property-based (universal invariants) | Slow |
| `_engine/` execution logic | Property + unit (lifecycle correctness) | Both |
| `_discovery/` providers | Property (cache validity, extraction completeness) | Slow |
| `app/` public facade | Unit (specific scenarios, error messages) | Fast |
| `_cli/` routing | Unit (arg parsing, mode resolution) | Fast |
| Boot sequence | Integration (real components, minimal stubs) | Fast |
| Static wiring fast path | Integration (timing assertion <5ms) | Fast |
| Plugin packages | Unit (mocked app, verify protocol satisfaction) | Fast |

## Property Test Conventions

Tag format in docstrings:
```python
# Feature: codebase-restructure, Property 1: Preset factory functions produce ConfigSources
```

Each property test validates specific requirements (traced via `**Validates: Requirements X.Y**`).

## Plugin Tests

Plugin-specific tests live in each plugin's own `tests/` directory:

```
plugins/functualize-inline/tests/
plugins/functualize-state-sqlite/tests/
plugins/functualize-flow-viz/tests/
tests/ui/  # functualize.ui (TextualApp, fullscreen)
```

Run them directly with `pytest plugins/<name>/tests/`; they are not collected by the root `pytest` invocation.

## CI Pipeline

| Step | What | Fails on |
|------|------|----------|
| Lint | `ruff check` + `ruff format --check` | Any lint error or format diff |
| Type check | `mypy src/` | Any type error |
| Import rules | `lint-imports` | Any layer contract violation |
| Fast tests | `pytest` (unit only) | Any test failure |
| Full tests | `HYPOTHESIS_PROFILE=ci pytest --run-slow --cov -n auto` | Any failure, across Python 3.11/3.12/3.13 |

## Writing New Tests

1. **For new code in a domain**: Place tests in the corresponding mirrored directory
   - New code in `src/functualize/_discovery/` → tests go in `tests/discovery/test_*.py`
   - New code in `src/functualize/_config/` → tests go in `tests/config/test_*.py`

2. **For internal utilities (zero-dep helpers)**: Write property tests with suffix
   - `tests/<domain>/test_<module>_properties.py` (Hypothesis property tests)
   - Property tests live alongside unit tests, identified by suffix

3. **For public API methods**: Write unit tests in the domain's test directory

4. **For a new plugin**: Create `tests/plugins/test_<plugin>.py`

5. **For a bug fix**: Write a regression test that fails without the fix, place in the relevant domain directory

Always ensure `lint-imports` passes — a test importing the wrong layer is itself a violation.
