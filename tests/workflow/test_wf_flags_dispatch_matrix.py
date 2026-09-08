"""`--wf-*` is honoured on every dispatch mode, cold cache and warm.

**Why both.** The flags have two injection points — `create_job_click_command`
(cold, built from a live signature) and `make_lazy_command` (warm, built from
the discovery cache). Warm boot is *every invocation after the first*, so a
project's second run is a different code path from its first, always.

`contributor/reference/pitfalls.md` §23 records what that costs when only one
side is handled: a job that raised exited 0 in silence, a gate pause exited 0
instead of 5, and a refusal exited 0 instead of 3 — the whole exit-code table
held only on a project's very first run.

The mitigation here is structural — one `workflow_flags` module builds the
options *and* resolves them, and both constructors call it — but structure is a
claim until something checks it. This is the check.

The repo already demands this guardrail for state-addressing flags:
`main.py`'s own comment records that omitting them made `--scope-id` silently
ignored on a cold discovery cache.
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
    log("FIRST RAN")
    return "one"


@job
def last(log: Log) -> str:
    log("LAST RAN")
    return "two"


@job
def plain(log: Log) -> str:
    """A job with no workflow, so nothing to advance."""
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
    log("GROUPED FIRST RAN")
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

#: A workflow whose job name differs from its file stem, so the dispatcher's
#: cheap enumeration misses it and the invocation lands in UNKNOWN mode.
_UNKNOWN = """
from pydantic import BaseModel, Field

from functualize import workflow
from functualize.job import Log, job
from functualize.workflow import END, Edge, Gate, Step


class Ask3(BaseModel):
    text: str = Field(description="anything")


@job
def seed(log: Log) -> str:
    log("SEED RAN")
    return "one"


@workflow(
    steps=[Step(seed), Gate(name="pause3", awaits=Ask3)],
    edges=[Edge("seed", "pause3"), Edge("pause3", END)],
)
def odd_named_walk(log: Log) -> str:
    log("ODD BODY RAN")
    return "done"
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
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
    (jobs / "other.py").write_text(_UNKNOWN)
    return tmp_path


def _run(project: Path, surface: str, *args: str) -> subprocess.CompletedProcess[str]:
    argv = (
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args]
        if surface == "func"
        else ["uv", "run", "--project", str(PROJECT_ROOT), "python", "main.py", *args]
    )
    return subprocess.run(
        argv, capture_output=True, text=True, cwd=str(project), timeout=180
    )


def _scope_of(result: subprocess.CompletedProcess[str]) -> str:
    match = re.search(r"scope '([0-9a-f]+)'", result.stdout + result.stderr)
    assert match is not None, result.stdout + result.stderr
    return match.group(1)


#: (mode label, surface, argv prefix, the log line the body prints)
_MODES = [
    ("JOB", "func", ["walk"], "WALK BODY RAN"),
    ("GROUP", "func", ["flow", "grouped-walk"], "GROUPED BODY RAN"),
    ("UNKNOWN", "func", ["odd-named-walk"], "ODD BODY RAN"),
    ("EMBEDDED", "app", ["walk"], "WALK BODY RAN"),
]


@pytest.mark.slow
@pytest.mark.parametrize(("mode", "surface", "argv", "marker"), _MODES)
def test_wf_resume_advances_cold_and_warm(
    project: Path, mode: str, surface: str, argv: list[str], marker: str
) -> None:
    """AC-16, AC-20. The run must **replay**, not mint a new id.

    That is the exact regression `main.py`'s comment describes: a state-
    addressing flag silently ignored produces a brand-new scope and the real
    run stays blocked forever, with no error anywhere.
    """
    # Cold: no discovery cache yet.
    blocked = _run(project, surface, *argv)
    assert blocked.returncode == 5, blocked.stdout + blocked.stderr
    scope = _scope_of(blocked)

    # Warm: the first run wrote the cache, so this is the lazy path.
    resumed = _run(
        project, surface, *argv, "--wf-resume", scope, "--wf-input", '{"text": "hi"}'
    )
    blob = resumed.stdout + resumed.stderr
    assert "No such option" not in blob, blob
    assert resumed.returncode == 0, blob
    assert marker in blob, blob

    # And it replayed the *same* scope rather than starting another.
    status = _run(project, surface, *argv, "--wf-status")
    assert scope not in status.stdout, status.stdout + status.stderr


@pytest.mark.slow
@pytest.mark.parametrize(("mode", "surface", "argv", "marker"), _MODES)
def test_wf_status_exits_without_running_the_job(
    project: Path, mode: str, surface: str, argv: list[str], marker: str
) -> None:
    """AC-25. It cannot be an ordinary kwarg consumed after the engine call."""
    result = _run(project, surface, *argv, "--wf-status")

    assert result.returncode == 0, result.stdout + result.stderr
    blob = result.stdout + result.stderr
    assert marker not in blob, blob
    assert "RAN" not in blob, blob


@pytest.mark.slow
class TestTheFlagsAreScopedToWorkflows:
    """AC-21."""

    def test_a_plain_job_carries_no_wf_flags(self, project: Path) -> None:
        cold = _run(project, "func", "plain", "--help")
        assert "--wf-resume" not in cold.stdout, cold.stdout

    def test_a_plain_job_carries_none_warm_either(self, project: Path) -> None:
        """The warm gate reads `descriptor.workflow` from the cache, a
        different signal from the cold path's live declaration."""
        _run(project, "func", "plain")  # populate the cache
        warm = _run(project, "func", "plain", "--help")
        assert "--wf-resume" not in warm.stdout, warm.stdout

    def test_a_workflow_job_carries_them_cold(self, project: Path) -> None:
        cold = _run(project, "func", "walk", "--help")
        for flag in ("--wf-resume", "--wf-status", "--wf-show", "--wf-run-id"):
            assert flag in cold.stdout, cold.stdout

    def test_a_workflow_job_carries_them_warm(self, project: Path) -> None:
        _run(project, "func", "walk")
        warm = _run(project, "func", "walk", "--help")
        for flag in ("--wf-resume", "--wf-status", "--wf-show", "--wf-run-id"):
            assert flag in warm.stdout, warm.stdout


@pytest.mark.slow
class TestAmbiguityAndUnknownIds:
    def test_an_unknown_id_errors_and_creates_nothing(self, project: Path) -> None:
        """AC-18. `--scope-id` silently started a fresh run under whatever was
        typed, so a typo produced a phantom scope the caller could not find."""
        result = _run(project, "func", "walk", "--wf-resume", "deadbeefdeadbeef")

        assert result.returncode != 0
        blob = result.stdout + result.stderr
        assert "deadbeefdeadbeef" in blob
        assert "WALK BODY RAN" not in blob

        status = _run(project, "func", "walk", "--wf-status")
        assert "deadbeefdeadbeef" not in status.stdout

    def test_a_bare_resume_with_no_scope_names_the_survey_flag(
        self, project: Path
    ) -> None:
        """AC-17, zero candidates."""
        result = _run(project, "func", "walk", "--wf-resume")

        assert result.returncode != 0
        assert "--wf-status" in result.stdout + result.stderr

    def test_a_bare_resume_with_several_lists_them(self, project: Path) -> None:
        """AC-17, several. Never "newest wins" — `blocked_at` resets on every
        re-block, so recency is not computable even if it were wanted."""
        first = _scope_of(_run(project, "func", "walk"))
        _run(project, "func", "walk", "--wf-run-id", "chosen-two")
        second = "chosen-two"

        result = _run(project, "func", "walk", "--wf-resume")

        assert result.returncode == 2
        blob = result.stdout + result.stderr
        assert first in blob and second in blob

    def test_a_bare_resume_with_exactly_one_uses_it(self, project: Path) -> None:
        """AC-17, one."""
        _run(project, "func", "walk")

        result = _run(project, "func", "walk", "--wf-resume", "--wf-input", '{"text": "x"}')

        assert result.returncode == 0, result.stdout + result.stderr
        assert "WALK BODY RAN" in result.stdout + result.stderr


@pytest.mark.slow
class TestRunId:
    """AC-19. `--wf-run-id` may mint a scope; `--wf-resume` may not. That split
    *is* the phantom-run fix."""

    def test_it_starts_under_the_chosen_id(self, project: Path) -> None:
        result = _run(project, "func", "walk", "--wf-run-id", "my-chosen-id")

        assert result.returncode == 5
        status = _run(project, "func", "walk", "--wf-status")
        assert "my-chosen-id" in status.stdout

    def test_starting_twice_under_one_id_is_idempotent(self, project: Path) -> None:
        """The capability `--scope-id` had only as a side effect of its double
        duty, kept deliberately here."""
        _run(project, "func", "walk", "--wf-run-id", "idem")
        again = _run(project, "func", "walk", "--wf-run-id", "idem")

        assert again.returncode == 5
        # One scope, not two.
        status = _run(project, "func", "walk", "--wf-status")
        assert status.stdout.count("idem") == 1, status.stdout

    def test_it_cannot_be_combined_with_resume(self, project: Path) -> None:
        result = _run(
            project, "func", "walk", "--wf-run-id", "a", "--wf-resume", "b"
        )
        assert result.returncode == 2
        assert "Pass one" in result.stdout + result.stderr


@pytest.mark.slow
class TestWfShow:
    def test_it_renders_the_full_projection(self, project: Path) -> None:
        """AC-25. Same output as `builtin workflow show` — the flag saves
        naming the workflow, it does not reduce the output."""
        scope = _scope_of(_run(project, "func", "walk"))

        result = _run(project, "func", "walk", "--wf-show", scope)

        assert result.returncode == 0, result.stdout + result.stderr
        for key in ('"steps"', '"edges"', '"state"', '"results"', '"pending_gates"'):
            assert key in result.stdout, result.stdout

    def test_it_does_not_run_the_job(self, project: Path) -> None:
        scope = _scope_of(_run(project, "func", "walk"))
        result = _run(project, "func", "walk", "--wf-show", scope)
        assert "WALK BODY RAN" not in result.stdout + result.stderr


@pytest.mark.slow
class TestInputRequiresResume:
    def test_input_without_resume_is_a_usage_error(self, project: Path) -> None:
        """It answers the gate the walk is about to pass; on its own it would
        silently do nothing on a fresh run."""
        result = _run(project, "func", "walk", "--wf-input", '{"text": "x"}')
        assert result.returncode == 2

    def test_gate_without_input_is_a_usage_error(self, project: Path) -> None:
        result = _run(project, "func", "walk", "--wf-gate", "pause")
        assert result.returncode == 2

    def test_retry_epilogue_without_resume_is_a_usage_error(
        self, project: Path
    ) -> None:
        result = _run(project, "func", "walk", "--wf-retry-epilogue")
        assert result.returncode == 2
