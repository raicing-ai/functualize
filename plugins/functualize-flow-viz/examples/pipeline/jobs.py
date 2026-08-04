"""A nested-invocation pipeline for flow-viz to visualize.

Run with:
    func jobs.py morning_report --city Tokyo
"""

from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.types import RunStatus


class ForecastConfig(BaseModel):
    """Configuration for weather jobs."""

    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")


def forecast(config: ForecastConfig, rc: RunContext) -> str:
    """Fetch the weather forecast for the configured city."""
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    return f"{config.city}: 24°C, sunny"


def alert(config: ForecastConfig, rc: RunContext) -> str:
    """Check forecast and send alerts if needed."""
    rc.log(f"No severe weather for {config.city} — all clear")
    return "all clear"


def morning_report(config: ForecastConfig, rc: RunContext) -> None:
    """Run the full morning weather pipeline (watch the tree render)."""
    rc.track_phase("forecast", "Fetching forecast", RunStatus.RUNNING)
    rc.invoke("forecast", city=config.city, days=config.days)
    rc.track_phase("forecast", "Forecast retrieved", RunStatus.SUCCESS)

    rc.track_phase("alerts", "Checking alerts", RunStatus.RUNNING)
    rc.invoke("alert", city=config.city)
    rc.track_phase("alerts", "Alerts checked", RunStatus.SUCCESS)

    rc.log("Morning report complete")
