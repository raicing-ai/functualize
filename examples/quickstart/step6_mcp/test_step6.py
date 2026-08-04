"""Tests for Step 6: the MCP visibility metadata contract.

The MCP server itself is exercised manually (`func mcp serve` — see the
module docstring); these tests prove the metadata the server consumes.
"""

from unittest.mock import MagicMock

from weather import ForecastConfig, forecast, purge_cache


def test_forecast_marked_external():
    decl = forecast.__functualize_job__
    assert decl.visibility == "external"
    assert decl.extra_description == "Get a weather forecast for a city"
    assert "weather" in decl.tags


def test_purge_cache_marked_internal():
    decl = purge_cache.__functualize_job__
    assert decl.visibility == "internal"


def test_jobs_still_run_directly():
    rc = MagicMock()
    assert "Tokyo" in forecast(ForecastConfig(city="Tokyo"), rc)
    assert purge_cache(rc) == "cache purged"
