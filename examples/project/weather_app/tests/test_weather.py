"""Tests for the weather app jobs."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add the src directory so we can import the jobs directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from weather_app.jobs.weather import ForecastConfig, alert, forecast, morning_report


def _make_rc() -> MagicMock:
    """Create a minimal mock RunContext for testing."""
    return MagicMock()


def test_forecast_returns_summary():
    config = ForecastConfig(city="Tokyo", days=5)
    result = forecast(config, _make_rc())
    assert "Tokyo" in result
    assert "5 days" in result


def test_forecast_uses_configured_api_url():
    rc = _make_rc()
    config = ForecastConfig(city="Paris", api_url="https://api.prod.example.com")
    forecast(config, rc)
    logged = " ".join(str(call) for call in rc.log.call_args_list)
    assert "https://api.prod.example.com" in logged


def test_alert_all_clear():
    config = ForecastConfig(city="Tokyo")
    assert alert(config, _make_rc()) == "all clear"


def test_morning_report_invokes_pipeline():
    rc = _make_rc()
    config = ForecastConfig(city="Tokyo", days=5)
    morning_report(config, rc)
    invoked = [call.args[0] for call in rc.invoke.call_args_list]
    assert invoked == ["forecast", "alert"]
    assert rc.track_phase.call_count == 4
