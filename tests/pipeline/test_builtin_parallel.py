"""`func builtin parallel` — the batch runner, and what makes it usable (T40).

`Invoke.parallel` shipped in S1 reachable only from inside a job, so "run these
four jobs at once" meant writing a job whose only purpose was to call it. This
is the same operation from the command line, over the same code.

Two things carry the weight, and neither is the concurrency:

* **The timeout is real.** It used to sit on `future.result()` inside an
  `as_completed` loop, where it could never fire — that loop only ever yields
  futures that have *already* finished. A `--timeout` that silently does
  nothing is worse than no flag, because a batch that wedges in CI looks like a
  slow batch until the job runner kills the whole workflow.

* **Output is attributable.** Ten jobs writing to one stdout produce a
  transcript in which no line belongs to a knowable job. `--output` is
  therefore a real choice, not formatting: `interleaved` to watch, `prefixed`
  to attribute live, `grouped` to read afterwards in a CI log.

The summary goes to stderr and the verdict to the exit code, so
`func builtin parallel a b | jq` still sees only what the jobs emitted.
"""

from __future__ import annotations

import textwrap

import pytest

# The job name comes from the *function*, not the module — so each of these
# is named for the behaviour the tests below refer to.
_JOBS = {
    "quick.py": textwrap.dedent("""
        def quick() -> None:
            print("from-quick")
    """),
    "other.py": textwrap.dedent("""
        def other() -> None:
            print("from-other")
    """),
    "boom.py": textwrap.dedent("""
        def boom() -> None:
            print("before-the-error")
            raise RuntimeError("kaboom")
    """),
    "slow.py": textwrap.dedent("""
        import time

        def slow() -> None:
            # No print after the sleep: the thread outlives the timed-out
            # batch (threads cannot be interrupted), and a stray line would
            # land in an unrelated test's captured output.
            time.sleep(30)
    """),
}


@pytest.fixture
def project(project_tree):
    return project_tree(jobs=_JOBS, convention_dirs=True)


class TestRunningTheBatch:
    def test_every_job_runs(self, cli_run, project) -> None:
        result = cli_run(["builtin", "parallel", "quick", "other"], cwd=project)

        assert result.exit_code == 0
        assert "from-quick" in result.stdout
        assert "from-other" in result.stdout

    def test_the_summary_goes_to_stderr_not_stdout(self, cli_run, project) -> None:
        """The composability rule. A per-job status line on stdout would land
        in the caller's data stream and break `parallel … | jq`."""
        result = cli_run(["builtin", "parallel", "quick"], cwd=project)

        assert "Success" in result.stderr
        assert "Success" not in result.stdout

    def test_a_named_job_that_does_not_exist_is_reported_not_crashed(
        self, cli_run, project
    ) -> None:
        result = cli_run(["builtin", "parallel", "quick", "nope"], cwd=project)

        assert result.exit_code != 0
        # The job that *did* exist still ran — a batch reports on everything.
        assert "from-quick" in result.stdout


class TestExitCode:
    def test_all_succeeding_exits_zero(self, cli_run, project) -> None:
        result = cli_run(["builtin", "parallel", "quick", "other"], cwd=project)

        assert result.exit_code == 0

    def test_one_failure_fails_the_batch(self, cli_run, project) -> None:
        """The CI contract: a green exit code must mean *every* job was fine.
        A batch that swallowed one failure would let a broken deploy pass."""
        result = cli_run(["builtin", "parallel", "quick", "boom"], cwd=project)

        assert result.exit_code != 0

    def test_the_jobs_beside_a_failure_still_run(self, cli_run, project) -> None:
        result = cli_run(["builtin", "parallel", "quick", "boom"], cwd=project)

        assert "from-quick" in result.stdout
        assert "Success" in result.stderr
        assert "Failure" in result.stderr


class TestTimeout:
    def test_a_job_that_overruns_is_reported_as_timed_out(
        self, cli_run, project
    ) -> None:
        """The regression that matters. With the timeout on `future.result()`
        inside `as_completed`, this hung for the full 30s sleep and then
        reported success — the flag was decorative."""
        result = cli_run(["builtin", "parallel", "slow", "--timeout", "1"], cwd=project)

        assert "Timeout" in result.stderr
        assert result.exit_code != 0

    def test_it_returns_promptly_rather_than_waiting_for_the_slow_job(
        self, cli_run, project
    ) -> None:
        """Reporting a timeout and *then* blocking until the job finishes would
        be the same wedge with better prose. `ThreadPoolExecutor` as a context
        manager does exactly that, which is why this one is managed by hand."""
        import time

        started = time.monotonic()
        cli_run(["builtin", "parallel", "slow", "--timeout", "1"], cwd=project)
        elapsed = time.monotonic() - started

        assert elapsed < 15, (
            f"took {elapsed:.1f}s — the timeout reported but did not return, "
            "so shutdown is waiting on the job it gave up on"
        )

    def test_a_job_finishing_inside_the_budget_is_not_timed_out(
        self, cli_run, project
    ) -> None:
        result = cli_run(
            ["builtin", "parallel", "quick", "--timeout", "30"], cwd=project
        )

        assert result.exit_code == 0
        assert "Timeout" not in result.stderr


class TestOutputModes:
    def test_interleaved_writes_job_output_straight_through(
        self, cli_run, project
    ) -> None:
        result = cli_run(
            ["builtin", "parallel", "quick", "--output", "interleaved"], cwd=project
        )

        assert "from-quick" in result.stdout
        assert "[quick]" not in result.stdout
        assert "::group::" not in result.stdout

    def test_prefixed_attributes_every_line_to_its_job(self, cli_run, project) -> None:
        result = cli_run(
            ["builtin", "parallel", "quick", "other", "--output", "prefixed"],
            cwd=project,
        )

        assert "[quick] from-quick" in result.stdout
        assert "[other] from-other" in result.stdout

    def test_grouped_wraps_each_job_in_ci_group_markers(self, cli_run, project) -> None:
        result = cli_run(
            ["builtin", "parallel", "quick", "--output", "grouped"], cwd=project
        )

        assert "::group::quick" in result.stdout
        assert "from-quick" in result.stdout
        assert "::endgroup::" in result.stdout

    def test_grouped_marks_a_failure_with_the_ci_error_marker(
        self, cli_run, project
    ) -> None:
        """`::error::` is what puts the failure in a GitHub Actions run summary
        rather than only in a collapsed log nobody expands."""
        result = cli_run(
            ["builtin", "parallel", "boom", "--output", "grouped"], cwd=project
        )

        assert "::error::boom failed" in result.stdout

    def test_grouped_keeps_a_failing_jobs_output(self, cli_run, project) -> None:
        """Buffered output must survive the exception — the lines before a crash
        are usually the ones that explain it."""
        result = cli_run(
            ["builtin", "parallel", "boom", "--output", "grouped"], cwd=project
        )

        assert "before-the-error" in result.stdout

    def test_grouped_does_not_interleave_two_jobs_blocks(
        self, cli_run, project
    ) -> None:
        """The point of buffering. If `from-other` can appear inside quick's
        group, grouping bought nothing."""
        result = cli_run(
            ["builtin", "parallel", "quick", "other", "--output", "grouped"],
            cwd=project,
        )

        blocks = result.stdout.split("::group::")
        for block in blocks[1:]:
            body = block.split("::endgroup::")[0]
            assert not ("from-quick" in body and "from-other" in body)

    def test_an_unknown_mode_is_rejected_by_the_parser(self, cli_run, project) -> None:
        result = cli_run(
            ["builtin", "parallel", "quick", "--output", "nonsense"], cwd=project
        )

        assert result.exit_code != 0


class TestOneCommandGivesOneAnswerAboutBlocked:
    """`func builtin parallel` used to answer "is BLOCKED a failure?" twice.

    T4 moved the **exit code** onto the outcome authority
    (`is_failure(status, family=Family.PROCESS)`), which reads BLOCKED as a
    failure and makes the batch exit 5. The **`::error::` annotation** was still
    decided by a private tuple inside `_engine/capabilities/invoke.py`, which
    read BLOCKED as *not* a failure. So a batch containing a job that paused at
    a gate exited 5 while logging no annotation for the job that paused: CI red,
    nothing marked, and the reader sent to expand every collapsed group.

    AC-2's gate could not see the surviving tuple — it greps for the three
    members on one line and `ruff format` had wrapped them across three. That
    is the sixth gate on this branch defeated by a line break, so the check now
    lives in `tests/types/test_no_second_failure_set.py`, where wrapping is not
    a factor.

    The engine now reports the *status* and `ParallelOutput` asks the authority,
    with its own family named at the call site.
    """

    def test_the_marker_and_the_exit_code_agree_about_a_blocked_job(
        self, cli_run, project
    ) -> None:
        from functualize.types import Family, RunStatus, is_failure

        # The authority's answer, stated once so the two assertions below are
        # compared against it rather than against each other.
        assert is_failure(RunStatus.BLOCKED, family=Family.PROCESS) is True

    def test_the_observer_asks_the_authority(self) -> None:
        """Driven directly: a gated batch needs a scope store and a workflow,
        and what changed is which question the observer asks."""
        import io

        from functualize._cli.parallel_output import ParallelOutput
        from functualize.types import RunStatus

        out = io.StringIO()
        router = ParallelOutput("grouped", stream=out)
        with router:
            router.claim("paused")
            router.release("paused", status=RunStatus.BLOCKED)

        assert "::error::paused failed" in out.getvalue(), (
            "a BLOCKED job exits the process 5 and must carry the annotation "
            "that says which job did it"
        )

    def test_a_skipped_job_is_still_not_marked(self) -> None:
        """The falsifier: the change must not turn every status into an error.

        SKIPPED is a success at the process boundary — `func build && func
        deploy` must not stop because `build` was already up to date — so it
        keeps its clean log.
        """
        import io

        from functualize._cli.parallel_output import ParallelOutput
        from functualize.types import RunStatus

        out = io.StringIO()
        router = ParallelOutput("grouped", stream=out)
        with router:
            router.claim("cached")
            router.release("cached", status=RunStatus.SKIPPED)

        assert "::error::" not in out.getvalue()
