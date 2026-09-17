"""Jobs exposed as MCP tools — visibility and metadata reference.

Serve with:
    func mcp serve

`forecast` and `travel_advice` become MCP tools; `purge_cache` stays
hidden (visibility="internal"); `refresh` has no metadata and defaults
to hidden as well.
"""

from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job


class ForecastConfig(BaseModel):
    """Configuration for weather jobs — becomes the MCP tool's input schema."""

    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")


@job(
    extra_description="Get a weather forecast for a city",
    category="weather",
    examples=["forecast --city Tokyo --days 5"],
    tags=["weather", "safe", "read-only"],
    visibility="external",
)
def forecast(config: ForecastConfig, rc: RunContext) -> str:
    """Fetch the weather forecast for the configured city."""
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    return f"{config.city}: 24°C, sunny for the next {config.days} days"


@job(
    extra_description="Advise whether the weather suits outdoor travel plans",
    category="weather",
    tags=["weather", "advice"],
    visibility="external",
)
def travel_advice(config: ForecastConfig, rc: RunContext) -> str:
    """Turn the forecast into a go/no-go travel recommendation."""
    rc.log(f"Evaluating travel conditions for {config.city}...")
    return f"{config.city} looks great for outdoor plans this week"


@job(
    extra_description="Purge the local forecast cache",
    visibility="internal",
)
def purge_cache(rc: RunContext) -> str:
    """Internal maintenance — hidden from MCP agents."""
    rc.log("Purging forecast cache...")
    return "cache purged"


def refresh(rc: RunContext) -> str:
    """No metadata at all — also not exposed as an MCP tool."""
    rc.log("Refreshing data sources...")
    return "refreshed"
