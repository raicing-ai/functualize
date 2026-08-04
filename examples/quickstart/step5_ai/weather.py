"""Step 5: Add AI with structured output.

Mirrors README Quick Start Step 5: an AI-powered job that turns weather
data into a typed travel plan via ``ai.complete(..., response_model=...)``.

This runnable example uses ``MockAI`` so it works without API keys.
With ``functualize-ai-pydantic`` installed, drop the mock and declare
``ai: AI`` as a job parameter instead — the framework injects the real
provider:

    def travel_plan(config: ForecastConfig, ai: AI, rc: RunContext): ...

Run with:
    func weather.py travel_plan --city Tokyo --days 5
"""

from functualize_ai.testing import MockAI
from pydantic import BaseModel, Field

from functualize.job import RunContext


class ForecastConfig(BaseModel):
    """Configuration for weather jobs."""

    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")


class TravelPlan(BaseModel):
    """Structured output the AI must produce."""

    destination: str
    best_days: list[str]
    packing_tips: list[str]


def forecast(config: ForecastConfig, rc: RunContext) -> str:
    """Fetch the weather forecast for the configured city."""
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    return f"{config.city}: 24°C, sunny for the next {config.days} days"


def travel_plan(config: ForecastConfig, rc: RunContext) -> TravelPlan:
    """AI generates a structured travel plan from weather data."""
    weather = forecast(config, rc)

    # MockAI stands in for the injected AI capability (no API key needed)
    ai = MockAI(
        responses={
            "*travel plan*": TravelPlan(
                destination=config.city,
                best_days=["Saturday", "Sunday"],
                packing_tips=["sunscreen", "light jacket"],
            ),
        }
    )

    plan = ai.complete(
        f"Create a travel plan for {config.city} based on: {weather}",
        response_model=TravelPlan,
    )
    rc.log(f"Best days: {', '.join(plan.best_days)}")
    rc.log(f"Pack: {', '.join(plan.packing_tips)}")
    return plan
