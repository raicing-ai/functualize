"""Tests for Step 3: invoke and workflow step tracking.

Tests individual functions directly (unit tests) and verifies
the invoke + step tracking behavior via the execution engine.
"""

from unittest.mock import MagicMock

from weather import ForecastConfig, alert, forecast


def _make_rc():
    """Create a minimal mock RunContext."""
    rc = MagicMock()
    rc.log = MagicMock()
    return rc


# --- Unit tests for individual jobs ---


def test_forecast_returns_string():
    """forecast() returns a formatted forecast string."""
    rc = _make_rc()
    config = ForecastConfig(city="Tokyo", days=5)
    result = forecast(config, rc)
    assert "Tokyo" in result
    assert "24°C" in result


def test_alert_returns_no_alerts():
    """alert() returns no_alerts status."""
    rc = _make_rc()
    config = ForecastConfig(city="Tokyo")
    result = alert(config, rc)
    assert result == "no_alerts"


def test_alert_logs_check():
    """alert() logs that it checked conditions."""
    rc = _make_rc()
    config = ForecastConfig(city="Paris")
    alert(config, rc)
    rc.log.assert_any_call("Checking alert conditions...")


# --- Integration test: invoke via FunctualizeApp ---


def test_morning_report_invokes_sub_jobs():
    """morning_report() invokes forecast and alert via rc.invoke().

    This test uses the real execution engine to verify cross-function
    invoke works when jobs are in the same directory.
    """
    from pathlib import Path

    from functualize.app import FunctualizeApp, JobSources

    # Point job_sources at this directory so all functions are registered
    this_dir = str(Path(__file__).parent)
    app = FunctualizeApp(
        name="test-quickstart-step3",
        job_sources=JobSources(directories=[this_dir]),
    )

    # Execute via the engine — config fields are passed as kwargs and the
    # engine resolves them into the Pydantic model
    result = app.execute("morning_report", city="Tokyo", days=3)

    assert result is not None
    if result.status.value != "Success":
        print(f"RESULT: {result}")
    assert result.status.value == "Success"


def test_forecast_via_engine():
    """forecast() can be executed through the engine directly."""
    from pathlib import Path

    from functualize.app import FunctualizeApp, JobSources

    this_dir = str(Path(__file__).parent)
    app = FunctualizeApp(
        name="test-quickstart-step3-forecast",
        job_sources=JobSources(directories=[this_dir]),
    )

    result = app.execute("forecast", city="Paris", days=5)

    assert result is not None
    assert result.status.value == "Success"
