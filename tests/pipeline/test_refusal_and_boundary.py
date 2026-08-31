"""A stage cannot report clean having verified nothing (R3), and warm agrees
with cold about what a run's exit code is.

Three defects meet here, and each one alone hides the next:

1. **The false clean.** A checksum run over an *empty* source map compares
   nothing and finds nothing changed, so a job declaring
   ``Fingerprint(sources=["absent/*.json"])`` answered "up to date — 0 sources
   unchanged" and exited 0. A stage certifying success having looked at
   nothing at all.

2. **The missing output.** ``checksum`` never consulted ``generates``, so a job
   whose inputs were unchanged reported fresh with its promised artifact
   deleted. ``timestamp`` has always forced a run in that case; the two methods
   simply disagreed.

3. **The warm boundary.** The lazy (warm-boot) command wrapper returned its
   ``JobResult`` and inspected nothing, so on every invocation after the first,
   a job that raised exited **0** in silence — as did a gate pause and a
   refusal. The exit-code table is a contract with scripts and agents; it held
   only on a project's very first run.

Every test here therefore runs the same job **twice**: once cold, once warm. A
test that runs a project only once cannot see (3) at all, and (3) is what made
(1) invisible from the command line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from functualize._types.enums import RunStatus
from functualize._types.exit_codes import ExitCode, exit_code_for_status

PROJECT_ROOT = Path(__file__).parent.parent.parent

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("r", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""


def _project(tmp_path: Path, jobs_source: str) -> Path:
    (tmp_path / "main.py").write_text(_MAIN)
    (tmp_path / "config.base.toml").write_text('[general]\napp_name = "r"\n')
    (tmp_path / ".functualize").mkdir()
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "r.py").write_text(jobs_source)
    return tmp_path


def _run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(PROJECT_ROOT),
            "python",
            "main.py",
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=str(project),
        timeout=120,
    )


class TestStatusContract:
    def test_refused_is_its_own_terminal_status(self) -> None:
        assert not RunStatus.REFUSED.ran
        assert not RunStatus.REFUSED.resumable

    def test_refused_exits_three(self) -> None:
        """3 was pinned in the exit table from the start, reachable only from
        `requires_tty`. Unmapped statuses fall back to 1, so without the entry
        a refusal was indistinguishable from a job that ran and threw."""
        assert exit_code_for_status(RunStatus.REFUSED) == ExitCode.REFUSED == 3

    def test_refused_is_not_a_skip(self) -> None:
        """The whole point. A skip exits 0 and means "nothing to do"."""
        assert exit_code_for_status(RunStatus.SKIPPED) == ExitCode.OK
        assert exit_code_for_status(RunStatus.REFUSED) != ExitCode.OK


_DECLARED_BUT_ABSENT = """
from functualize.job import Fingerprint, job

JOB_GROUP = "r"


@job(group=JOB_GROUP, cache=Fingerprint(sources=["absent/*.json"]))
def verify() -> None:
    print("VERIFY BODY RAN")
"""


class TestRefusal:
    def test_declared_sources_that_resolve_to_nothing_refuse(
        self, tmp_path: Path
    ) -> None:
        """Cold *and* warm: the second run is the one that used to be fresh."""
        project = _project(tmp_path, _DECLARED_BUT_ABSENT)

        for label in ("cold", "warm"):
            result = _run(project, "r", "verify")
            assert result.returncode == 3, (
                f"{label} run exited {result.returncode}, not 3.\n"
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            assert "VERIFY BODY RAN" not in result.stdout
            assert "Refused" in result.stderr

    def test_a_job_declaring_no_sources_is_unaffected(self, tmp_path: Path) -> None:
        """The distinction that makes the refusal safe: "declared nothing" is
        not "declared something that matched nothing"."""
        project = _project(
            tmp_path,
            'from functualize.job import job\n\nJOB_GROUP = "r"\n\n\n'
            '@job(group=JOB_GROUP)\ndef plain() -> None:\n    print("PLAIN RAN")\n',
        )
        for _ in range(2):
            result = _run(project, "r", "plain")
            assert result.returncode == 0, result.stderr
            assert "PLAIN RAN" in result.stdout


_GENERATES = """
from pathlib import Path

from functualize.job import Fingerprint, job

JOB_GROUP = "r"


@job(group=JOB_GROUP, cache=Fingerprint(sources=["in.txt"], generates=["out/made.txt"]))
def build() -> None:
    Path("out").mkdir(exist_ok=True)
    Path("out/made.txt").write_text("built")
    print("BUILD BODY RAN")
"""


class TestMissingOutputForcesARun:
    def test_deleting_a_declared_output_is_not_fresh(self, tmp_path: Path) -> None:
        """`checksum` ignored `generates` entirely, so a job reported up to
        date with the artifact it promised to produce deleted — and every
        downstream consumer then read a record describing a file that is gone.
        """
        project = _project(tmp_path, _GENERATES)
        (project / "in.txt").write_text("unchanged\n")

        assert _run(project, "r", "build").returncode == 0
        # Unchanged inputs, output present: fresh, body must not run.
        second = _run(project, "r", "build")
        assert second.returncode == 0, second.stderr
        assert "BUILD BODY RAN" not in second.stdout

        (project / "out" / "made.txt").unlink()
        third = _run(project, "r", "build")
        assert third.returncode == 0, third.stderr
        assert "BUILD BODY RAN" in third.stdout, (
            "the declared output was deleted and the job still reported fresh"
        )
        assert (project / "out" / "made.txt").exists()


_RAISES = """
from functualize.job import job

JOB_GROUP = "r"


@job(group=JOB_GROUP)
def boom() -> None:
    raise RuntimeError("kaboom")
"""


class TestWarmBoundaryAgreesWithCold:
    def test_a_raising_job_exits_one_on_every_run(self, tmp_path: Path) -> None:
        """The warm command wrapper inspected the result not at all.

        Cold exited 1 with the traceback; warm — which is every run after the
        first — exited 0 in total silence. Asserting only the first run cannot
        see this, which is why it survived.
        """
        project = _project(tmp_path, _RAISES)

        for label in ("cold", "warm", "warm-again"):
            result = _run(project, "r", "boom")
            assert result.returncode == 1, (
                f"{label} run exited {result.returncode}, not 1.\n"
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            assert "kaboom" in result.stdout + result.stderr
