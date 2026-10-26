"""Boot validation of every declared walk-local reader position."""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._types.errors import WorkflowDeclarationError
from functualize.app.core import FunctualizeApp, request_for
from functualize.job import FromJob
from functualize.workflow import END, Edge, FromStep, Gate, Step, Tool, workflow


class Answer(BaseModel):
    ok: bool


@pytest.fixture(autouse=True)
def _reset_state():
    AppState.reset()
    yield
    AppState.reset()


def _run(**jobs: object) -> None:
    app = FunctualizeApp(name="validation")
    for name, function in jobs.items():
        app.register_dynamic_job(name, function)
    app.execute(request_for("walk"))


def test_step_may_read_an_earlier_gate() -> None:
    def act(answer: Annotated[Answer, FromStep("approve")]) -> bool:
        return answer.ok

    @workflow(
        steps=[Gate("approve", awaits=Answer), Step(act)],
        edges=[Edge("approve", "act"), Edge("act", END)],
    )
    def walk() -> None:
        pass

    _run(act=act, walk=walk)


def test_gate_tool_may_bind_an_earlier_step() -> None:
    def plan() -> str:
        return "plan"

    def inspect(allowed: str) -> str:
        return allowed

    @workflow(
        steps=[
            Step(plan),
            Gate(
                "approve",
                awaits=Answer,
                tools=[Tool(inspect, allowed=FromStep("plan"))],
            ),
        ],
        edges=[Edge("plan", "approve"), Edge("approve", END)],
    )
    def walk() -> None:
        pass

    _run(plan=plan, inspect=inspect, walk=walk)


def test_epilogue_may_read_any_declared_node() -> None:
    def plan() -> str:
        return "plan"

    @workflow(steps=[Step(plan)], edges=[Edge("plan", END)])
    def walk(value: Annotated[str, FromStep("plan")] = "default") -> str:
        return value

    _run(plan=plan, walk=walk)


def test_epilogue_unknown_name_is_refused() -> None:
    def plan() -> str:
        return "plan"

    @workflow(steps=[Step(plan)], edges=[Edge("plan", END)])
    def walk(value: Annotated[str, FromStep("other")] = "default") -> str:
        return value

    with pytest.raises(WorkflowDeclarationError) as caught:
        _run(plan=plan, walk=walk)
    message = str(caught.value)
    assert "FromStep('other')" in message
    assert "value" in message and "walk" in message


def test_step_cannot_read_itself() -> None:
    def act(value: Annotated[str, FromStep("act")]) -> str:
        return value

    @workflow(steps=[Step(act)], edges=[Edge("act", END)])
    def walk() -> None:
        pass

    with pytest.raises(WorkflowDeclarationError) as caught:
        _run(act=act, walk=walk)
    message = str(caught.value)
    assert "FromStep('act')" in message
    assert "value" in message and "act" in message


def test_mixed_sources_are_refused() -> None:
    def plan() -> str:
        return "plan"

    def act(value: Annotated[str, FromJob("plan"), FromStep("plan")]) -> str:
        return value

    @workflow(
        steps=[Step(plan), Step(act)],
        edges=[Edge("plan", "act"), Edge("act", END)],
    )
    def walk() -> None:
        pass

    with pytest.raises(WorkflowDeclarationError) as caught:
        _run(plan=plan, act=act, walk=walk)
    assert "value" in str(caught.value)
    assert "FromJob and FromStep" in str(caught.value)
