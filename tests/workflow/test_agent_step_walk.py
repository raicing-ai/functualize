"""An agent step runs — through the port, through the public entry point.

The refusal tests cover what must *not* happen. These cover the other half:
a workflow declares an agent step the way a user would, and the step is
actually performed, recorded, replayed on resume, and wired into the graph's
edges and conditions exactly like any other node.

Driven through `FunctualizeApp.execute`, because the claim is about the
framework a user has, not about a walker assembled by hand: a core executor
that nothing registers would satisfy every unit test in this file's sibling.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from functualize._app.state import AppState
from functualize._primitives.state_store import StateStore
from functualize._types.enums import RunStatus
from functualize._types.errors import AgentExecutorUnavailableError
from functualize._types.interactivity import PromptRequest, PromptResponse
from functualize.app.core import FunctualizeApp, request_for
from functualize.types import RunRequest
from functualize.workflow import END, AgentStep, ConditionalEdge, Edge, Step
from functualize.workflow._decorator import workflow


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Give each test its own state file by running in a fresh cwd."""
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    yield


class _Surface:
    """A surface that answers prompts, so `cli-prompt` has someone to ask."""

    def __init__(self, answer: object = "done") -> None:
        self.answer = answer
        self.questions: list[str] = []
        self.steps: list[str | None] = []

    def collect(self, request: PromptRequest) -> PromptResponse:
        self.questions.append(request.question)
        self.steps.append(request.source_step)
        return PromptResponse(value=self.answer)


def _store() -> StateStore:
    return StateStore.for_project(Path.cwd())


def _single_agent_step_app(surface: _Surface) -> FunctualizeApp:
    """An app whose one workflow is a single agent step, and nothing else.

    No executor is registered by the test: resolution of an unnamed executor
    against "the single registered one" is only meaningful if the single
    registered one is core's own.
    """
    app = FunctualizeApp(name="testapp")
    app.push_surface(surface)

    @workflow(
        steps=[AgentStep(name="draft", instructions="Write the migration")],
        edges=[Edge(source="draft", target=END)],
    )
    def release() -> str:
        return "released"

    app.register_dynamic_job("release", release)
    return app


class TestAnAgentStepRuns:
    def test_the_registered_executor_performs_the_step(self) -> None:
        surface = _Surface("CREATE TABLE t (id int);")
        app = _single_agent_step_app(surface)

        result = app.execute(request_for("release"))

        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "released"
        # The step reached the surface, was asked its own instructions, and
        # was identified as the step rather than as an anonymous prompt.
        assert surface.questions == ["Write the migration"]
        assert surface.steps == ["draft"]

    def test_what_the_executor_returned_is_what_the_walk_recorded(self) -> None:
        surface = _Surface("CREATE TABLE t (id int);")
        app = _single_agent_step_app(surface)

        result = app.execute(request_for("release"))

        scope = _store().get_scope(str(result.metadata["workflow_scope"]))
        assert scope is not None
        assert scope["steps"]["draft::"]["status"] == "success"
        assert scope["steps"]["draft::"]["return_value"] == "CREATE TABLE t (id int);"

    def test_a_recorded_agent_step_replays_instead_of_being_asked_again(self) -> None:
        """A resumed walk must not spend the step twice — it is not free."""
        surface = _Surface("first answer")
        app = _single_agent_step_app(surface)

        first = app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="s1"
            )
        )
        second = app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="s1"
            )
        )

        assert first.status is RunStatus.SUCCESS
        assert second.status is RunStatus.SUCCESS
        assert surface.questions == ["Write the migration"]
        assert second.return_value == "released"

    def test_with_no_surface_the_step_fails_rather_than_inventing_an_answer(
        self,
    ) -> None:
        """Headless: the executor cannot ask, and says so. It is not skipped."""
        app = _single_agent_step_app(_Surface())
        app.pop_surface()

        result = app.execute(request_for("release"))

        assert result.status is RunStatus.FAILURE
        assert result.exception is not None
        assert "InputNotAvailable" in str(result.exception)
        scope = _store().get_scope(str(result.metadata["workflow_scope"]))
        assert scope is not None
        assert scope["steps"]["draft::"]["status"] == "failed"

    def test_an_executor_that_is_not_registered_refuses_before_anything_runs(
        self,
    ) -> None:
        """The end-to-end shape of AC-7: the walk never starts, and no step
        record exists to reconcile — the graph is refused, not half-run."""
        app = FunctualizeApp(name="testapp")
        ran: list[str] = []

        @workflow(
            steps=[Step("prepare"), AgentStep(name="draft", instructions="Write it")],
            edges=[
                Edge(source="prepare", target="draft"),
                Edge(source="draft", target=END),
            ],
        )
        def release() -> None:
            """Topology only."""

        app.register_dynamic_job("prepare", lambda: ran.append("prepare"))
        app.register_dynamic_job("release", release)
        # The core executor is the only one registered; remove it, so the
        # unnamed step has nothing to resolve to.
        app._agent_step_registry._executors.clear()

        with pytest.raises(AgentExecutorUnavailableError):
            app.execute(request_for("release"))

        assert ran == []


class TestAnAgentStepInsideAGraph:
    """AC-3: every existing node kind and edge works unchanged around one."""

    def test_a_conditional_edge_branches_on_what_the_agent_returned(self) -> None:
        surface = _Surface("ship it")
        app = FunctualizeApp(name="testapp")
        app.push_surface(surface)
        ran: list[str] = []

        def prepare() -> str:
            ran.append("prepare")
            return "prepared"

        def ship() -> str:
            ran.append("ship")
            return "shipped"

        def abandon() -> str:
            ran.append("abandon")
            return "abandoned"

        @workflow(
            steps=[
                Step("prepare"),
                AgentStep(name="review", instructions="Review the change"),
                Step("ship"),
                Step("abandon"),
            ],
            edges=[
                Edge(source="prepare", target="review"),
                ConditionalEdge(
                    source="review",
                    condition=lambda value: "ship" if value == "ship it" else "abandon",
                    targets={"ship": "ship", "abandon": "abandon"},
                ),
                Edge(source="ship", target=END),
                Edge(source="abandon", target=END),
            ],
        )
        def release() -> None:
            """Topology only."""

        app.register_dynamic_job("prepare", prepare)
        app.register_dynamic_job("ship", ship)
        app.register_dynamic_job("abandon", abandon)
        app.register_dynamic_job("release", release)

        result = app.execute(request_for("release"))

        assert result.status is RunStatus.SUCCESS
        # The branch the agent's own answer selected, and only that branch.
        assert ran == ["prepare", "ship"]
        assert surface.questions == ["Review the change"]
