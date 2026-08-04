"""Step 2: Typed configuration — Pydantic models become CLI options.

Run with:
    func weather.py forecast --city Tokyo --days 5
    func weather.py forecast --city Paris --days 7 --api-url https://custom.api.com
"""

from pydantic import BaseModel, Field

from functualize.job import RunContext


class ForecastConfig(BaseModel):
    """Configuration for the forecast job."""

    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")
    api_url: str = Field(
        default="https://weather.example.com",
        description="Weather API endpoint",
    )


def forecast(config: ForecastConfig, rc: RunContext) -> str:
    """Fetch weather forecast for a city."""
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    rc.log(f"Using API: {config.api_url}")
    result = f"{config.city}: 24°C, sunny for the next {config.days} days"
    rc.log(result)
    return result
