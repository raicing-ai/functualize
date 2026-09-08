"""A gated `@workflow` is addressed and advanced on both surfaces.

The original defect: `--scope-id` was a **pre-command global of the bare `func`
CLI**, and `_cli/main.py` was the only caller that threaded it. The builder
every `FunctualizeApp` entry point uses never passed it and exposed no
equivalent — so on an embedded app a gated `@workflow` blocked at exit 5,
accepted input, and then had **no way to be run with that scope id**. Every
later run opened a fresh scope and blocked again, forever.

`--scope-id` is now **removed in both spellings** and replaced by the
post-command `--wf-resume`, which does strictly more: it may omit the id when
unambiguous, it can answer the gate in the same command, and — the defect fix —
an unknown id **errors** rather than silently starting a new run under it.

Post-command because that is where a reader looks: the audit that found the
original bug got the pre-command position wrong twice before reading
`dispatch.py`.

Scoped to workflow-declaring jobs, so the flags stay off every ordinary job's
`--help` and cannot collide with a config field of the same name.
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
        "answer",
        scope,
        "pause",
        "--input",
        '{"text": "hi"}',
    )
    assert deposited.returncode == 0, deposited.stdout + deposited.stderr

    resumed = _run(project, surface, "walk", "--wf-resume", scope)
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
    assert "--wf-resume" in err, err
    # The flag is spelled after the job name, which is where it works.
    assert re.search(r"\bwalk --wf-resume [0-9a-f]+", err), err
    program = "func" if surface == "func" else "main.py"
    assert program in err, err
    # It names the command that *finishes* the run, not one that starts
    # another attempt at it. With no pre-command flag to fall back on, "re-run
    # the command you remember" is gone, so exit 5 has to carry the whole
    # continuation.
    assert "--wf-input" in err, err


@pytest.mark.parametrize("surface", SURFACES)
def test_an_ordinary_job_has_no_workflow_flags(surface: str, tmp_path: Path) -> None:
    """The flags are scoped to jobs that declare a workflow.

    A job with nothing to advance should not advertise advancing, and a config
    field must not collide with a flag every command carries.
    """
    project = _project(tmp_path)

    helped = _run(project, surface, "plain", "--help")
    options = helped.stdout.split("Options:", 1)[-1]
    assert "--wf-resume" not in options, helped.stdout

    rejected = _run(project, surface, "plain", "--wf-resume", "abc")
    assert rejected.returncode != 0
    assert "No such option" in rejected.stdout + rejected.stderr


def test_the_pre_command_flag_is_gone_and_fails_loudly(tmp_path: Path) -> None:
    """AC-22. `func --scope-id X walk` no longer exists, and cannot run the
    wrong thing.

    No deprecation shim. `detect_mode`'s scan skips boolean, always-value,
    optional-value, `--opt=value` and short options, so a bare `--scope-id`
    matches none of them and falls through: **the flag itself becomes the first
    positional** and its value is never examined. The result is confusing but
    loud, non-zero, and incapable of mistaking the stray id for a job name.

    A refusal branch would give a better message. Its only justification is
    courtesy to muscle memory, and the recognition set it would need exists so
    the scan can skip a flag *and its value* while hunting the first positional
    — which only matters for the invocation that is now invalid.
    """
    project = _project(tmp_path)

    rejected = _run(project, "func", "--scope-id", "abc", "walk")

    assert rejected.returncode != 0
    blob = rejected.stdout + rejected.stderr
    assert "scope-id" in blob, blob
    # The job did not run, and the stray id was never taken for a job name.
    assert "WALK BODY RAN" not in blob, blob


def test_the_per_command_flag_is_gone_too(tmp_path: Path) -> None:
    """AC-22, the second spelling. Both, not just the global."""
    project = _project(tmp_path)

    rejected = _run(project, "func", "walk", "--scope-id", "abc")

    assert rejected.returncode != 0
    assert "No such option" in rejected.stdout + rejected.stderr


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

    Found by running a realistic pipeline end to end, not by a test — every
    workflow job in the suite happened to be ungrouped. That is the whole
    argument for keeping one around as an integration check, which is what
    `examples/standalone/composition_lab/` (its `demo.sh`, and
    `tests/test_composition_lab_e2e.py`) now is: `lab.release` is a grouped
    workflow job, gated, run on both surfaces.
    """
    project = _project(tmp_path)

    blocked = _run(project, surface, "flow", "grouped-walk")
    assert blocked.returncode == 5, blocked.stdout + blocked.stderr
    err = blocked.stderr

    assert "flow.grouped-walk --wf-resume" not in err, (
        "the message printed the job address, which is not a runnable command"
    )
    assert re.search(r"flow grouped-walk --wf-resume [0-9a-f]+", err), err

    # And the command it printed actually runs.
    match = re.search(r"--wf-resume ([0-9a-f]+)", err)
    assert match is not None
    resumed = _run(
        project, surface, "flow", "grouped-walk", "--wf-resume", match.group(1)
    )
    assert "No such command" not in resumed.stdout + resumed.stderr
    assert "No such option" not in resumed.stdout + resumed.stderr


def test_the_flag_is_declared_nowhere_in_the_source() -> None:
    """AC-23. A negative about the whole tree, so it is answered by searching
    it rather than by reading a file.

    Counts **declarations**, not prose: several comments name the removed flag
    to explain why it went, and a check that forbids explaining a removal is a
    check that rewards deleting the explanation.
    """
    import subprocess

    src = PROJECT_ROOT / "src" / "functualize"
    result = subprocess.run(
        ["grep", "-rho", '"--scope-id"', str(src)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.strip() == "", (
        f"--scope-id is still declared as a click option:\n{result.stdout}"
    )
