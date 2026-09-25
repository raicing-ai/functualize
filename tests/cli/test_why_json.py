"""`func builtin why --json` exit codes: answered, not up to date.

The exit code answers *"was the question answered about a runnable job?"*,
not *"is the job up to date?"*. `why` is the command the shipped docs and
skill point at when a job does not appear to run, and the skill's §5 has an
agent invoke it verbatim — so `func builtin why <job> && …` in CI or a health
check must read a healthy job as success. The run/not-run distinction is in
the payload (`will_run`, `state`) and the prose headline, never the exit code.

The regression this file guards against had two halves, both found by the
Discovery QA rehearsal on the published 0.4.0 artifact:

- a job with no `@job` declaration — the healthy default — was routed
  through `explain_verdicts`' *error* return, so the payload said
  `state: "unknown"` and the process exited 2, the usage-error code, while
  the prose said WOULD RUN;
- a declared stale job exited 4 (`ExitCode.STALE`), a number the documented
  table reserves for a `--check` stale-check *failure* and that the shipped
  skill's exit-code table says no current command produces.

The last test is the one that matters most. `why` exists to answer the same
question the run answers, and the previous cycle's worst defect was `why`
contradicting the run that had just happened. A second reader of that question
— a `--json` that re-derived the verdicts — would reopen it, so both forms come
off one set of verdicts and this test holds them to it, cold and warm, in
separate processes.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("y", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""

_JOBS = """
from pathlib import Path

from functualize.job import Fingerprint, Guards, Precondition, job

JOB_GROUP = "y"


@job(group=JOB_GROUP, cache=Fingerprint(sources=["src/*.py"]))
def cached() -> None:
    print("RAN cached")


@job(
    group=JOB_GROUP,
    guards=Guards(preconditions=[Precondition("test -f missing.txt", msg="no world")]),
)
def gated() -> None:
    print("RAN gated")


def plain() -> None:
    print("RAN plain")
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\nroot = true\n'
    )
    (tmp_path / "main.py").write_text(_MAIN)
    (tmp_path / "config.base.toml").write_text('[general]\napp_name = "y"\n')
    (tmp_path / ".functualize").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("print(1)\n")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "y.py").write_text(_JOBS)
    return tmp_path


def _run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "python", "main.py", *args],
        capture_output=True,
        text=True,
        cwd=str(project),
        timeout=120,
    )


def _why(project: Path, job: str) -> tuple[dict, int]:
    result = _run(project, "builtin", "why", job, "--json")
    return json.loads(result.stdout), result.returncode


def test_a_stale_job_exits_zero(project: Path) -> None:
    """A job that WOULD RUN is the healthy case, not a stale-check failure.

    `ExitCode.STALE` (4) is documented as the `--check` stale-check failure and
    the shipped skill's table says no command produces it; a diagnostic that
    answered the question successfully must not borrow it. The stale/fresh
    distinction a script needs is `will_run` in this payload.
    """
    payload, code = _why(project, "y.cached")

    assert payload["will_run"] is True
    assert payload["state"] == "run"
    assert code == 0


def test_a_job_with_no_declaration_exits_zero(project: Path) -> None:
    """The rehearsal defect: `why` on a plain, healthy job exited 2.

    A function with no `@job` declaration is the default kind of job, and the
    answer to "would it run?" is yes — but it was returned through
    `explain_verdicts`' *error* channel, so the payload claimed
    `state: "unknown"` while saying `will_run: true`, and the process exited
    with the usage-error code. `func builtin why <job> && …` in a health check
    stopped the chain on a healthy job.
    """
    payload, code = _why(project, "y.plain")

    assert payload["state"] == "run"
    assert payload["will_run"] is True
    assert "no @job declaration" in payload["reason"]
    assert code == 0

    prose = _run(project, "builtin", "why", "y.plain").stdout
    assert "WOULD RUN" in prose, prose


def test_a_fresh_job_exits_zero(project: Path) -> None:
    """The would-not-run half of the contract, measured rather than implied."""
    assert "RAN cached" in _run(project, "y", "cached").stdout

    payload, code = _why(project, "y.cached")

    assert payload["will_run"] is False
    assert payload["state"] == "skip_fresh"
    assert code == 0


def test_a_refusal_exits_three(project: Path) -> None:
    """The run table's number, not a second vocabulary for the same fact.

    A refusal is 3 whether you ask about it or trigger it. Inventing a
    different code for "would refuse" is how two tables drift.
    """
    payload, code = _why(project, "y.gated")

    assert payload["state"] in ("error", "refused")
    assert code == 3


def test_an_unresolvable_job_exits_two(project: Path) -> None:
    payload, code = _why(project, "y.nosuchjob")

    assert code == 2
    assert payload["job"] == "y.nosuchjob"


def test_the_payload_carries_its_own_exit_code(project: Path) -> None:
    """So a caller that captured stdout need not also capture `$?`."""
    payload, code = _why(project, "y.cached")

    assert payload["exit_code"] == code


def test_the_json_names_the_state_by_its_wire_value(project: Path) -> None:
    """A new `GuardState` member must be a new string, never a renamed one."""
    payload, _ = _why(project, "y.cached")

    assert payload["state"] in {
        "run",
        "skip_neutral",
        "skip_satisfied",
        "skip_fresh",
        "blocked",
        "error",
        "refused",
    }
    assert isinstance(payload["checks"], list)
    assert isinstance(payload["deps"], list)


def test_json_and_prose_agree_cold_and_warm(project: Path) -> None:
    """The defect this whole surface has to avoid reopening.

    `func builtin why` contradicting the run that just happened was the
    previous cycle's D3/D4. A `--json` that re-derived the verdicts would be a
    second reader of one question — the exact shape that produced it. Both
    forms come off `explain_verdicts`, and this holds them to it across a cold
    and a warm boot, in separate processes, because in one process a live value
    masks a failed record read entirely.
    """
    for _ in range(2):
        cold_payload, _ = _why(project, "y.cached")
        prose = _run(project, "builtin", "why", "y.cached").stdout

        if cold_payload["will_run"]:
            assert "WOULD RUN" in prose, prose
        else:
            assert "SKIP" in prose, prose

        # And the run itself agrees with what `why` predicted.
        ran = "RAN cached" in _run(project, "y", "cached").stdout
        assert ran == cold_payload["will_run"], (cold_payload, prose)
