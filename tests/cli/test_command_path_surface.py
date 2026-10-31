"""Acceptance fixtures for the shell command path contract."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

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
def test_bare_non_tty_listing_prints_paths(cli_run, project_tree):
    result = cli_run([], cwd=_project(project_tree))
    assert result.exit_code == 0
    assert "suite inventory" in result.stdout
    assert "deploy web run" in result.stdout
    assert "suite.inventory" not in result.stdout


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


def test_app_door_grouped_literal_dot_leaf_runs_under_printed_path(
    tmp_path, monkeypatch
):
    """The grouped Click leaf must run under the path shown in the refusal."""
    from click.testing import CliRunner

    from functualize._discovery.providers import Job, StaticProvider
    from functualize.app import FunctualizeApp, JobSources
    from functualize.app.adapters import CliAdapter

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    def lint() -> None:
        print("LINT")

    app = FunctualizeApp(
        name="s",
        job_sources=JobSources(
            job_providers=[
                StaticProvider([Job(function=lint, name="ci.tools.lint", group="ci")])
            ]
        ),
    )
    adapter = CliAdapter()
    adapter(app)
    runner = CliRunner()

    dotted = runner.invoke(adapter.cli_command, ["ci.tools.lint"], prog_name="s")
    assert dotted.exit_code != 0
    assert "navigate groups with spaces: s ci tools.lint" in dotted.output
    printed = next(
        line.rsplit(": ", 1)[-1]
        for line in dotted.output.splitlines()
        if "navigate groups with spaces" in line
    )
    copied = runner.invoke(adapter.cli_command, shlex.split(printed)[1:], prog_name="s")
    assert copied.exit_code == 0, copied.output
    assert "LINT" in copied.output
    help_result = runner.invoke(
        adapter.cli_command, ["ci", "tools.lint", "--help"], prog_name="s"
    )
    assert help_result.exit_code == 0, help_result.output
    assert "Usage: s ci tools.lint [OPTIONS]" in help_result.output


def test_app_door_suggests_and_uses_full_grouped_path(tmp_path, monkeypatch, capsys):
    from click.testing import CliRunner

    from functualize._discovery.providers import Job, StaticProvider
    from functualize.app import FunctualizeApp, JobSources
    from functualize.app.adapters import CliAdapter

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    def inventory() -> None:
        print("INVENTORY")

    app = FunctualizeApp(
        name="sample",
        job_sources=JobSources(
            job_providers=[StaticProvider([Job(function=inventory, group="suite")])]
        ),
    )
    adapter = CliAdapter()
    adapter(app)
    runner = CliRunner()
    typo = runner.invoke(adapter._cli_group, ["inventori"], prog_name="sample")
    assert typo.exit_code != 0
    assert "sample suite inventory" in typo.output
    suggested = next(
        line.strip()
        for line in typo.output.splitlines()
        if line.strip() == "sample suite inventory"
    )
    copied = runner.invoke(
        adapter._cli_group,
        shlex.split(suggested)[1:],
        prog_name="sample",
    )
    assert copied.exit_code == 0, copied.output
    assert "INVENTORY" in copied.output
    help_result = runner.invoke(
        adapter._cli_group, ["suite", "inventory", "--help"], prog_name="sample"
    )
    assert help_result.exit_code == 0, help_result.output
    assert "Usage: sample suite inventory [OPTIONS]" in help_result.output
    run = runner.invoke(adapter._cli_group, ["suite", "inventory"], prog_name="sample")
    assert run.exit_code == 0, run.output
    assert "INVENTORY" in run.output

    from functualize.app.commands import JobCommandProvider

    leaf = JobCommandProvider(app).nodes()[0].children()[0]
    assert leaf.execute(["--help"]) == 0
    assert "Usage: sample suite inventory [OPTIONS]" in capsys.readouterr().out


@pytest.mark.parametrize("lazy", [False, True])
def test_app_door_child_group_hint_runs_as_printed(tmp_path, monkeypatch, lazy):
    """A child's namespace and its declared group are separate shell segments."""
    from click.testing import CliRunner

    from functualize.app import FunctualizeApp, JobSources
    from functualize.app.adapters import CliAdapter

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    child = tmp_path / "child"
    jobs = child / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "ops.py").write_text(
        'JOB_GROUP = "ops"\n\ndef tool() -> None:\n    print("CHILD-TOOL")\n'
    )

    app = FunctualizeApp(
        name="parent",
        job_sources=JobSources(children={"kid": str(child)}, lazy=lazy),
    )
    adapter = CliAdapter()
    adapter(app)
    runner = CliRunner()

    dotted = runner.invoke(adapter.cli_command, ["kid.ops.tool"], prog_name="parent")
    assert dotted.exit_code != 0
    assert "parent kid ops tool" in dotted.output
    printed = next(
        line.rsplit(": ", 1)[-1]
        for line in dotted.output.splitlines()
        if "navigate groups with spaces" in line
    )
    assert printed == "parent kid ops tool"
    copied = runner.invoke(
        adapter.cli_command, shlex.split(printed)[1:], prog_name="parent"
    )
    assert copied.exit_code == 0, copied.output
    assert "CHILD-TOOL" in copied.output

    # A job discovered after the Click tree was built takes the fallback wire.
    # That wire must name the invoked program, which may differ from app.name.
    child_group = adapter.cli_command.commands.pop("kid")
    fallback = runner.invoke(
        adapter.cli_command, ["kid.ops.tool"], prog_name="launcher"
    )
    assert fallback.exit_code != 0
    assert "launcher kid ops tool" in fallback.output
    adapter.cli_command.add_command(child_group, name="kid")


def _workflow_app(tmp_path, monkeypatch):
    """An app with a literal-dot leaf and a grouped workflow, both gated."""
    from pydantic import BaseModel

    from functualize._discovery.providers import Job, StaticProvider
    from functualize.app import FunctualizeApp, JobSources
    from functualize.workflow import END, Edge, Gate, Step, workflow

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".functualize").mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    class Ask(BaseModel):
        text: str

    def build() -> str:
        return "built"

    def finish() -> str:
        print("FINISHED")
        return "finished"

    def gated() -> str:
        return "done"

    flow = workflow(
        steps=[Step("build"), Gate(name="pause", awaits=Ask), Step("finish")],
        edges=[
            Edge("build", "pause"),
            Edge("pause", "finish"),
            Edge("finish", END),
        ],
    )
    return FunctualizeApp(
        name="sample",
        job_sources=JobSources(
            job_providers=[
                StaticProvider(
                    [
                        Job(function=build),
                        Job(function=finish),
                        Job(function=flow(gated), name="tools.release"),
                        Job(function=flow(gated), name="ship", group="ci"),
                    ]
                )
            ]
        ),
    )


def test_copied_resume_line_finishes_the_run_and_keeps_a_literal_dot_leaf(
    tmp_path, monkeypatch
):
    """The blocked message's resume line runs as printed on the app door."""
    from click.testing import CliRunner

    from functualize.app.adapters import CliAdapter
    from functualize.app.adapters.click_params import _program_name

    adapter = CliAdapter()
    adapter(_workflow_app(tmp_path, monkeypatch))
    runner = CliRunner()
    program = _program_name()
    for typed, path in (
        (["tools.release"], "tools.release"),
        (["ci", "ship"], "ci ship"),
    ):
        blocked = runner.invoke(adapter._cli_group, typed)
        assert blocked.exit_code == 5, blocked.output
        line = next(
            row.strip() for row in blocked.stderr.splitlines() if "--wf-resume" in row
        )
        assert line.startswith(f"{program} {path} --wf-resume "), line
        copied = shlex.split(line)[1:]
        copied[-1] = '{"text": "ok"}'
        resumed = runner.invoke(adapter._cli_group, copied)
        assert resumed.exit_code == 0, resumed.output
        assert "FINISHED" in resumed.output


def test_provenance_keeps_child_jobs_and_local_literal_dot_leaves():
    """`(local)` and child attribution survive without splitting identity."""
    from types import SimpleNamespace

    from functualize._cli.completions.provenance import (
        CompletionProvenanceClassifier,
    )
    from functualize._discovery.transforms import NamespaceTransform
    from functualize.types import JobDescriptor

    app = SimpleNamespace(child_projects=[SimpleNamespace(name="tools")])
    classifier = CompletionProvenanceClassifier(app)
    (mounted,) = NamespaceTransform("tools").transform_list(
        [JobDescriptor(name="lint", group=None)]
    )
    grouped = JobDescriptor(name="tools.run", group="tools")
    literal = JobDescriptor(name="pkg.lint", group=None)
    assert str(mounted.command_path) == "tools.lint"
    assert classifier.get_provenance(mounted).source_type == "child"
    assert classifier.get_provenance(mounted).display_label == "tools"
    assert classifier.get_provenance(grouped).source_type == "child"
    assert classifier.get_provenance(literal).source_type == "local"


def test_inline_handoff_hint_is_the_trie_path_and_literal_leaf_runs(
    tmp_path, monkeypatch, capsys
):
    from functualize._cli.inline_tui import _run_handoff
    from functualize._discovery.providers import Job, StaticProvider
    from functualize.app import FunctualizeApp, JobSources

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    def run() -> None:
        print("RUN")

    def lint() -> None:
        print("LINT")

    app = FunctualizeApp(
        name="sample",
        job_sources=JobSources(
            job_providers=[
                StaticProvider(
                    [
                        Job(function=run, group="deploy.web"),
                        Job(function=lint, name="tools.lint"),
                    ]
                )
            ]
        ),
    )
    # The token crosses two edges below `deploy`; the offered spelling is the
    # whole path from the root, not the token with its dots blanked out.
    _run_handoff(app, ["deploy", "web.run"])
    assert "e.g. `deploy web run`." in capsys.readouterr().err
    _run_handoff(app, ["tools.lint"])
    assert "LINT" in capsys.readouterr().out
