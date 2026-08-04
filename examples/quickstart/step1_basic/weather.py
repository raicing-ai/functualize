"""Step 1: Run a Python script — the simplest functualize job.

Run with:
    func weather.py forecast
"""

from functualize.job import RunContext


def forecast(rc: RunContext) -> str:
    """Check today's weather forecast."""
    rc.log("Fetching forecast...")
    rc.log("Tomorrow: 24°C, sunny")
    return "24°C, sunny"
