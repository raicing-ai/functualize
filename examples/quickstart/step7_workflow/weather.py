"""Step 7: Workflows that pause for input.

A `@workflow` declares a graph of jobs plus the points where the graph must
stop and wait. Running the workflow job walks that graph:

    func weather.py trip_planner --city Tokyo

`forecast` runs, then the walk reaches the `preferences` gate, finds no input,
and stops. The job reports BLOCKED (exit 5) — not a failure. It did everything
it was asked to do and is waiting.

Answering the gate is a separate act. An AI agent driving this over MCP calls
`get_workflow_state` to see the gate's JSON schema, then `resume_gate` to
deposit input. Running the job again replays the walk: `forecast` is already
recorded for this scope so it is skipped, the gate is now answered, and
`travel_plan` and the body run.

The decorated function's own body is the *epilogue* — it runs once, after the
walk reaches `END`, and its return value is the workflow's return value. That
is what makes a workflow an ordinary job: `trip_planner` can be depended on,
or used as a `Step` of another workflow, with no special composition feature.
"""

from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.workflow import END, Edge, Gate, Step, workflow


class ForecastConfig(BaseModel):
    """Configuration for weather jobs."""

    city: str = Field(default="Tokyo", description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")


class TripPreferences(BaseModel):
    """Input the gate waits for before planning continues."""

    budget: str = Field(description="Budget level: budget, mid-range, luxury")
    interests: list[str] = Field(description="Travel interests")


def forecast(config: ForecastConfig, rc: RunContext) -> str:
    """Fetch the weather forecast for the configured city."""
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    return f"{config.city}: 24°C, sunny for the next {config.days} days"


def travel_plan(config: ForecastConfig, rc: RunContext) -> str:
    """Produce the final plan once preferences are resolved."""
    rc.log(f"Planning a trip to {config.city}...")
    return f"Trip plan for {config.city} ready"


@workflow(
    steps=[
        Step(forecast),
        # `tools` tells an agent what it may use while answering this gate.
        Gate(name="preferences", awaits=TripPreferences, tools=["run_job"]),
        Step(travel_plan),
    ],
    edges=[
        Edge(source="forecast", target="preferences"),
        Edge(source="preferences", target="travel_plan"),
        Edge(source="travel_plan", target=END),
    ],
)
def trip_planner(config: ForecastConfig, rc: RunContext) -> str:
    """Multi-step trip planning that pauses for traveller preferences."""
    rc.log(f"Itinerary for {config.city} complete.")
    return f"Itinerary ready for {config.city}"
