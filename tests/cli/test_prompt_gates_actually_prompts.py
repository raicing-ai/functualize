"""`--prompt-gates` **prompts** — AC-10's other half.

`tests/cli/test_app_surface_prompt_gates.py` asserts that the flag is accepted
on both surfaces and that a gated walk blocks without it. Both are real, and its
own docstring concedes what is missing: *"Whether an interactive prompt actually
renders is not testable without a tty, and pretending otherwise would make this
a test of the harness."*

That is true of a *terminal* prompt and not of the thing AC-10 promises. The
flag does not draw anything itself: it adds `"prompt"` to the gate's strategy
list (`_engine/workflow_walker.py::_gate_strategy_list`), and `PromptGateResolver`
then asks whatever `PromptCollector` the app's surface stack resolves to. A test
can push a surface and be that collector — no tty, no harness fiction, and the
assertion lands on the behaviour the flag is *for*: the gate's fields get asked
for, and the walk runs to completion instead of stopping.

Three things, because "it prompts" is three claims:

1. with the flag, the collector is asked — and asked for **the gate's fields**;
2. with the flag, the walk reaches the other side of the gate;
3. without it, neither happens (the falsifier, so 1 and 2 are attributable to
   the flag rather than to the gate being resolvable anyway).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from functualize._types.interactivity import PromptRequest, PromptResponse
from functualize.app.core import FunctualizeApp, request_for
from functualize.types import RunStatus
from functualize.workflow import END, Edge, Gate, Step, workflow


class Prefs(BaseModel):
    budget: str = Field(description="Budget level")


class RecordingSurface:
    """A surface that answers every prompt and remembers being asked."""

    def __init__(self, answer: str = "modest") -> None:
        self.requests: list[PromptRequest] = []
        self._answer = answer

    def collect(self, request: PromptRequest) -> PromptResponse:
        self.requests.append(request)
        return PromptResponse(value=self._answer)


@pytest.fixture
def gated_app(tmp_path, monkeypatch) -> tuple[FunctualizeApp, RecordingSurface]:
    monkeypatch.chdir(tmp_path)

    def survey() -> str:
        return "surveyed"

    @workflow(
        steps=[Step(survey), Gate(name="preferences", awaits=Prefs)],
        edges=[
            Edge(source="survey", target="preferences"),
            Edge(source="preferences", target=END),
        ],
    )
    def plan() -> str:
        """Walks to the gate."""
        return "planned"

    app = FunctualizeApp("gated")
    app.register_dynamic_job("survey", survey)
    app.register_dynamic_job("plan", plan)

    surface = RecordingSurface()
    app.push_surface(surface)
    return app, surface


def _run(app: FunctualizeApp, **changes: Any):
    """Run `plan`, stating control inputs as **request fields**.

    Not as `request_for("plan", prompt_gates=True)` — `request_for`'s keyword
    arguments are the *job's* arguments, so that spelling delivers
    `prompt_gates` to the workflow body and it fails with "unexpected keyword
    argument". That separation is deliberate and is what
    `tests/app/test_control_inputs_are_not_kwargs.py` pins; this helper exists
    so the tests below cannot get it wrong quietly.
    """
    return app.execute(request_for("plan").replace(**changes))


def test_with_the_flag_the_gate_is_asked_about(gated_app) -> None:
    app, surface = gated_app

    _run(app, prompt_gates=True)

    assert surface.requests, "the flag was set and nothing was ever asked"
    asked = " ".join(request.question for request in surface.requests).lower()
    assert "budget" in asked, (
        f"something was asked, but not for the gate's field: {asked!r}"
    )


def test_with_the_flag_the_walk_reaches_the_other_side(gated_app) -> None:
    """The point of prompting: the run finishes rather than pausing."""
    app, _ = gated_app

    result = _run(app, prompt_gates=True)

    assert result.status is RunStatus.SUCCESS, (
        "the gate was prompted for, so the walk should have finished; got "
        f"{result.status} ({result.exception})"
    )


def test_without_the_flag_nothing_is_asked_and_the_walk_blocks(gated_app) -> None:
    """The falsifier for both tests above.

    Without it they would pass for a gate that resolves on its own, and AC-10
    would be "kept" by a test that never exercised the flag.
    """
    app, surface = gated_app

    result = _run(app)

    assert surface.requests == [], (
        f"the gate was prompted for without the flag: {surface.requests}"
    )
    assert result.status is RunStatus.BLOCKED
