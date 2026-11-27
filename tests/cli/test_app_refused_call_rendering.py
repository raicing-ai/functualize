"""An app script gives discovery refusals before parsing a lazy job's arguments."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REASON = (
    "No provider is registered for Widget without a qualifier. "
    "Register one from a plugin, or declare a type the caller supplies."
)


@pytest.fixture
def app_script(tmp_path: Path) -> Path:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "refused.py").write_text(
        "class Widget: pass\n"
        "def refused(p: Widget):\n"
        "    raise AssertionError('refused job ran')\n"
    )
    (jobs / "refused_workflow.py").write_text(
        "from functualize.workflow import END, Edge, Step, workflow\n"
        "class Widget: pass\n"
        "def stage(): pass\n"
        "@workflow(steps=[Step(stage)], edges=[Edge(source='stage', target=END)])\n"
        "def refused_workflow(p: Widget):\n"
        "    raise AssertionError('refused workflow ran')\n"
    )
    (jobs / "grouped.py").write_text(
        "JOB_GROUP = 'team'\n"
        "class Widget: pass\n"
        "def refused_group(p: Widget):\n"
        "    raise AssertionError('refused group job ran')\n"
    )
    (tmp_path / "my_app.py").write_text(
        "import sys\n"
        "from functualize.app import FunctualizeApp, JobSources\n"
        "from functualize.app.adapters import CliAdapter\n"
        "import functualize.app.adapters.cli as cli\n"
        "original = cli.make_lazy_command\n"
        "def marked(*args, **kwargs):\n"
        "    print('LAZY_BUILDER ' + args[0].name, file=sys.stderr)\n"
        "    return original(*args, **kwargs)\n"
        "cli.make_lazy_command = marked\n"
        "app = FunctualizeApp('probe', job_sources=JobSources("
        "directories=['jobs'], lazy=True))\n"
        "adapter = CliAdapter(); adapter(app); adapter.run()\n"
    )
    return tmp_path


def _run(root: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(
        os.environ,
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / "config"),
        XDG_DATA_HOME=str(home / "data"),
        XDG_CACHE_HOME=str(home / "cache"),
    )
    return subprocess.run(
        [sys.executable, "my_app.py", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("command", "args", "job_name"),
    [
        (("refused",), (), "refused"),
        (("refused",), ("--p", "x"), "refused"),
        (("refused",), ("x",), "refused"),
        (("refused-workflow",), ("--wf-status",), "refused-workflow"),
        (("team", "refused-group"), ("--group-option", "x"), "team.refused-group"),
    ],
    ids=["bare", "unknown-option", "extra-positional", "workflow", "group"],
)
def test_refused_app_job_ignores_arguments_before_parsing(
    app_script: Path,
    tmp_path: Path,
    command: tuple[str, ...],
    args: tuple[str, ...],
    job_name: str,
) -> None:
    expected = (
        f"Error: job {job_name!r} cannot run: parameter 'p' was refused "
        f"at discovery. {_REASON}"
    )
    for boot in ("cold", "warm"):
        home = tmp_path / f"{boot}-{job_name.replace('.', '-')}-{len(args)}"
        home.mkdir()
        if boot == "warm":
            primer = _run(app_script, home, *command, "--help")
            assert primer.returncode == 0, primer.stderr
        result = _run(app_script, home, *command, *args)
        errors = [
            line for line in result.stderr.splitlines() if line.startswith("Error:")
        ]
        assert result.returncode == 2, result.stderr
        assert errors == [expected], result.stderr
        assert "No such option" not in result.stderr
        assert "Traceback" not in result.stderr
        assert (f"LAZY_BUILDER {job_name}" in result.stderr) is (boot == "warm")


@pytest.mark.parametrize("boot", ["cold", "warm"])
def test_refused_app_job_help_is_available(
    app_script: Path, tmp_path: Path, boot: str
) -> None:
    home = tmp_path / f"help-{boot}"
    home.mkdir()
    if boot == "warm":
        assert _run(app_script, home, "refused", "--help").returncode == 0
    result = _run(app_script, home, "refused", "--help")
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout
    assert "Error:" not in result.stderr
