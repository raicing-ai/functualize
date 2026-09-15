"""A refused agent step leaves the process cleanly — exit 3, no traceback.

`contracts.md` §5 promised of both refusals: *"Each maps to an exit code
through F2's outcome module — no new exit code, no second vocabulary."*
Nothing mapped them. Both derive from `Exception`, and they are raised in
`WorkflowRunner.prelude` — before DI resolution and before any hook — so they
never become a `JobResult` and never reach `deliver_job_result`. They travelled
straight out of `engine.run` to the process boundary:

    Traceback (most recent call last):
      ...
    functualize._types.errors.AgentExecutorUnavailableError: Agent step 'draft'
    names executor 'ai', which is not registered ...
    exit 1

Exit **1** is `JOB_RAISED`, and `_types/exit_codes.py` says in its own words why
a refusal must not land there: it would be *"indistinguishable from a job that
ran and threw"*. `REFUSED` (3) exists for exactly this — "the job declined to
start because a declared precondition for running it was not met".

`prelude_refusal` (formerly `scope_store_refusal`) now catches them. Its
docstring carries the reason the two exit codes differ.

**Why the feature's own tests could not see this.** Every test in
`test_agent_step_refusals.py` drives `WorkflowRunner` or `AgentStepRegistry`
directly and asserts `pytest.raises(...)` — which is correct at that level, and
is also precisely the behaviour that is wrong one layer up. The refusal
*should* be an exception in the engine and *should not* be one at the process
boundary, and no test in the feature crossed that line. This file is that line.

The body runs on both doors and, within each, **twice** — the second call is
the warm/cached-descriptor dispatch path, which is a different wrapper. Only
one of the two used to handle a case is `contributor/reference/pitfalls.md` §23,
and `deliver_job_result`'s docstring records what it cost: "Cold boot exited 1,
warm boot exited 0, for the same job and the same failure."
"""

from __future__ import annotations

import textwrap

from functualize._types.exit_codes import ExitCode

_WORKFLOW = textwrap.dedent(
    '''
    from functualize.workflow import END, AgentStep, Edge, workflow


    @workflow(
        steps=[AgentStep(name="draft", instructions="Write it", executor="ai")],
        edges=[Edge(source="draft", target=END)],
    )
    def release() -> None:
        """Needs an executor nobody registered."""
    '''
)


def _tree(project_tree):
    return project_tree(jobs={"release.py": _WORKFLOW}, convention_dirs=True)


class TestAnUnregisteredExecutorRefusesCleanly:
    def test_it_exits_refused_not_job_raised(self, cli_run, project_tree) -> None:
        result = cli_run(["release"], cwd=_tree(project_tree))

        assert result.exit_code == ExitCode.REFUSED, (
            f"expected {ExitCode.REFUSED} (REFUSED), got {result.exit_code}"
            f"\n{result.stdout}\n{result.stderr}"
        )

    def test_it_prints_a_line_rather_than_a_traceback(
        self, cli_run, project_tree
    ) -> None:
        """The message was always good; it was the *delivery* that was wrong."""
        result = cli_run(["release"], cwd=_tree(project_tree))

        combined = result.stdout + result.stderr
        assert "Traceback (most recent call last)" not in combined
        assert "AgentExecutorUnavailableError" not in combined
        assert "Error:" in combined

    def test_it_still_says_which_package_supplies_the_executor(
        self, cli_run, project_tree
    ) -> None:
        """The refusal's whole value is the hint; catching it must not eat it."""
        result = cli_run(["release"], cwd=_tree(project_tree))

        combined = result.stdout + result.stderr
        assert "functualize-ai" in combined

    def test_the_warm_dispatch_path_answers_the_same(
        self, cli_run, project_tree
    ) -> None:
        """Second invocation, same tree: the cached-descriptor wrapper.

        A separate `with live_ctx, prelude_refusal():` site, and the one that
        historically diverged.
        """
        root = _tree(project_tree)

        cold = cli_run(["release"], cwd=root)
        warm = cli_run(["release"], cwd=root)

        assert cold.exit_code == warm.exit_code == ExitCode.REFUSED
        assert "Traceback" not in warm.stdout + warm.stderr
