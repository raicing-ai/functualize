"""The Part I cells not covered elsewhere (S9/T35).

Each cell is either implemented here or recorded as superseded. Two of them
turned out to describe behavior a later decision replaced — worth pinning as
loudly as the ones that pass, because a stale acceptance criterion is a
standing invitation to "fix" working code back to a rejected design.

`FromJob` and `Annotated` are imported at **module** level on purpose. This
module uses `from __future__ import annotations`, so hints are strings
resolved against module globals; imported inside a test they are invisible to
`get_type_hints`, `resolved_hints` returns `{}`, and every edge silently
disappears. That trap cost real time during S8 even with a comment warning
about it two files over.
"""

from __future__ import annotations

from typing import Annotated

import pytest

from functualize._app.state import AppState
from functualize._types.enums import RunStatus
from functualize._types.errors import WorkflowDeclarationError
from functualize._types.from_job import FromJob, FromStep
from functualize.app.core import FunctualizeApp
from functualize.job import Deps, RunContext, job
from functualize.workflow import END, Edge, Gate, Step, workflow


@pytest.fixture(autouse=True)
def _reset() -> object:
    AppState.reset()
    yield
    AppState.reset()


def _app(name: str = "cells", **jobs: object) -> FunctualizeApp:
    app = FunctualizeApp(name=name)
    for job_name, fn in jobs.items():
        app.register_dynamic_job(job_name, fn)
    return app


class TestCellDxI:
    """`invoke(x)` where x has deps — deps honored at invoke time."""

    def test_invoke_runs_the_targets_dependencies(self) -> None:
        calls: list[str] = []

        @job
        def dep_j() -> str:
            calls.append("dep")
            return "d"

        @job(deps=Deps("dep_j"))
        def target() -> str:
            calls.append("target")
            return "t"

        @job
        def caller(rc: RunContext) -> str:
            return str(rc.invoke("target").return_value)

        _app("dxi", dep_j=dep_j, target=target, caller=caller).execute("caller")

        assert calls == ["dep", "target"], "an invoked job's deps must run first"


class TestCellFxI:
    """`invoke(x)` where x has `FromJob[y]` and y never ran — ensure-fresh."""

    def test_the_upstream_runs_and_its_value_is_injected(self) -> None:
        calls: list[str] = []

        @job
        def upstream() -> str:
            calls.append("upstream")
            return "value-from-upstream"

        @job
        def consumer(v: Annotated[str, FromJob("upstream")] = "MISSING") -> str:
            return v

        @job
        def caller(rc: RunContext) -> str:
            return str(rc.invoke("consumer").return_value)

        result = _app(
            "fxi", upstream=upstream, consumer=consumer, caller=caller
        ).execute("caller")

        assert calls == ["upstream"], "a never-run upstream must be run"
        assert result.return_value == "value-from-upstream"


class TestCellFxW:
    """`FromJob` naming a job that is not a node of the walk.

    **The matrix cell is superseded.** It specified "uniform ensure-fresh:
    cached-if-fresh, else run upstream". The shipped rule is stricter and was
    decided later: inside a workflow the *graph* declares the order, so a
    `run=True` reference to a job the graph does not contain is refused at
    validation. Running it would execute a job outside the ordering the walk
    exists to impose.

    The refusal names its own escape, and that escape is the ensure-fresh
    behavior the cell wanted — made explicit rather than implicit.
    """

    def _graph(self, run: bool):
        @job
        def outsider() -> str:
            return "o"

        if run:

            @job
            def step_one(v: Annotated[str, FromJob("outsider")] = "") -> str:
                return f"saw {v}"

        else:

            @job
            def step_one(
                v: Annotated[str, FromJob("outsider", run=False)] = "DEFAULT",
            ) -> str:
                return f"saw {v}"

        @workflow(steps=[Step(step_one)], edges=[Edge(source="step-one", target=END)])
        def wf(seen: Annotated[str, FromJob("step-one")] = "?") -> str:
            return seen

        return _app("fxw", outsider=outsider, step_one=step_one, wf=wf)

    def test_a_run_true_reference_outside_the_graph_is_refused(self) -> None:
        with pytest.raises(WorkflowDeclarationError, match="not a node in the graph"):
            self._graph(run=True).execute("wf", scope_id="fxw-1")

    def test_run_false_is_the_documented_escape(self) -> None:
        """Reading a recorded value orders nothing, so it needs no node."""
        result = self._graph(run=False).execute("wf", scope_id="fxw-2")
        assert result.return_value == "saw DEFAULT"


class TestCellDxWKeepGoing:
    """`Deps(policy="keep-going")` meeting the walk's failure mode.

    Node-local (resolved question 11): the step's own policy governs its dep
    set, and the walk's mode governs propagation. So a step that tolerates a
    failing dep still runs; a step that does not, fails the walk.
    """

    def _wf(self, policy: str):
        calls: list[str] = []

        @job
        def flaky() -> str:
            calls.append("flaky")
            raise RuntimeError("boom")

        @job
        def solid() -> str:
            calls.append("solid")
            return "s"

        @job(deps=Deps("flaky", "solid", policy=policy))  # type: ignore[arg-type]
        def step_one() -> str:
            calls.append("step_one")
            return "one"

        @workflow(steps=[Step(step_one)], edges=[Edge(source="step-one", target=END)])
        def wf() -> str:
            return "done"

        app = _app(f"dxw-{policy}", flaky=flaky, solid=solid, step_one=step_one, wf=wf)
        return app, calls

    def test_fail_fast_stops_the_step(self) -> None:
        app, calls = self._wf("fail-fast")
        result = app.execute("wf", scope_id="kg-1")

        assert result.status is not RunStatus.SUCCESS
        assert "step_one" not in calls, "the step must not run against a failed dep"

    def test_keep_going_still_runs_the_other_dep(self) -> None:
        """The policy is the step's own: it governs *its* dep set."""
        app, calls = self._wf("keep-going")
        app.execute("wf", scope_id="kg-2")

        assert "solid" in calls, "keep-going must not abandon the remaining deps"


class TestCellFsResumeAndMissing:
    """The two remaining `FS×` cells."""

    def _gated(self):
        from pydantic import BaseModel

        class Sub(BaseModel):
            ok: bool

        @job
        def setup_vfs() -> list[str]:
            return ["src/a.py"]

        @job
        def read_file(path: str, allowed: list[str] | None = None) -> str:
            if allowed is not None and path not in allowed:
                return f"REFUSED {path}"
            return f"contents {path}"

        @workflow(
            steps=[
                Step(setup_vfs),
                Gate(
                    name="edit",
                    awaits=Sub,
                    tools=[
                        # A step that ran, and one that never will.
                        __import__(
                            "functualize._types.workflow", fromlist=["Tool"]
                        ).Tool(read_file, allowed=FromStep("setup-vfs")),
                    ],
                ),
            ],
            edges=[
                Edge(source="setup-vfs", target="edit"),
                Edge(source="edit", target=END),
            ],
        )
        def wf() -> str:
            return "done"

        return _app("fs", setup_vfs=setup_vfs, read_file=read_file, wf=wf)

    def test_a_binding_still_resolves_after_a_block(self) -> None:
        """The scope's records outlive the pause, which is what makes a
        blocked gate answerable at all."""
        import asyncio

        from functualize_mcp._workflow_tools import WorkflowToolProvider

        app = self._gated()
        assert app.execute("wf", scope_id="FS1").status is RunStatus.BLOCKED

        tools = WorkflowToolProvider(app)
        result = asyncio.run(
            tools._call_gate_tool("FS1", "read_file", {"path": "src/a.py"})
        )
        assert result["return_value"] == "contents src/a.py"

    def test_a_binding_to_an_unreached_step_resolves_to_none(self) -> None:
        """The walk may legitimately not have reached it; the tool's own
        signature decides whether that is an error."""
        app = self._gated()
        app.execute("wf", scope_id="FS2")

        from functualize_mcp._workflow_tools import WorkflowToolProvider

        tools = WorkflowToolProvider(app)
        scope = tools.store.get_scope("FS2") or {}

        assert tools._resolve_bound(scope, {"x": FromStep("never-ran")}) == {"x": None}
