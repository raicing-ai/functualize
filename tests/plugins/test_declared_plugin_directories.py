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


# --- AC-4 ---------------------------------------------------------------------


@surfaces("func")
def test_declared_and_convention_both_load(cli_run, tmp_path: Path):
    """AC-4 — declaring one directory does not cost you your own.

    The falsifier for the old early-return: the config branch `return`ed its
    result, so a project that declared an extra directory would have lost
    `.functualize/plugins/` entirely. It never fired, so nobody hit it — but the
    bug was there, and this is what pins the fix.
    """
    root = tmp_path / "both"
    convention = root / ".functualize" / "plugins"
    convention.mkdir(parents=True)
    (convention / "convention_plugin.py").write_text(
        _PLUGIN.replace("MARKER_PLUGIN_REGISTERED", "CONVENTION_MARKER").replace(
            "marker-plugin", "convention-plugin"
        )
    )

    extra = root / "shared"
    extra.mkdir()
    (extra / "declared_plugin.py").write_text(
        _PLUGIN.replace("MARKER_PLUGIN_REGISTERED", "DECLARED_MARKER").replace(
            "marker-plugin", "declared-plugin"
        )
    )

    jobs = root / ".functualize" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "sample.py").write_text(_JOB)
    (root / ".functualize.toml").write_text(
        f'plugins_directories = ["{extra.resolve()}"]\n'
    )

    result = cli_run(["sample"], cwd=root)

    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert "DECLARED_MARKER" in combined, "the declared directory did not load"
    assert "CONVENTION_MARKER" in combined, "declaring one suppressed the other"


# --- AC-5 ---------------------------------------------------------------------


@surfaces("func")
def test_ambient_refusal_holds_one_level_up_too(cli_run, tmp_path: Path):
    """AC-5 — widening the search must not widen the hijack.

    `func <file>.py <job>` sets `ambient_directory=False` so a neighbour's
    `.functualize/plugins/` cannot take over an invocation that named a
    different program. Before this feature the refusal only had to cover the
    literal cwd, because that was the only place the loader looked. Now the
    convention directory is found by walking up — so the refusal has to cover
    the project root as well, which is what this places the hijacker at.
    """
    project = tmp_path / "project"
    plugins = project / ".functualize" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "killer.py").write_text(
        'import sys\n\nprint("ANCESTOR PLUGIN RAN", file=sys.stderr)\n'
    )

    here = project / "scripts"
    here.mkdir()
    (here / "weather.py").write_text(
        'def trip_planner() -> None:\n    """Plan."""\n    print("PLANNED")\n'
    )

    result = cli_run(["weather.py", "trip_planner"], cwd=here)

    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert "PLANNED" in result.stdout
    assert "ANCESTOR PLUGIN RAN" not in combined


# --- AC-6, AC-6b, AC-6c -------------------------------------------------------


@surfaces("func")
def test_a_missing_declared_directory_warns_by_name(cli_run, tmp_path: Path):
    """AC-6 — a typo'd path is reported, on a default run, with no flags.

    Before this feature there was no message at any level. Measured: at
    `--log-level debug`, the most verbose setting the CLI offers, the string
    `plugins_directories` never appeared once.
    """
    root = tmp_path / "typo"
    jobs = root / ".functualize" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "sample.py").write_text(_JOB)
    missing = root / "not_here"
    (root / ".functualize.toml").write_text(
        f'plugins_directories = ["{missing.resolve()}"]\n'
    )

    result = cli_run(["sample"], cwd=root)

    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert "does not exist" in combined
    assert str(missing.resolve()) in combined, "the warning must name the path"


@surfaces("func")
def test_an_empty_declared_directory_warns_by_name(cli_run, tmp_path: Path):
    """AC-6b — the directory is there, but nothing in it is a plugin.

    Usually a `.py` file missing its `name`/`version`/`description`. Reported
    separately from the missing case because the fix is different.
    """
    root = tmp_path / "empty"
    jobs = root / ".functualize" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "sample.py").write_text(_JOB)
    empty = root / "no_plugins"
    empty.mkdir()
    (root / ".functualize.toml").write_text(
        f'plugins_directories = ["{empty.resolve()}"]\n'
    )

    result = cli_run(["sample"], cwd=root)

    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert "no loadable plugin" in combined
    assert str(empty.resolve()) in combined


@surfaces("func")
def test_a_project_declaring_nothing_stays_silent(cli_run, tmp_path: Path):
    """AC-6c — the falsifier for over-applying AC-6.

    Most projects have no `.functualize/plugins/` and never will. An absent
    *convention* directory is not a mistake and must not produce a line on
    every single run — that is how a warning becomes noise and stops being read.
    """
    root = tmp_path / "quiet"
    jobs = root / ".functualize" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "sample.py").write_text(_JOB)

    result = cli_run(["sample"], cwd=root)

    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert "plugin directory" not in combined.lower()


# --- AC-9b --------------------------------------------------------------------


def test_a_programmatic_app_honours_a_declared_directory(tmp_path, monkeypatch):
    """AC-9b — no CLI anywhere in the picture.

    Walk A runs in `_cli/main.py`, not in boot — measured, `rg auto_discover
    src/functualize/_app/` returned nothing. So a library user constructing
    `FunctualizeApp` directly never ran it, and any fix that only touched the
    CLI would have left them broken. Boot resolves for itself now, and this is
    the test that says so.
    """
    from functualize.app import FunctualizeApp

    root = tmp_path / "programmatic"
    shared = root / "shared_plugins"
    shared.mkdir(parents=True)
    (shared / "marker_plugin.py").write_text(_PLUGIN)
    (root / ".functualize.toml").write_text(
        f'plugins_directories = ["{shared.resolve()}"]\n'
    )

    monkeypatch.chdir(root)
    app = FunctualizeApp(name="programmatic")

    assert "marker-plugin" in app.plugin_loader.loaded_plugins
