"""Tests for Step 4: the jobs behind the inline TUI walkthrough.

The TUI itself is exercised manually (see README.md in this directory);
these tests prove the jobs it browses are correct.
"""

from unittest.mock import MagicMock

from weather import (
    CompareConfig,
    ForecastConfig,
    TemperatureUnit,
    compare,
    forecast,
    report,
)


def _make_rc():
    """Create a minimal mock RunContext."""
    rc = MagicMock()
    rc.log = MagicMock()
    return rc


def test_report_needs_no_args():
    assert report(_make_rc()) == "24°C, sunny"


def test_forecast_requires_city():
    result = forecast(ForecastConfig(city="Tokyo", days=5), _make_rc())
    assert "Tokyo" in result
    assert "5 days" in result


def test_compare_uses_enum_unit():
    config = CompareConfig(city_a="Tokyo", city_b="Oslo")
    assert config.unit is TemperatureUnit.celsius
    result = compare(config, _make_rc())
    assert "Tokyo" in result
