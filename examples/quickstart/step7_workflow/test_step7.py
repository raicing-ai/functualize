"""Tests for Step 7: a workflow that blocks at a gate and resumes.

The declaration tests are cheap structural checks. The ones that matter run the
graph through the real engine, because the whole claim of Step 7 is that
running the workflow job *walks* the graph — a claim no amount of inspecting
`__functualize_workflow__` can support.
"""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from weather import (
    ForecastConfig,
    TripPreferences,
    forecast,
    travel_plan,
    trip_planner,
)

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.app.utils import StateStore
from functualize.job import RunStatus
from functualize.workflow import END, Gate, Step


@pytest.fixture(autouse=True)
def _isolated_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    """A fresh app and state file per test."""
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def app() -> FunctualizeApp:
    instance = FunctualizeApp(name="step7")
    instance.register_dynamic_job("forecast", forecast, config_class=ForecastConfig)
    instance.register_dynamic_job(
        "travel_plan", travel_plan, config_class=ForecastConfig
    )
    instance.register_dynamic_job(
        "trip_planner", trip_planner, config_class=ForecastConfig
    )
    return instance


def _store() -> StateStore:
    return StateStore.for_project(Path.cwd())


# --- Declaration -----------------------------------------------------------


def test_workflow_definition_attached():
    wf = trip_planner.__functualize_workflow__
    assert [s.name for s in wf.nodes] == ["forecast", "preferences", "travel-plan"]


def test_preferences_is_a_gate_node():
    nodes = {s.name: s for s in trip_planner.__functualize_workflow__.nodes}
    gate = nodes["preferences"]
    assert isinstance(gate, Gate)
    assert gate.awaits is TripPreferences
    assert gate.tools == ("run_job",)


def test_step_nodes_reference_jobs():
    nodes = {s.name: s for s in trip_planner.__functualize_workflow__.nodes}
    assert isinstance(nodes["forecast"], Step)
    assert nodes["forecast"].job is forecast
    assert nodes["travel-plan"].job is travel_plan


def test_edges_terminate_at_end():
    edges = trip_planner.__functualize_workflow__.edges
    assert [(e.source, e.target) for e in edges[:-1]] == [
        ("forecast", "preferences"),
        ("preferences", "travel-plan"),
    ]
    assert edges[-1].source == "travel-plan"
    assert edges[-1].target is END


def test_step_jobs_run_directly():
    rc = MagicMock()
    config = ForecastConfig(city="Tokyo")
    assert "Tokyo" in forecast(config, rc)
    assert "Tokyo" in travel_plan(config, rc)


# --- Walking the graph -----------------------------------------------------


def test_running_the_workflow_blocks_at_the_gate(app):
    result = app.execute("trip_planner", scope_id="trip-1")

    assert result.status is RunStatus.BLOCKED
    assert result.status.resumable, "a gate is a pause, not a failure"
    assert result.metadata["blocked_on"] == "preferences"


def test_the_gate_publishes_the_schema_a_caller_must_satisfy(app):
    app.execute("trip_planner", scope_id="trip-1")

    gate = _store().get_gate("trip-1", "preferences")
    assert gate is not None
    assert gate["model"] == "TripPreferences"
    assert set(gate["input_schema"]["required"]) == {"budget", "interests"}


def test_answering_the_gate_lets_the_workflow_finish(app):
    app.execute("trip_planner", scope_id="trip-1")
    _store().deposit_gate_payload(
        "trip-1",
        "preferences",
        {"budget": "mid-range", "interests": ["food", "temples"]},
    )

    result = app.execute("trip_planner", scope_id="trip-1")

    assert result.status is RunStatus.SUCCESS
    assert result.return_value == "Itinerary ready for Tokyo"


def test_resuming_does_not_rerun_completed_steps(app):
    """Replay + memoization: `forecast` ran before the block and must not run
    twice, or resuming a paused workflow would repeat its side effects."""
    app.execute("trip_planner", scope_id="trip-1")
    _store().deposit_gate_payload(
        "trip-1", "preferences", {"budget": "budget", "interests": ["hiking"]}
    )
    app.execute("trip_planner", scope_id="trip-1")

    scope = _store().get_scope("trip-1")
    assert scope["status"] == "completed"
    assert scope["steps"]["forecast::"]["status"] == "success"


def test_a_fresh_scope_starts_over(app):
    """Scope ids address runs; a new one is a new trip, not a resume."""
    first = app.execute("trip_planner", scope_id="trip-1")
    second = app.execute("trip_planner", scope_id="trip-2")

    assert first.status is RunStatus.BLOCKED
    assert second.status is RunStatus.BLOCKED
    assert set(_store().scope_ids()) == {"trip-1", "trip-2"}
