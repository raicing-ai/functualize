"""PROPOSED — one job, two surfaces, two boots, one resolved config.

**Not wired into the suite.** Drop into `tests/config/` to adopt.

The existing cross-surface harness (`tests/config/test_secret_surface_parity.py`)
states the right rule — *"Every surface that reports what a job's config will be
must agree with what the job actually receives"* — and then drives only
`sys.argv = ["func"] + args`, because that is what `tests/conftest.py::cli_run`
does. `tests/group_options/test_adapter_entry_point_parity.py` already found and
named the consequence for group flags:

    "Nothing caught it because 'CLI parity' was six probes over one CLI.
     The adapter is a *second* CLI"

…and covers exactly one axis of it (mid-path flag parsing, cold only). This
module crosses the two axes that matter for config: **surface** (bare `func`
vs. `FunctualizeApp` + `CliAdapter`) and **boot** (cold vs. warm).

Subprocesses, not `CliRunner`: the defect lives in which *builder* constructs
the command, and that is decided by whether a discovery cache exists on disk.
An in-process runner that shares a warmed registry cannot see it.

Expected today: the `app`/`warm` cells FAIL for both jobs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_APP = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("parity", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()
adapter(app)
adapter.run()
"""

_JOBS = """
from pydantic import BaseModel, Field
from functualize.job import Log, job

JOB_GROUP = "demo"


class OptionalCfg(BaseModel):
    title: str = Field(default="DEFAULT")


class RequiredCfg(BaseModel):
    token: str


@job(group=JOB_GROUP)
def optional_field(log: Log, config: OptionalCfg) -> None:
    log(f"RESULT {config.title}")


@job(group=JOB_GROUP)
def required_field(log: Log, config: RequiredCfg) -> None:
    log(f"RESULT {config.token}")
"""

_CONFIG = """
[general]
app_name = "parity"

[demo.optional-field]
title = "FROM FILE"

[demo.required-field]
token = "FROM FILE"
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\nroot = true\n'
    )
    (tmp_path / "config.base.toml").write_text(_CONFIG)
    (tmp_path / ".functualize").mkdir()
    (tmp_path / "app.py").write_text(_APP)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "d.py").write_text(_JOBS)
    return tmp_path


def _invoke(surface: str, project: Path, command: str) -> str:
    argv = (
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", "demo", command]
        if surface == "func"
        else [
            "uv",
            "run",
            "--project",
            str(PROJECT_ROOT),
            "python",
            "app.py",
            "demo",
            command,
        ]
    )
    proc = subprocess.run(
        argv, cwd=project, capture_output=True, text=True, timeout=120
    )
    blob = proc.stdout + proc.stderr
    for line in blob.splitlines():
        if "RESULT " in line:
            return line.split("RESULT ", 1)[1].strip()
    return f"<exit {proc.returncode}: {blob.strip().splitlines()[-1] if blob.strip() else 'no output'}>"


@pytest.mark.parametrize("command", ["optional-field", "required-field"])
@pytest.mark.parametrize("surface", ["func", "app"])
def test_config_file_value_survives_both_boots(
    surface: str, command: str, project: Path
) -> None:
    """The second invocation must resolve config exactly like the first.

    Sabotage that fails this: revert `build_click_params_from_fields` to
    `default=field.default`. Only the `app`/warm cells move, which is the
    evidence that this test exercises the descriptor-built command path and
    not merely the same call twice.
    """
    cold = _invoke(surface, project, command)
    warm = _invoke(surface, project, command)

    assert cold == "FROM FILE", f"{surface}/cold resolved {cold!r}"
    assert warm == cold, (
        f"{surface}: cold resolved {cold!r} but warm resolved {warm!r} — "
        f"the two command builders disagree about this field"
    )
