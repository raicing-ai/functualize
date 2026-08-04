"""Tests for Step 2: typed config with Pydantic models."""

from unittest.mock import MagicMock

from weather import ForecastConfig, forecast


def _make_rc():
    """Create a minimal mock RunContext."""
    rc = MagicMock()
    rc.log = MagicMock()
    return rc


def test_forecast_with_defaults():
    """forecast() uses default values for days and api_url."""
    rc = _make_rc()
    config = ForecastConfig(city="Tokyo")
    result = forecast(config, rc)
    assert "Tokyo" in result
    assert "3 days" in result


def test_forecast_with_custom_days():
    """forecast() respects custom days parameter."""
    rc = _make_rc()
    config = ForecastConfig(city="Paris", days=5)
    result = forecast(config, rc)
    assert "Paris" in result
    assert "5 days" in result


def test_forecast_logs_api_url():
    """forecast() logs which API it's using."""
    rc = _make_rc()
    config = ForecastConfig(city="London", api_url="https://custom.api.com")
    forecast(config, rc)
    rc.log.assert_any_call("Using API: https://custom.api.com")


def test_forecast_config_validation():
    """ForecastConfig validates days range (1-7)."""
    import pytest

    with pytest.raises(ValueError):
        ForecastConfig(city="Tokyo", days=0)

    with pytest.raises(ValueError):
        ForecastConfig(city="Tokyo", days=10)
