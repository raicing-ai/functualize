"""Tests for Step 1: basic job with RunContext."""

from unittest.mock import MagicMock

from weather import forecast


def _make_rc():
    """Create a minimal mock RunContext."""
    rc = MagicMock()
    rc.log = MagicMock()
    return rc


def test_forecast_returns_result():
    """forecast() returns a weather string."""
    rc = _make_rc()
    result = forecast(rc)
    assert result == "24°C, sunny"


def test_forecast_logs_messages():
    """forecast() logs two messages via rc.log()."""
    rc = _make_rc()
    forecast(rc)
    assert rc.log.call_count == 2
    rc.log.assert_any_call("Fetching forecast...")
    rc.log.assert_any_call("Tomorrow: 24°C, sunny")
