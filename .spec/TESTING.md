# Testing Guidelines

This project uses a multi-tier test strategy. Follow these rules when running tests:

## Commands

- **Lint & format (always run first):**
  1. `uv run ruff check --fix src/ tests/ plugins/`
  2. `uv run ruff format src/ tests/ plugins/`
- **Fast tests (unit only):** `uv run pytest -x -q --no-header`
- **Full tests (including property-based):** `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q --no-header` — the `ci` profile (200 examples) is what CI runs; without it you are verifying a weaker gate. Budget ~10 minutes.
- **Example projects:** `uv run pytest examples/ -v` — `testpaths = ["tests"]`, so the
  root invocation does **not** collect these. Requires `uv sync --all-packages` (the AI
  and plugin examples import workspace packages). CI runs it in the `examples` job.
- **Documented commands:** `PATH="$PWD/.venv/bin:$PATH" python
  .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/ --engine shell`
  — runs the commands the docs tell a reader to run and compares the output against
  what the docs claim. Must be invoked **from the repository root**; a shell step's
  `cwd` is process-relative. Without `.venv/bin` on `PATH` every step exits 127 and
  reports as documentation drift, so **before believing a failure, run
  `a-core-builtins`** to prove the harness works. CI runs the shell subset in the
  `doc-verify` job; the release pass runs all engines.

!!! note "The three sync flags prune each other"
    `uv sync --all-packages`, `--all-extras` and `--group docs` each drop what the
    others install. Each CI job has its own environment, so each flag is right there.
    A local pass that runs all of the above needs
    `uv sync --all-packages --all-extras --group docs`. Running one alone produces
    failures that look like real defects.

## When to run tests

- **Before running any tests:** Always run ruff check and ruff format first to catch lint/format issues early. Fix any remaining errors that `--fix` cannot auto-resolve.
- **After implementing code changes:** Run fast tests to verify nothing is broken.
- **After completing a spec task (final checkpoint):** Run the full test suite including `--run-slow` to validate property-based invariants hold.
- **Do NOT run full (slow) tests on intermediate steps** — only at the end of each task.

## Test tiers

| Tier | Marker | Speed | Description |
|------|--------|-------|-------------|
| Unit | (default) | <1s each | Pure logic, single-module isolation |
| Property-based | `_properties.py` / `_props.py` suffix | ~seconds | Hypothesis-driven invariants |
| CLI integration | (default) | <100ms each | In-process `cli_run` fixture, real routing |
| TUI Pilot | `@pytest.mark.asyncio` | <200ms each | Headless Textual interaction |
| E2E / interactive | `@pytest.mark.slow` | seconds | pexpect with real PTY |

## CLI Testing Infrastructure

The CLI test infrastructure is inspired by [pyinvoke's testing patterns](https://github.com/pyinvoke/invoke/tree/main/tests): in-process execution, static fixture projects, and env isolation without subprocess overhead.

### Core fixtures (defined in `tests/conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `_isolate_home` | autouse | Patches `Path.home()` and strips `FUNCTUALIZE_*` / `XDG_*` env vars. Prevents tests from reading the developer's real config. |
| `xdg_dirs` | per-test | Creates a temporary XDG directory layout (`config`, `data`, `cache`, `home`). Returns a namespace with convenience paths like `xdg_dirs.functualize_config`. |
| `project_tree` | per-test | Factory fixture for creating project directories dynamically. Accepts `jobs`, `plugins`, `pyproject`, `functualize_toml`, `convention_dirs`. |
| `cli_run` | per-test | In-process CLI runner. Calls `main()` directly with captured stdout/stderr. Returns `namespace(stdout, stderr, exit_code)`. Depends on `xdg_dirs` for isolation. |
| `clean_sys_modules` | per-test | Snapshots `sys.modules` and restores after test. Prevents import bleed between discovery tests. |

### In-process CLI runner (`cli_run`)

The `cli_run` fixture exercises the real `functualize._cli.main:main` entry point in the current process. No subprocess is spawned. This gives:

- **Speed:** ~50ms per test (vs 500ms+ for subprocess).
- **Coverage:** exercises the full boot → resolve → route → execute stack.
- **Debuggability:** breakpoints work, stack traces are local.

```python
def test_job_execution(cli_run, project_tree):
    root = project_tree(
        jobs={"hello.py": "def hello():\n    print('world')\n"}
    )
    result = cli_run(["hello"], cwd=root)
    assert result.exit_code == 0
    assert "world" in result.stdout
```

Parameters:
- `args: list[str] | str` — CLI arguments (without the `func` prefix).
- `cwd: Path | None` — working directory for the invocation.
- `env: dict[str, str] | None` — additional environment variables to set.

### XDG virtual filesystem (`xdg_dirs`)

Creates a complete XDG directory layout in `tmp_path` and wires up all env vars. No external tools (pyfakefs) needed.

```python
def test_global_config_loaded(cli_run, xdg_dirs, project_tree):
    config_dir = xdg_dirs.functualize_config
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text('[cli]\noutput = "json"\n')

    root = project_tree(jobs={"noop.py": "def noop(): pass\n"})
    result = cli_run(["noop"], cwd=root)
    assert result.exit_code == 0
```

The `_isolate_home` autouse fixture ensures no test can accidentally read the developer's real `~/.config/functualize/` or `XDG_*` env vars.

### Static fixture projects (`tests/_support/`)

Complex project layouts that multiple tests share are committed to `tests/_support/`:

```
tests/_support/
├── projects/
│   ├── minimal/         — single job, pyproject.toml
│   ├── grouped/         — JOB_GROUP modules (infra, deploy)
│   ├── multi_config/    — pyproject.toml + .functualize.toml (precedence test)
│   └── with_plugins/    — file-based plugin
├── configs/
│   ├── global_plain/    — output = "plain"
│   ├── global_json/     — output = "json"
│   └── global_with_aliases/ — alias definitions
└── jobs/
    ├── simple.py        — no params, just prints
    ├── parameterized.py — typed params (env, dry, replicas)
    ├── grouped.py       — JOB_GROUP = "infra"
    ├── failing.py       — always raises RuntimeError
    └── with_deps.py     — DI capabilities (Log)
```

Use static fixtures for complex, multi-test scenarios. Use `project_tree` factory for simple/dynamic cases.

### `expect()` helper

A convenience function for readable assertions on `cli_run` results:

```python
from tests.conftest import expect

result = cli_run(["version"])
expect(result, stdout_contains="functualize", exit_code=0)
```

### Test matrix dimensions

When writing CLI integration tests, consider these dimensions:

| Dimension | Values |
|-----------|--------|
| Routing mode | BARE, SINGLE_FILE, GROUP, JOB, BUILTIN, UNKNOWN |
| Config sources | XDG global, pyproject.toml, .functualize.toml, env vars, CLI flags |
| Discovery | convention dirs, explicit dirs, filters, JOB_GROUP |
| Boot state | cold (no cache), warm (cache exists), invalidated |
| Error conditions | missing job, bad config syntax, permission errors, failing job |

## TUI Testing

### Tier 1: Textual Pilot (fast, headless)

For Textual-based apps, use `app.run_test()` which runs the app headlessly:

```python
@pytest.mark.asyncio
async def test_key_press():
    app = MyTuiApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        assert app.some_state is True
```

Works in CI, no terminal needed. Test key presses, clicks, widget queries, screen cycling, and terminal size variations.

### Tier 2: Visual regression (`pytest-textual-snapshot`)

For catching layout/styling regressions without brittle position assertions:

```python
def test_main_layout(snap_compare):
    assert snap_compare("path/to/tui_app.py", terminal_size=(80, 24))
```

Run `pytest --snapshot-update` to accept new baselines.

### Tier 3: pexpect (real PTY, slow)

Only for scenarios requiring a real terminal — interactive prompts, signal handling, ANSI detection:

```python
@pytest.mark.slow
def test_ctrl_c_exits_cleanly(tmp_path):
    child = pexpect.spawn("func slow", cwd=str(tmp_path), timeout=10)
    child.expect("starting")
    child.sendcontrol("c")
    child.expect(pexpect.EOF)
    assert "Traceback" not in child.before.decode()
```

Marked `@pytest.mark.slow` — skipped by default, runs with `--run-slow`.

## Plugin tests

Plugin-specific tests live in each plugin's own `tests/` directory (e.g. `plugins/functualize-state-sqlite/tests/`).
Run them directly with `pytest plugins/<name>/tests/`; they are not collected
by the root `pytest` invocation.

## Documentation and examples as a tested surface

The docs and `examples/` are a second product surface, and a claim about *runtime
behaviour* — "this field is masked" — is invisible to a static doc scan while being
false. See [`contributor/guides/docs-example-parity.md`](../contributor/guides/docs-example-parity.md)
for the pass that catches it, the drift classes it found, and the detection method for
each. Run it before a release.
