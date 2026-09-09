"""``--prompt-gates`` works on an app's own entry point, not only ``func`` (D-1).

The body runs **twice** — `cli_run` is parameterised over the `func` and `app`
surfaces — and that is the whole point. Before run-request/T13 the `app` half
could not pass: `adapters/cli.py` declared `--force` beneath a comment claiming
"parity with the bare `func` CLI, which has both as pre-command globals", and
`--prompt-gates` was absent. A `@workflow` reached from an app entry point
blocked at its first `Gate` and there was no flag on that surface to prompt for
the gate's fields, so exit 5 was terminal — the defect the audit recorded as
D-1.

What is asserted is deliberately narrow: that the flag is **accepted and
forwarded**, and that a gated walk blocks with the documented exit code when it
is absent. Whether an interactive prompt actually renders is not testable
without a tty, and pretending otherwise would make this a test of the harness.
"""

from __future__ import annotations

import pytest

_GATED_WORKFLOW = '''\
"""A workflow that walks one step and then blocks on a gate."""

from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.workflow import END, Edge, Gate, Step, workflow


class Prefs(BaseModel):
    budget: str = Field(description="Budget level")


def survey(rc: RunContext) -> str:
    """The step before the gate."""
    return "surveyed"


@workflow(
    steps=[
        Step(survey),
        Gate(name="preferences", awaits=Prefs),
    ],
    edges=[
        Edge(source="survey", target="preferences"),
        Edge(source="preferences", target=END),
    ],
)
def plan(rc: RunContext) -> str:
    """Walks to the gate and blocks there."""
    return "planned"
'''


@pytest.fixture
def gated_tree(project_tree):
    return project_tree(jobs={"plan.py": _GATED_WORKFLOW})


class TestTheFlagIsAcceptedOnBothSurfaces:
    def test_the_flag_is_not_an_unknown_option(self, cli_run, gated_tree) -> None:
        # The failure this pins is a *usage* error — "no such option:
        # --prompt-gates" — which is what the app surface produced before T13.
        result = cli_run(["--prompt-gates", "plan"], cwd=gated_tree)

        combined = result.stdout + result.stderr
        assert "no such option" not in combined.lower(), combined
        assert "unrecognized" not in combined.lower(), combined
        assert "Traceback" not in result.stderr, result.stderr

    def test_it_is_accepted_before_the_job_name(self, cli_run, gated_tree) -> None:
        """A pre-command global, the same position `func` takes it in."""
        result = cli_run(["--prompt-gates", "plan"], cwd=gated_tree)

        # Whatever the walk decides, the flag itself must not be the problem.
        assert result.exit_code != 2, (
            f"exit 2 is a usage error, so the flag was rejected: {result.stderr}"
        )


class TestAGatedWalkBlocksWithoutIt:
    def test_a_gate_blocks_and_the_process_says_so(self, cli_run, gated_tree) -> None:
        """Exit 5 — "paused, not done" — is the same number on both surfaces.

        The decision recorded as D3: one rule everywhere, so a wrapper script
        can tell "waiting on a human" from "finished" without knowing which
        entry point ran.
        """
        result = cli_run(["plan"], cwd=gated_tree)

        assert result.exit_code == 5, (
            f"expected 5 (blocked at a gate), got {result.exit_code}: "
            f"{result.stdout}{result.stderr}"
        )
