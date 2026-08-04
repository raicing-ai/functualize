"""Step 3: Invoke jobs with workflow step tracking.

Run with:
    func weather.py morning_report --city Tokyo --days 5

Demonstrates:
- rc.invoke() to call other jobs (by name or function reference)
- rc.track_phase() for phase tracking
- Flow-viz plugin subscribes to these events automatically
"""

from pydantic import BaseModel, Field

from functualize._types.enums import RunStatus
from functualize.job import RunContext


class ForecastConfig(BaseModel):
    """Configuration for weather jobs."""

    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")


def forecast(config: ForecastConfig, rc: RunContext) -> str:
    """Fetch weather forecast for a city."""
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    return f"{config.city}: 24°C, sunny for the next {config.days} days"


def alert(config: ForecastConfig, rc: RunContext) -> str:
    """Check forecast and send alerts if needed."""
    rc.log("Checking alert conditions...")
    rc.log("No severe weather — all clear")
    return "no_alerts"


def morning_report(config: ForecastConfig, rc: RunContext) -> str:
    """Run the full morning weather pipeline with step tracking."""
    rc.track_phase("forecast", "Fetching forecast", RunStatus.RUNNING)
    rc.invoke("forecast", city=config.city, days=config.days)
    rc.track_phase("forecast", "Forecast retrieved", RunStatus.SUCCESS)

    rc.track_phase("alerts", "Checking alerts", RunStatus.RUNNING)
    rc.invoke("alert", city=config.city)  # Invoke by name
    rc.track_phase("alerts", "Alerts checked", RunStatus.SUCCESS)

    rc.log("Morning report complete")
    return "complete"
