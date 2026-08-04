"""Step 6: Expose jobs to AI agents via MCP.

Mirrors README Quick Start Step 6: mark jobs for external visibility with
``@job``, then serve them as MCP tools (requires functualize-mcp):

    cd examples/quickstart/step6_mcp
    func mcp serve

Jobs with ``visibility="external"`` become MCP tools that agents like
Claude can discover and call; ``visibility="internal"`` jobs stay hidden.
"""

from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job


class ForecastConfig(BaseModel):
    """Configuration for weather jobs."""

    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")


@job(
    extra_description="Get a weather forecast for a city",
    visibility="external",
    tags=["weather", "safe"],
)
def forecast(config: ForecastConfig, rc: RunContext) -> str:
    """Fetch the weather forecast for the configured city."""
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    return f"{config.city}: 24°C, sunny for the next {config.days} days"


@job(
    extra_description="Purge the local forecast cache",
    visibility="internal",
)
def purge_cache(rc: RunContext) -> str:
    """Internal maintenance job — hidden from MCP agents."""
    rc.log("Purging forecast cache...")
    return "cache purged"
