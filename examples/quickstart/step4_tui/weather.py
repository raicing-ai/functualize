"""Step 4: Browse and run jobs interactively — the inline TUI.

Run bare `func` (no arguments) from this directory in a terminal:

    cd examples/quickstart/step4_tui
    func

Expected TUI behavior (SmartBar readiness colors):
- "report"    → green immediately (no required args) — Ctrl+Enter runs it
- "forecast"  → yellow PENDING until --city is provided, then green READY
- "compare"   → yellow with two required fields; Tab autocompletes flags,
  enum values for --unit complete on trailing space
- Ctrl+R      → config panel ring: every field with its effective value
  and where it came from (CLI / env / config file / default)
- Ctrl+E      → general panel ring: job browser, settings

Requires the CLI extra: pip install "functualize[cli]"
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from functualize.job import RunContext


class TemperatureUnit(StrEnum):
    """Temperature unit — enum values autocomplete in the SmartBar."""

    celsius = "celsius"
    fahrenheit = "fahrenheit"


class ForecastConfig(BaseModel):
    """One required field — the SmartBar stays PENDING (yellow) until set."""

    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")


class CompareConfig(BaseModel):
    """Two required fields plus an enum — exercises value completions."""

    city_a: str = Field(description="First city")
    city_b: str = Field(description="Second city")
    unit: TemperatureUnit = Field(
        default=TemperatureUnit.celsius, description="Temperature unit"
    )


def report(rc: RunContext) -> str:
    """Show the current weather report (no args — runs immediately)."""
    rc.log("Fetching current conditions...")
    rc.log("Now: 24°C, sunny, light breeze")
    return "24°C, sunny"


def forecast(config: ForecastConfig, rc: RunContext) -> str:
    """Fetch the forecast for a city (one required arg)."""
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    result = f"{config.city}: 24°C, sunny for the next {config.days} days"
    rc.log(result)
    return result


def compare(config: CompareConfig, rc: RunContext) -> str:
    """Compare the weather between two cities (two required args + enum)."""
    rc.log(f"Comparing {config.city_a} vs {config.city_b} ({config.unit.value})")
    result = f"{config.city_a} is warmer than {config.city_b} today"
    rc.log(result)
    return result
