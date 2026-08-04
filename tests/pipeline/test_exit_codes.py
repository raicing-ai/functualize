"""Exit codes are a contract with scripts and agents (S5 T39).

A caller greps the exit code to decide whether to retry, escalate, or resume,
so the table is pinned rather than emergent:

===  ==========================================================
  0  success (and *skipped* — a guard saying "nothing to do" did what was asked)
  1  the job raised
  2  usage / config error
  3  refused pre-flight (including ``requires_tty`` while piped)
  4  stale-check failure (``--check``)
  5  blocked awaiting gate input
===  ==========================================================

**5 is deliberately not 3** (decision D-a). A workflow that paused at a gate
ran successfully and is resumable; a pre-flight refusal never started. One code
for both would force every caller to parse stderr to tell "waiting for a human"
apart from "I refused" — the distinction a pipeline most needs to act on.
"""

from __future__ import annotations

import pytest

from functualize._types.enums import RunStatus
from functualize._types.exit_codes import ExitCode, exit_code_for_status


class TestStatusMapping:
    """The single seam every terminating path routes through."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (RunStatus.SUCCESS, ExitCode.OK),
            (RunStatus.SKIPPED, ExitCode.OK),
            (RunStatus.BLOCKED, ExitCode.BLOCKED),
            (RunStatus.FAILURE, ExitCode.JOB_RAISED),
            (RunStatus.TIMEOUT, ExitCode.JOB_RAISED),
            (RunStatus.CANCELLED, ExitCode.JOB_RAISED),
        ],
    )
    def test_each_terminal_status_maps_to_its_pinned_code(
        self, status: RunStatus, expected: ExitCode
    ) -> None:
        assert exit_code_for_status(status) == expected

    def test_blocked_does_not_share_a_code_with_refused(self) -> None:
        """The D-a decision, stated as a test so it cannot silently collapse."""
        assert exit_code_for_status(RunStatus.BLOCKED) != ExitCode.REFUSED
        assert exit_code_for_status(RunStatus.BLOCKED) == 5

    def test_a_skipped_job_does_not_break_a_shell_chain(self) -> None:
        """`func build && func deploy` must not stop because `build` was already
        up to date — a skip is the guard working, not a failure."""
        assert exit_code_for_status(RunStatus.SKIPPED) == 0

    def test_an_unmapped_status_is_a_failure_not_a_new_code(self) -> None:
        """Inventing a code here would put an unpinned number into a contract
        callers script against."""
        assert exit_code_for_status(RunStatus.UNKNOWN) == ExitCode.JOB_RAISED

    def test_the_codes_are_ints_usable_as_process_status(self) -> None:
        assert int(ExitCode.OK) == 0
        assert int(ExitCode.BLOCKED) == 5


_GEN_JOB = '''\
def generate() -> None:
    """Emit far more than any reader will take."""
    import sys

    for i in range(100000):
        print(f"line-{i}")
        sys.stdout.flush()
'''

_RAISER = '''\
def boom() -> None:
    """Always raises."""
    raise RuntimeError("kaboom")
'''


@pytest.mark.slow
class TestPipelineExitBehaviour:
    """Driven through the real binary — an exit code is only real at a process
    boundary, and the SIGPIPE path cannot be observed in-process at all."""

    def _project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "ec"\nversion = "0.1.0"\ndependencies = []\n'
        )
        (tmp_path / ".functualize.toml").write_text('jobs_directories = ["jobs"]\n')
        jobs = tmp_path / "jobs"
        jobs.mkdir()
        (jobs / "gen.py").write_text(_GEN_JOB)
        (jobs / "raiser.py").write_text(_RAISER)
        return tmp_path

    def _run(self, project, shell_cmd: str):
        import subprocess

        root = __import__("pathlib").Path(__file__).parent.parent.parent
        # `set -o pipefail` is load-bearing: without it bash reports the
        # *last* command's status, so `func … | head -5` would return head's 0
        # no matter what func did, and the assertion would be vacuous.
        return subprocess.run(
            [
                "bash",
                "-o",
                "pipefail",
                "-c",
                shell_cmd.replace("func ", f"uv run --project {root} func "),
            ],
            capture_output=True,
            text=True,
            cwd=str(project),
            timeout=120,
        )

    def test_a_closed_pipe_exits_zero_and_quietly(self, tmp_path) -> None:
        """The spec AC. A reader taking five lines and leaving is the normal
        way to use a pipeline, not an error — and the shutdown flush must not
        print "Exception ignored in: …" either, hence *quietly*."""
        project = self._project(tmp_path)

        result = self._run(project, "func generate | head -5")

        assert result.returncode == 0, result.stderr
        assert result.stderr.strip() == "", result.stderr
        assert "line-0" in result.stdout

    def test_a_raising_job_exits_one(self, tmp_path) -> None:
        project = self._project(tmp_path)

        result = self._run(project, "func boom")

        assert result.returncode == 1
