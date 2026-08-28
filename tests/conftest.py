"""Shared test configuration and fixtures for functualize tests.

This module provides:
- Hypothesis profiles (dev/default/ci)
- Slow test marker infrastructure
- XDG isolation fixtures (prevent home-dir bleed)
- Virtual filesystem fixtures (xdg_dirs, project_tree)
- In-process CLI runner (cli_run)
- sys.modules isolation (clean_sys_modules)
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import types
from collections.abc import Iterator
from io import StringIO
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

from functualize._primitives.entry_points import clear_entry_point_cache

# ===========================================================================
# Paths
# ===========================================================================

SUPPORT = Path(__file__).parent / "_support"
SUPPORT_PROJECTS = SUPPORT / "projects"
SUPPORT_CONFIGS = SUPPORT / "configs"
SUPPORT_JOBS = SUPPORT / "jobs"


# ===========================================================================
# Hypothesis Profiles
# ===========================================================================
# dev: quick smoke-check during active development (HYPOTHESIS_PROFILE=dev)
# default: balanced coverage for local full runs
# ci: thorough coverage in CI (HYPOTHESIS_PROFILE=ci in workflow)
#
# The profile is the ONE knob for how hard the property tier works, so it has
# to be reachable from outside. This previously called `load_profile("default")`
# unconditionally while `ci.yml` set `HYPOTHESIS_PROFILE: ci` — so the `ci`
# profile had never once run, and there was no way to ask for a faster local
# pass either.
#
# A per-test `@settings(max_examples=...)` still overrides whatever is loaded
# here, so pinning that inline gives a test up its tunability. Prefer leaving
# the budget to the profile unless a specific property genuinely needs more.

# `deadline=None` everywhere, not just in CI. Hypothesis's default is a 200ms
# wall-clock budget per example, which measures how loaded the machine is
# rather than anything about the code: this tier is normally run under `-n 10`,
# where a worker routinely loses a few hundred milliseconds to its peers. The
# `too_slow` health check is suppressed for the same reason — it also times
# input generation against the clock. Genuinely slow properties are found by
# `--durations`, which reports without failing.
settings.register_profile(
    "dev",
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "default",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "ci",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


# ===========================================================================
# Slow Test Marker (property-based tests)
# ===========================================================================


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow tests (property-based / hypothesis)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (property-based, hypothesis)"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-slow"):
        return
    skip_slow = pytest.mark.skip(reason="Need --run-slow option to run")
    for item in items:
        # Auto-skip based on file naming convention
        if (
            "_properties" in item.nodeid
            or "_props" in item.nodeid
            or "_property" in item.nodeid
            or "slow" in item.keywords
        ):
            item.add_marker(skip_slow)


# ===========================================================================
# Core Isolation Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent tests from reading the developer's real home/XDG directories.

    Inspired by pyinvoke's `fake_user_home` autouse fixture. Patches
    Path.home() and strips all FUNCTUALIZE_* and XDG_* env vars so no
    test accidentally depends on the developer's local configuration.

    Individual tests that need XDG paths should use the `xdg_dirs` fixture,
    which sets up a clean temporary layout.
    """
    fake_home = Path("/tmp/functualize_test_fakehome_nonexistent")  # noqa: S108
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    # Strip real FUNCTUALIZE_* and XDG_* vars
    for key in list(os.environ):
        if key.startswith(("FUNCTUALIZE_", "XDG_")):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _reset_entry_point_cache() -> Iterator[None]:
    """Give every test a cold entry-point snapshot.

    `_primitives.entry_points` scans the path once per process and reuses the
    result, which is right for a real run and wrong for a suite: a test that
    boots a real app would otherwise leave its snapshot in place for a later
    test that fabricates a distribution on `sys.path` and expects discovery to
    find it. The dependency would be invisible and order-sensitive, so the
    cache is cleared on both sides of every test rather than in the handful of
    tests that look like they need it today.

    Cheap: clearing an empty cache is a lock and an assignment, and the rescan
    only happens for tests that actually ask for entry points.
    """
    clear_entry_point_cache()
    yield
    clear_entry_point_cache()


@pytest.fixture(autouse=True)
def _restore_environ() -> Iterator[None]:
    """Give every test back the environment it started with.

    A test that loads a `.env` in-process — `--dotenv-file` through the
    `CliRunner`, or a direct `load_dotenv()` — mutates `os.environ` for the
    rest of the session. `monkeypatch` cannot undo that: monkeypatch reverses
    what *monkeypatch* did, and this was done by production code holding a real
    reference to the process environment.

    This shipped. `tests/core/test_show_info.py`'s `dotenv_file` fixture writes
    `MY_VAR=hello`, and `tests/cli/test_cli_integration.py::test_no_dotenv_flag`
    asserts `MY_VAR` is *unset* to prove `--no-dotenv` suppresses loading. Each
    passes alone; run in one process in that order, the second reads the first's
    leak and fails — an order-dependent failure in the one test whose subject is
    environment isolation.

    Same reasoning as `_reset_entry_point_cache` above: the coupling is
    invisible and order-sensitive, so the environment is restored on both sides
    of every test rather than in the handful that look like they need it today.
    """
    saved = os.environ.copy()
    yield
    if os.environ != saved:
        # Restore by difference rather than clear-then-update: the TUI tests
        # run worker threads, and a thread that reads the environment during
        # teardown must never observe the empty window a `clear()` opens.
        for key in set(os.environ) - set(saved):
            os.environ.pop(key, None)
        for key, value in saved.items():
            if os.environ.get(key) != value:
                os.environ[key] = value


@pytest.fixture()
def xdg_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Virtual XDG directory layout — lightweight, no external tools needed.

    Creates a real (but temporary) filesystem with standard XDG directories,
    wires up all env vars and Path.home(), and returns a namespace for
    convenient access to the paths.

    Usage::

        def test_global_config_loaded(xdg_dirs, cli_run, project_tree):
            config_dir = xdg_dirs.functualize_config
            config_dir.mkdir(parents=True)
            (config_dir / "config.toml").write_text('[cli]\\noutput = "json"\\n')
            ...
    """
    config_home = tmp_path / "xdg" / "config"
    data_home = tmp_path / "xdg" / "data"
    cache_home = tmp_path / "xdg" / "cache"
    home = tmp_path / "home"

    for d in (config_home, data_home, cache_home, home):
        d.mkdir(parents=True)

    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    return types.SimpleNamespace(
        root=tmp_path / "xdg",
        config=config_home,
        data=data_home,
        cache=cache_home,
        home=home,
        # Functualize-specific convenience paths
        functualize_config=config_home / "functualize",
        functualize_cache=cache_home / "functualize",
        functualize_data=data_home / "functualize",
    )


@pytest.fixture()
def project_tree(tmp_path: Path):
    """Factory fixture for creating project directory trees dynamically.

    Use for simple/dynamic test cases. For complex, multi-test project
    trees, prefer static fixtures in tests/_support/projects/.

    Usage::

        def test_job_discovery(project_tree, cli_run):
            root = project_tree(
                jobs={"hello.py": "def run():\\n    print('hi')\\n"},
                convention_dirs=True,
            )
            result = cli_run(["hello"], cwd=root)
            assert "hi" in result.stdout
    """

    _counter = [0]

    def _make(
        *,
        pyproject: str | None = None,
        functualize_toml: str | None = None,
        jobs: dict[str, str] | None = None,
        convention_dirs: bool = False,
        plugins: dict[str, str] | None = None,
        lib_files: dict[str, str] | None = None,
        extra_files: dict[str, str] | None = None,
    ) -> Path:
        _counter[0] += 1
        root = tmp_path / f"project_{_counter[0]}"
        root.mkdir(exist_ok=True)

        if pyproject:
            (root / "pyproject.toml").write_text(pyproject)
        if functualize_toml:
            (root / ".functualize.toml").write_text(functualize_toml)
        if convention_dirs:
            (root / ".functualize" / "jobs").mkdir(parents=True, exist_ok=True)
            (root / ".functualize" / "lib").mkdir(parents=True, exist_ok=True)
            (root / ".functualize" / "plugins").mkdir(parents=True, exist_ok=True)
        if jobs:
            jobs_dir = root / ".functualize" / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            for name, content in jobs.items():
                (jobs_dir / name).write_text(content)
        if plugins:
            plugins_dir = root / ".functualize" / "plugins"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            for name, content in plugins.items():
                (plugins_dir / name).write_text(content)
        if lib_files:
            lib_dir = root / ".functualize" / "lib"
            lib_dir.mkdir(parents=True, exist_ok=True)
            for name, content in lib_files.items():
                (lib_dir / name).write_text(content)
        if extra_files:
            for rel_path, content in extra_files.items():
                target = root / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)

        return root

    return _make


@pytest.fixture()
def clean_sys_modules():
    """Snapshot sys.modules and restore after test completes.

    Pyinvoke-inspired: prevents import bleed between tests that exercise
    dynamic job discovery (which imports user modules at runtime). Without
    this, a test that imports `tests._support.projects.minimal.jobs.hello`
    could bleed into a subsequent test.
    """
    snapshot = sys.modules.copy()
    yield
    # Remove anything newly imported
    for name in list(sys.modules):
        if name not in snapshot:
            del sys.modules[name]
    # Restore anything that was modified
    sys.modules.update(snapshot)


# ===========================================================================
# In-Process CLI Runner (pyinvoke-inspired)
# ===========================================================================


@pytest.fixture()
def cli_run(xdg_dirs: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch):
    """In-process CLI runner that exercises the real main() path.

    Returns a callable: (args, cwd=None, env=None) -> SimpleNamespace(stdout, stderr, exit_code)

    Inspired by pyinvoke's run()/expect() helpers. Runs functualize's main()
    in the current process with captured stdout/stderr. No subprocess overhead,
    fast and deterministic.

    The `xdg_dirs` dependency ensures all XDG paths are isolated. Tests can
    write config files into `xdg_dirs.functualize_config` to test config
    resolution without touching the real filesystem.

    Usage::

        def test_version_flag(cli_run):
            result = cli_run(["--version"])
            assert result.exit_code == 0
            assert "functualize" in result.stdout.lower() or "0." in result.stdout

        def test_job_execution(cli_run, project_tree):
            root = project_tree(jobs={"hi.py": "def run():\\n    print('hi')\\n"})
            result = cli_run(["hi"], cwd=root)
            assert result.exit_code == 0
            assert "hi" in result.stdout
    """

    def _run(
        args: list[str] | str,
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> types.SimpleNamespace:
        if isinstance(args, str):
            args = args.split()

        old_argv = sys.argv[:]
        stdout_buf = StringIO()
        stderr_buf = StringIO()

        if env:
            for k, v in env.items():
                monkeypatch.setenv(k, v)

        try:
            sys.argv = ["func"] + args
            if cwd:
                monkeypatch.chdir(cwd)

            # Reset logging to avoid handler accumulation across tests
            logging.root.handlers.clear()

            with (
                contextlib.redirect_stdout(stdout_buf),
                contextlib.redirect_stderr(stderr_buf),
            ):
                try:
                    from functualize._cli.main import main

                    main()
                    code = 0
                except SystemExit as e:
                    code = e.code if e.code is not None else 0
                except Exception as exc:
                    # Capture unexpected exceptions as stderr + exit 1
                    stderr_buf.write(f"{type(exc).__name__}: {exc}\n")
                    code = 1
        finally:
            sys.argv = old_argv

        return types.SimpleNamespace(
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            exit_code=code,
        )

    return _run


# ===========================================================================
# Convenience: expect() helper (pyinvoke-style assertion)
# ===========================================================================


def expect(
    result: types.SimpleNamespace,
    *,
    stdout_contains: str | list[str] | None = None,
    stderr_contains: str | list[str] | None = None,
    exit_code: int = 0,
    stdout_not_contains: str | list[str] | None = None,
) -> None:
    """Assert properties of a cli_run result.

    Designed for readable, pyinvoke-style test assertions::

        result = cli_run(["--version"])
        expect(result, stdout_contains="functualize", exit_code=0)
    """
    assert result.exit_code == exit_code, (
        f"Expected exit_code={exit_code}, got {result.exit_code}.\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    if stdout_contains is not None:
        items = (
            [stdout_contains] if isinstance(stdout_contains, str) else stdout_contains
        )
        for item in items:
            assert item in result.stdout, (
                f"Expected {item!r} in stdout.\nstdout: {result.stdout!r}"
            )

    if stderr_contains is not None:
        items = (
            [stderr_contains] if isinstance(stderr_contains, str) else stderr_contains
        )
        for item in items:
            assert item in result.stderr, (
                f"Expected {item!r} in stderr.\nstderr: {result.stderr!r}"
            )

    if stdout_not_contains is not None:
        items = (
            [stdout_not_contains]
            if isinstance(stdout_not_contains, str)
            else stdout_not_contains
        )
        for item in items:
            assert item not in result.stdout, (
                f"Did NOT expect {item!r} in stdout.\nstdout: {result.stdout!r}"
            )
