"""Tests for Step 5: AI with structured output (MockAI, no API keys)."""

from unittest.mock import MagicMock

from weather import ForecastConfig, TravelPlan, forecast, travel_plan


def _make_rc():
    """Create a minimal mock RunContext."""
    rc = MagicMock()
    rc.log = MagicMock()
    return rc


def test_forecast_returns_summary():
    result = forecast(ForecastConfig(city="Tokyo", days=5), _make_rc())
    assert "Tokyo" in result


def test_travel_plan_returns_structured_output():
    plan = travel_plan(ForecastConfig(city="Tokyo"), _make_rc())
    assert isinstance(plan, TravelPlan)
    assert plan.destination == "Tokyo"
    assert plan.best_days == ["Saturday", "Sunday"]


def test_travel_plan_logs_packing_tips():
    rc = _make_rc()
    travel_plan(ForecastConfig(city="Paris"), rc)
    logged = " ".join(str(call) for call in rc.log.call_args_list)
    assert "sunscreen" in logged
