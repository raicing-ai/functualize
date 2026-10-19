"""Acceptance fixtures for the shell command path contract."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from tests.conftest import surfaces

JOBS = {
    "suite.py": (
        'JOB_GROUP = "suite"\n\n'
        'def inventory() -> None:\n    print("INVENTORY")\n\n'
        'def versions() -> None:\n    print("VERSIONS")\n'
    ),
    "deploy.py": ('JOB_GROUP = "deploy.web"\n\ndef run() -> None:\n    print("RUN")\n'),
    "hello.py": 'def hello() -> None:\n    print("HELLO")\n',
}


def _project(project_tree) -> Path:
    return project_tree(jobs=JOBS)


@surfaces("func")
def test_misspelling_suggests_a_copyable_command(cli_run, project_tree, tmp_path):
    root = _project(project_tree)
    result = cli_run(["suite.inventori"], cwd=root)
    assert result.exit_code == 1
    assert "  func suite inventory" in result.stderr

    suggested = next(
        line.strip()
        for line in result.stderr.splitlines()
        if line.strip() == "func suite inventory"
    )
    home = tmp_path / "subprocess-home"
    home.mkdir()
    env = dict(os.environ)
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / "config"),
        XDG_DATA_HOME=str(home / "data"),
        XDG_CACHE_HOME=str(home / "cache"),
    )
    completed = subprocess.run(
        shlex.split(suggested),
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "INVENTORY" in completed.stdout


@surfaces("func")
def test_nested_and_retired_names_suggest_paths(cli_run, project_tree):
    root = _project(project_tree)
    nested = cli_run(["deploy.web.rnu"], cwd=root)
    retired = cli_run(["versions"], cwd=root)
    assert "func deploy web run" in nested.stderr
    assert "func suite versions" in retired.stderr


@surfaces("func")
def test_leaf_usage_has_the_full_path(cli_run, project_tree):
    result = cli_run(["suite", "inventory", "--help"], cwd=_project(project_tree))
    assert result.exit_code == 0
    assert "Usage: func suite inventory [OPTIONS]" in result.stdout


@surfaces("func")
def test_dotted_group_traversal_is_refused(cli_run, project_tree):
    result = cli_run(["suite.inventory"], cwd=_project(project_tree))
    assert result.exit_code != 0
    assert "navigate groups with spaces" in result.stderr


@surfaces("func")
def test_root_help_lists_jobs_and_groups(cli_run, project_tree):
    root = _project(project_tree)
    cold = cli_run(["--help"], cwd=root)
    warm = cli_run(["--help"], cwd=root)
    assert cold.exit_code == warm.exit_code == 0
    assert "hello" in cold.stdout
    assert "suite" in cold.stdout
    assert cold.stdout == warm.stdout


def test_literal_dot_leaf_and_explicit_group_are_distinct_paths(tmp_path, monkeypatch):
    """The later dot refusal must preserve a dot inside a single leaf."""
    from click.testing import CliRunner

    from functualize._discovery.providers import Job, StaticProvider
    from functualize.app import FunctualizeApp, JobSources
    from functualize.app.adapters import CliAdapter

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    def lint() -> None:
        print("LINT")

    def pack() -> None:
        print("PACK")

    provider = StaticProvider(
        [
            Job(function=lint, name="tools.lint"),
            Job(function=pack, name="pack", group="ci"),
        ]
    )
    app = FunctualizeApp(
        name="sample", job_sources=JobSources(job_providers=[provider])
    )
    adapter = CliAdapter()
    adapter(app)
    runner = CliRunner()
    literal = runner.invoke(adapter._cli_group, ["tools.lint"])
    grouped = runner.invoke(adapter._cli_group, ["ci", "pack"])
    assert literal.exit_code == grouped.exit_code == 0
    assert "LINT" in literal.output
    assert "PACK" in grouped.output
