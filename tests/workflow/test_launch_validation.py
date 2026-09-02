"""A `@workflow` job refuses an unbindable launch argument before it walks.

A workflow's kwargs bind to its *epilogue*, which runs after the graph. So an
argument the function cannot accept used to run every step, block at the gate,
wait for a person to approve the release, and only then raise — spending the
approval on a run that could never have succeeded.

The assertion that matters is **not** that the call fails. Both the old and the
new behaviour return a status, so `status is FAILURE` alone would pass against
an implementation that ran the whole graph and failed afterwards. What separates
them is the state store: before the fix a nonsense kwarg wrote four step records
and published a gate. After it, nothing is written at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._primitives.state_store import StateStore
from functualize._types.enums import RunStatus

_JOBS = '''
from pydantic import BaseModel, Field

from functualize import workflow
from functualize.job import Log, job
from functualize.workflow import END, Edge, Gate, Step


class Approval(BaseModel):
    note: str = Field(description="why this is approved")


@job
def alpha(log: Log) -> str:
    log("alpha ran")
    return "a"


@job
def omega(log: Log) -> str:
    log("omega ran")
    return "z"


@workflow(
    steps=[Step(alpha), Gate(name="pause", awaits=Approval), Step(omega)],
    edges=[Edge("alpha", "pause"), Edge("pause", "omega"), Edge("omega", END)],
)
def walk(log: Log) -> str:
    """DI-only signature: every parameter here is filled by the engine."""
    log("walk complete")
    return "done"
'''


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A project with one gated walk, with the cwd pointed at it.

    The engine resolves its state store from the working directory, so the
    chdir is what makes `StateStore.for_project(tmp_path)` below read the same
    file the run wrote.
    """
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "w.py").write_text(_JOBS)
    monkeypatch.chdir(tmp_path)

    from functualize.app import FunctualizeApp, JobSources

    return FunctualizeApp("w", job_sources=JobSources(directories=["jobs"])), tmp_path


def _scope(root: Path, scope_id: str) -> dict:
    """The persisted scope record, or an empty one if nothing was written."""
    return StateStore.for_project(root).get_scope(scope_id) or {}


class TestTheGraphDoesNotRun:
    """A1 — the assertion a status check cannot make."""

    def test_a_refused_launch_writes_no_scope_state(
        self, project: tuple[object, Path]
    ) -> None:
        app, root = project

        result = app.execute("walk", scope_id="a1", zzz_nonsense=1)  # type: ignore[attr-defined]

        assert result.status is RunStatus.FAILURE

        scope = _scope(root, "a1")
        assert not scope.get("steps"), "a step ran; the graph was walked"
        assert not scope.get("gates"), "a gate was published; the walk reached it"
        assert scope.get("position") is None, "the walk recorded a position"

    def test_the_same_walk_does_reach_the_gate_when_launched_cleanly(
        self, project: tuple[object, Path]
    ) -> None:
        """The control for the test above.

        Without it, an implementation that refused *every* launch would satisfy
        A1 perfectly. This is the cell that says the fixture can actually walk.
        """
        app, root = project

        result = app.execute("walk", scope_id="control")  # type: ignore[attr-defined]

        assert result.status is RunStatus.BLOCKED
        scope = _scope(root, "control")
        assert scope.get("steps"), "the walk recorded no steps"
        assert "pause" in scope.get("gates", {})
        assert scope.get("position") == "pause"


class TestParityWithAPlainJob:
    """A2 — the two kinds of job answer the same way."""

    def test_workflow_and_plain_job_refuse_identically(
        self, project: tuple[object, Path]
    ) -> None:
        """Compared against each other, never against a frozen string.

        The wording comes from CPython, so pinning a literal here would be a
        second source of truth for it. If the message ever changes, both sides
        change together and this still means what it says.
        """
        app, _ = project

        from_workflow = app.execute("walk", scope_id="a2", zzz_nonsense=1)  # type: ignore[attr-defined]
        from_plain = app.execute("alpha", zzz_nonsense=1)  # type: ignore[attr-defined]

        assert from_workflow.status is from_plain.status is RunStatus.FAILURE
        assert type(from_workflow.exception) is type(from_plain.exception) is TypeError

        assert "walk()" in str(from_workflow.exception)
        assert "alpha()" in str(from_plain.exception)
        for result in (from_workflow, from_plain):
            assert "zzz_nonsense" in str(result.exception)

    def test_neither_raises(self, project: tuple[object, Path]) -> None:
        """The invariant the refusal shape exists to preserve.

        A refusal that escaped as an exception would reach the CLI as a raw
        traceback instead of a rendered failure panel — the reason config
        resolution was moved inside this handler in the first place.
        """
        app, _ = project

        for job_name in ("walk", "alpha"):
            result = app.execute(job_name, zzz_nonsense=1)  # type: ignore[attr-defined]
            assert result.exception is not None
