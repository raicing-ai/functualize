# Testing Strategy

## Two-Tier Test Split

| Tier | What | When to Run | Command |
|------|------|-------------|---------|
| **Fast** (unit) | Unit tests, integration tests | After every change | `uv run pytest` |
| **Slow** (property-based) | Hypothesis tests (100+ examples) | Before pushing / pre-release | `uv run pytest --run-slow` |

Property-based test files are detected by naming convention: `*_properties.py`, `*_props.py`, `*_property.py`.

Those two tiers decide *which* tests exist — `--run-slow` turns the property-based half on.
How much of them to run for a given change is a separate axis: **Step** (the test files that
import what you changed, selected by `tests-for-diff`, 4-15 s when it prints paths),
**Wave** (the test directories the change touches), **Tip** (everything, ~21 min — far past
the 600 s tool-call cap, so it is dispatched or chunked, never one local call). The tiers,
their measured costs and the load they were taken at, the mapper's exit codes and the cap
that shapes them live in `.agents/skills/test-tiers/SKILL.md`.

## Commands

```bash
# Always run lint first
uv run ruff check --fix src/ tests/ plugins/
uv run ruff format src/ tests/ plugins/

# Step tier — only the test files that import what you changed (4-15 s). Run the mapper
# alone first: when it prints nothing (a docs-only change) there is nothing to run, and
# this command would fall through to the whole fast tier.
uv run pytest -n auto -q --no-header $(.agents/skills/test-tiers/scripts/tests-for-diff)

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
plugins/adapters/functualize-inline/tests/
plugins/substrates/functualize-substrate-sqlite/tests/
plugins/adapters/functualize-flow-viz/tests/
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

The *Full tests* row is the **tip tier**: ~21 min on the 4-core runner, which no single tool
call can hold. On a branch it is dispatched rather than waited on —
`gh workflow run CI --ref <branch>` (`workflow_dispatch` on the workflow whose `name:` is
`CI`) — and the verdict is read in a later turn; locally it is chunked into foreground calls
of at most 570 s each. Which tier to pick for a change, and the 600 s cap that forces this,
is in `.agents/skills/test-tiers/SKILL.md`.

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

## A test that spawns a `func` subprocess must give it its own HOME

`tests/conftest.py::_isolate_home` is autouse and points `HOME` at a **fixed**
path — `/tmp/functualize_test_fakehome_nonexistent` — so no test reads the
developer's real configuration. It is one path, shared by every checkout on the
machine, and a subprocess **inherits it** through `os.environ`.

Meanwhile `func` registers itself in `<config>/functualize/install.json` on
every run, and that registry is **append-only by design**: `self doctor` reports
a record whose binary no longer exists as a WARNING and never prunes it. The
file is not under `tmp_path`, so nothing cleans it between runs — or between
worktrees.

Put together: a child launched as `python -c "…main()"` has `argv[0] == "-c"`,
which `main.py` resolves to `<venv>/bin/-c`. That path cannot exist, so
`tests/_cli/test_self_doctor.py::test_a_recognised_installation_reports_ok`
fails — **for every future run, in every checkout, permanently**. Measured: it
did, and the record had to be deleted by hand.

So set all four:

```python
env = dict(os.environ)
home = tmp_path / "_home"
home.mkdir()
env["HOME"] = str(home)
env["XDG_CONFIG_HOME"] = str(home / ".config")
env["XDG_DATA_HOME"] = str(home / ".local" / "share")
env["XDG_CACHE_HOME"] = str(home / ".cache")
subprocess.run([...], env=env, ...)
```

`HOME` alone is not enough to reason about — `_isolate_home` *strips* every
`XDG_*` variable, so the child falls back to `$HOME/.config`; setting them
explicitly means the isolation does not depend on that fallback staying true.

Worked example: `tests/spec/test_disabled_is_honoured_by_the_builtin_commands.py`.
