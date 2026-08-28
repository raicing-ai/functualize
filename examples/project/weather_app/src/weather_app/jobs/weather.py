"""Weather jobs — the README Quick Start progression, living in a project.

Run via the installed entry point (`weather-app forecast --city Tokyo`)
or directly with `func` from the project directory.
"""

from pydantic import BaseModel, Field

from functualize.job.context import RunContext
from functualize.job.decorators import job
from functualize.types import RunStatus


class ForecastConfig(BaseModel):
    """Configuration for weather jobs.

    Values resolve from (highest to lowest precedence):
    1. CLI flags (--city, --days, --api-url)
    2. Environment variables (FORECAST_CITY, FORECAST_DAYS, FORECAST_API_URL)
    3. Config files ([forecast] section in config.base.toml + ENVIRONMENT overlay)
    4. Model defaults below
    """

    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")
    api_url: str = Field(
        default="https://weather.example.com", description="Weather API endpoint"
    )


@job(
    extra_description="Get a weather forecast for a city",
    category="weather",
    tags=["weather", "safe", "read-only"],
    visibility="external",
)
def forecast(config: ForecastConfig, rc: RunContext) -> str:
    """Fetch the weather forecast for the configured city."""
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    rc.log(f"Using API: {config.api_url}")
    result = f"{config.city}: 24°C, sunny for the next {config.days} days"
    rc.log(result)
    return result


def alert(config: ForecastConfig, rc: RunContext) -> str:
    """Check forecast and send alerts if needed."""
    rc.log(f"Checking alert conditions for {config.city}...")
    rc.log("No severe weather — all clear")
    return "all clear"


def morning_report(config: ForecastConfig, rc: RunContext) -> None:
    """Run the full morning weather pipeline."""
    rc.track_phase("forecast", "Fetching forecast", RunStatus.RUNNING)
    rc.invoke("forecast", city=config.city, days=config.days)
    rc.track_phase("forecast", "Forecast retrieved", RunStatus.SUCCESS)

    rc.track_phase("alerts", "Checking alerts", RunStatus.RUNNING)
    rc.invoke("alert", city=config.city)
    rc.track_phase("alerts", "Alerts checked", RunStatus.SUCCESS)

    rc.log("Morning report complete")
