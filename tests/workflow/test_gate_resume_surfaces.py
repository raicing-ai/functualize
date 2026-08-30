"""A gated `@workflow` resumes on both surfaces (D-5).

`--scope-id` was a **pre-command global of the bare `func` CLI**, and
`_cli/main.py` was the only caller that threaded it into
`create_job_click_command(..., workflow_scope_id=...)`. The builder every
`FunctualizeApp` entry point uses never passed it and exposed no equivalent.

So on an embedded app — which is what the acceptance fixture, the reference
workspace and every example use — a `@workflow` with a `Gate`:

* blocked on the first run, exit 5 (correct);
* accepted input via `builtin workflow resume` (correct);
* and then had **no way to be run with that scope id**. Every later run opened a
  fresh scope and blocked again, forever. The deposited input was never read.

The flag is now a **post-command** option on job commands that declare a
workflow, on both surfaces. Post-command because that is where a reader looks:
the audit that found this got the pre-command position wrong twice before
reading `dispatch.py`. `func --scope-id X walk` still works.

Scoped to workflow-declaring jobs, so it stays off every ordinary job's `--help`
and cannot collide with a config field named `scope_id`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("w", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""

_JOBS = '''
from pydantic import BaseModel, Field

from functualize import workflow
from functualize.job import Log, job
from functualize.workflow import END, Edge, Gate, Step


class Ask(BaseModel):
    text: str = Field(description="anything")


@job
def first(log: Log) -> str:
    log("first ran")
    return "one"


@job
def last(log: Log) -> str:
    log("LAST RAN")
    return "two"


@job
def plain(log: Log) -> str:
    """A job with no workflow, so nothing to resume."""
    log("PLAIN RAN")
    return "three"


@workflow(
    steps=[Step(first), Gate(name="pause", awaits=Ask), Step(last)],
    edges=[Edge("first", "pause"), Edge("pause", "last"), Edge("last", END)],
)
def walk(log: Log) -> str:
    log("WALK BODY RAN")
    return "done"

'''


# A *grouped* workflow job, in its own module so the module-level `JOB_GROUP`
# does not regroup the ungrouped jobs above. Its whole point is that a grouped
# job is addressed `flow.grouped-walk` and invoked `flow grouped-walk`.
_GROUPED = """
from pydantic import BaseModel, Field

from functualize import workflow
from functualize.job import Log, job
from functualize.workflow import END, Edge, Gate, Step

JOB_GROUP = "flow"


class Ask2(BaseModel):
    text: str = Field(description="anything")


@job(group=JOB_GROUP)
def step_one(log: Log) -> str:
    log("grouped first ran")
    return "one"


@workflow(
    steps=[Step(step_one), Gate(name="pause2", awaits=Ask2)],
    edges=[Edge("flow.step-one", "pause2"), Edge("pause2", END)],
)
@job(group=JOB_GROUP)
def grouped_walk(log: Log) -> str:
    log("GROUPED BODY RAN")
    return "done"
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\nroot = true\n'
    )
    (tmp_path / "main.py").write_text(_MAIN)
    (tmp_path / "config.base.toml").write_text('[general]\napp_name = "w"\n')
    (tmp_path / ".functualize").mkdir()
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "w.py").write_text(_JOBS)
    (jobs / "g.py").write_text(_GROUPED)
    return tmp_path


def _run(project: Path, surface: str, *args: str) -> subprocess.CompletedProcess[str]:
    argv = (
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args]
        if surface == "func"
        else ["uv", "run", "--project", str(PROJECT_ROOT), "python", "main.py", *args]
    )
    return subprocess.run(
        argv, capture_output=True, text=True, cwd=str(project), timeout=120
    )


SURFACES = ["func", "app"]


@pytest.mark.parametrize("surface", SURFACES)
def test_block_deposit_resume_completes(surface: str, tmp_path: Path) -> None:
    """The whole flow, end to end, on the surface under test.

    The third step is the one that did not exist. Asserting only that the
    deposit is *accepted* — which it always was — is how this stayed open: the
    input went in and nothing could ever read it back out.
    """
    project = _project(tmp_path)

    blocked = _run(project, surface, "walk")
    assert blocked.returncode == 5, blocked.stdout + blocked.stderr
    match = re.search(r"scope '([0-9a-f]+)'", blocked.stdout + blocked.stderr)
    assert match is not None, blocked.stdout + blocked.stderr
    scope = match.group(1)

    deposited = _run(
        project,
        surface,
        "builtin",
        "workflow",
        "resume",
        scope,
        "pause",
        "--input",
        '{"text": "hi"}',
    )
    assert deposited.returncode == 0, deposited.stdout + deposited.stderr

    resumed = _run(project, surface, "walk", "--scope-id", scope)
    blob = resumed.stdout + resumed.stderr
    assert "No such option" not in blob, blob
    assert resumed.returncode == 0, blob
    assert "WALK BODY RAN" in blob, blob


@pytest.mark.parametrize("surface", SURFACES)
def test_the_blocked_message_names_a_runnable_resume_command(
    surface: str, tmp_path: Path
) -> None:
    """At **default** log level, and for the surface that printed it.

    The message used to say "Re-run with --log-level DEBUG for the exact resume
    command" — one indirection too many for the line a CI log carries — and the
    command it then printed said `func …` even when the caller was `./main.py`,
    which sends the reader to a CLI that does not know about their project.
    """
    project = _project(tmp_path)

    blocked = _run(project, surface, "walk")
    err = blocked.stderr

    assert "--log-level DEBUG" not in err, err
    assert "--scope-id" in err, err
    # The flag is spelled after the job name, which is where it now works.
    assert re.search(r"\bwalk --scope-id [0-9a-f]+", err), err
    program = "func" if surface == "func" else "main.py"
    assert program in err, err


@pytest.mark.parametrize("surface", SURFACES)
def test_an_ordinary_job_has_no_scope_id_flag(surface: str, tmp_path: Path) -> None:
    """The flag is scoped to jobs that declare a workflow.

    A job with nothing to resume should not advertise resumption, and a config
    field named `scope_id` must not collide with a flag every command carries.
    """
    project = _project(tmp_path)

    helped = _run(project, surface, "plain", "--help")
    options = helped.stdout.split("Options:", 1)[-1]
    assert "--scope-id" not in options, helped.stdout

    rejected = _run(project, surface, "plain", "--scope-id", "abc")
    assert rejected.returncode != 0
    assert "No such option" in rejected.stdout + rejected.stderr


def test_the_pre_command_flag_still_works(tmp_path: Path) -> None:
    """`func --scope-id X walk` is unchanged.

    It has been the documented form since gates existed; the post-command
    option is additive, and when both are given the per-command value wins.
    """
    project = _project(tmp_path)

    blocked = _run(project, "func", "walk")
    match = re.search(r"scope '([0-9a-f]+)'", blocked.stdout + blocked.stderr)
    assert match is not None
    scope = match.group(1)

    _run(
        project,
        "func",
        "builtin",
        "workflow",
        "resume",
        scope,
        "pause",
        "--input",
        '{"text": "hi"}',
    )

    resumed = _run(project, "func", "--scope-id", scope, "walk")
    blob = resumed.stdout + resumed.stderr
    assert resumed.returncode == 0, blob
    assert "WALK BODY RAN" in blob, blob


@pytest.mark.parametrize("surface", SURFACES)
def test_the_blocked_message_names_a_command_path_not_a_job_address(
    surface: str, tmp_path: Path
) -> None:
    """A grouped job is *addressed* dotted and *invoked* with spaces.

    `audit.audit-run` is the job's name; `audit audit-run` is how you run it —
    its group is a command group, and neither surface has a top-level command
    with a dot in it. The first version of this message printed the address, so
    following it answered `No such command 'audit.audit-run'`, which is worse
    than printing nothing: it makes the resume feature itself look broken.

    Found by running `pipeline-readiness/idiomatic-audit/demo.sh`, not by a
    test — every workflow job in the suite happened to be ungrouped. That is
    the whole argument for keeping a realistic pipeline around as an
    integration check.
    """
    project = _project(tmp_path)

    blocked = _run(project, surface, "flow", "grouped-walk")
    assert blocked.returncode == 5, blocked.stdout + blocked.stderr
    err = blocked.stderr

    assert "flow.grouped-walk --scope-id" not in err, (
        "the message printed the job address, which is not a runnable command"
    )
    assert re.search(r"flow grouped-walk --scope-id [0-9a-f]+", err), err

    # And the command it printed actually runs.
    match = re.search(r"--scope-id ([0-9a-f]+)", err)
    assert match is not None
    resumed = _run(
        project, surface, "flow", "grouped-walk", "--scope-id", match.group(1)
    )
    assert "No such command" not in resumed.stdout + resumed.stderr
    assert "No such option" not in resumed.stdout + resumed.stderr
