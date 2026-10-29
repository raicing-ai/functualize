"""Step 3: Invoke jobs with workflow step tracking.

Run with:
    func weather.py morning_report --city Tokyo --days 5

Demonstrates:
- rc.invoke() to call other jobs (by name or function reference)
- .raise_for_status() to stop when a child did not do its work, and
  catching JobFailedError where the parent can do better than fail
- rc.invoke(..., capture=True) to take a child's emitted output back as data
- rc.events.track_phase() for phase tracking
- Flow-viz plugin subscribes to these events automatically
"""

from pydantic import BaseModel, Field

from functualize._types.enums import RunStatus
from functualize.job import RunContext, Stdout
from functualize.types import JobFailedError


class ForecastConfig(BaseModel):
    """Configuration for weather jobs."""

    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")


def forecast(config: ForecastConfig, rc: RunContext) -> str:
    """Fetch weather forecast for a city."""
    if not config.city.strip():
        raise ValueError("no city to forecast")
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    return f"{config.city}: 24°C, sunny for the next {config.days} days"


def alert(config: ForecastConfig, rc: RunContext, out: Stdout) -> str:
    """Check forecast and send alerts if needed."""
    rc.log("Checking alert conditions...")
    rc.log("No severe weather — all clear")
    # Run on its own, this document reaches stdout. Invoked with
    # capture=True, it comes back to the parent instead.
    out.emit({"city": config.city, "alerts": []})
    return "no_alerts"


def morning_report(config: ForecastConfig, rc: RunContext) -> str:
    """Run the full morning weather pipeline with step tracking."""
    rc.events.track_phase("forecast", "Fetching forecast", RunStatus.RUNNING)
    try:
        # An unchecked rc.invoke() returns a failed forecast as a value and
        # carries on. raise_for_status() turns it into JobFailedError here.
        rc.invoke("forecast", city=config.city, days=config.days).raise_for_status()
    except JobFailedError as err:
        # The one failure this report can do better than crash on: say so,
        # and finish. Leave the call unchecked only if you branch on status.
        rc.log(f"{err.job_name} did not succeed ({err.status.value})", level="warning")
        rc.events.track_phase("forecast", "Forecast unavailable", RunStatus.FAILURE)
        return "forecast unavailable"
    rc.events.track_phase("forecast", "Forecast retrieved", RunStatus.SUCCESS)

    rc.events.track_phase("alerts", "Checking alerts", RunStatus.RUNNING)
    # Invoke by name, checked, with alert's emitted document captured as data.
    checked = rc.invoke("alert", city=config.city, capture=True).raise_for_status()
    alerts = [a for doc in checked.metadata["emitted"] for a in doc["alerts"]]
    rc.events.track_phase("alerts", "Alerts checked", RunStatus.SUCCESS)

    rc.log("Morning report complete")
    return f"complete: {len(alerts)} alert(s)"
