"""The reproduction from the field bug report, as three executable cases.

Filed against `0.2.3`, re-verified by the reporter against `0.3.0`, re-verified
against this branch before the spec was written. `[tool.functualize]
plugins_directories` is declared, documented in three places, and **never read**:
`PluginLoader._resolve_plugin_directories` guards the config read behind
``hasattr(app, "_resolution_chain")``, and `load_all` has exactly one production
call site — boot step 4 — where that attribute does not exist yet. Discovery
falls through to an exact-match ``Path.cwd() / ".functualize" / "plugins"``
which, unlike every other anchored thing in this framework, does not walk up.

The layout is the reporter's, and it is the ordinary multi-app shape::

    root/
    ├── .functualize/plugins/marker_plugin.py
    └── hello_app/
        ├── pyproject.toml          # declares plugins_directories
        └── jobs/sample.py

In one boot from ``hello_app/``, the app finds ``root/.functualize/`` as its
project anchor and writes runtime state there — while the plugin loader looks
only at ``hello_app/.functualize/plugins`` and says nothing about it.

Gates AC-1, AC-2 and AC-3 of `.spec/features/declared-plugin-directories/spec.md`.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tests.conftest import surfaces

MARKER = "MARKER_PLUGIN_REGISTERED"

_PLUGIN = textwrap.dedent(
    '''\
    """A file plugin that announces its own registration."""

    from __future__ import annotations

    import sys
    from typing import Any


    class MarkerPlugin:
        name = "marker-plugin"
        version = "1.0.0"
        description = "Prints a marker when the loader registers it."

        def __call__(self, app: Any) -> None:
            print("MARKER_PLUGIN_REGISTERED", file=sys.stderr)


    plugin = MarkerPlugin()
    '''
)

_JOB = textwrap.dedent(
    '''\
    """A trivial job, so boot has something to route to."""


    def sample() -> None:
        """Print a word."""
        print("ran")
    '''
)


def _multi_app_tree(root: Path, *, declare: bool) -> Path:
    """Build the reporter's layout and return the *child app* directory.

    The shared plugin lives at the parent's ``.functualize/plugins/``; the jobs
    and the config live one level down, which is where ``func`` is actually run.
    """
    plugins = root / ".functualize" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "marker_plugin.py").write_text(_PLUGIN)

    app_dir = root / "hello_app"
    (app_dir / "jobs").mkdir(parents=True)
    (app_dir / "jobs" / "sample.py").write_text(_JOB)

    declared = f'plugins_directories = ["{plugins.resolve()}"]\n' if declare else ""
    (app_dir / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "hello-app"
            version = "0.1.0"

            [tool.functualize]
            jobs_directories = ["jobs"]
            {declared}"""
        )
    )
    return app_dir


# --- AC-1 -------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TRANSITIONAL(declared-plugin-directories/T5): the config read is "
        "guarded by hasattr(app, '_resolution_chain'), which is False at boot "
        "step 4 on every production path. T5 moves resolution to the "
        "composition root and this flips to a pass."
    ),
)
@surfaces("func")
def test_a_declared_directory_loads_from_a_subdirectory(cli_run, tmp_path: Path):
    """AC-1 — the headline. A declared directory is honoured from anywhere.

    The path in `pyproject.toml` is absolute, so nothing about where the shell
    happens to be should matter. Today nothing loads, and no warning says why.
    """
    app_dir = _multi_app_tree(tmp_path / "declared", declare=True)

    result = cli_run(["sample"], cwd=app_dir)

    assert result.exit_code == 0, result.stderr
    assert MARKER in (result.stdout + result.stderr)


# --- AC-2 -------------------------------------------------------------------


@surfaces("func")
def test_the_convention_directory_loads_at_the_project_root(cli_run, tmp_path: Path):
    """AC-2 — the one mechanism that works today, and must keep working.

    This is the regression gate on the fix, not a demonstration of the bug:
    cwd *is* the directory holding `.functualize/plugins/`, which is the only
    case the exact-match fallback handles.
    """
    root = tmp_path / "at_root"
    plugins = root / ".functualize" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "marker_plugin.py").write_text(_PLUGIN)

    jobs = root / ".functualize" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "sample.py").write_text(_JOB)

    result = cli_run(["sample"], cwd=root)

    assert result.exit_code == 0, result.stderr
    assert MARKER in (result.stdout + result.stderr)


# --- AC-3 -------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TRANSITIONAL(declared-plugin-directories/T5): the convention "
        "directory is looked for at Path.cwd() exactly, with no upward walk — "
        "while the same boot resolves the project anchor two levels up and "
        "writes fresh.json into it. T5 anchors the convention directory on "
        "that same project root."
    ),
)
@surfaces("func")
def test_the_convention_directory_loads_from_a_subdirectory(cli_run, tmp_path: Path):
    """AC-3 — no config at all; the project root is found by walking up.

    Nothing is declared here. The plugin sits at the project's own
    `.functualize/plugins/`, and `func` runs from the app directory beneath it
    — the layout the reporter had to work around by running from the parent
    with `--discovery-depth` raised.
    """
    app_dir = _multi_app_tree(tmp_path / "convention", declare=False)

    result = cli_run(["sample"], cwd=app_dir)

    assert result.exit_code == 0, result.stderr
    assert MARKER in (result.stdout + result.stderr)
