"""Tests for the weather_tools MCP example: the visibility contract."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent))

from jobs import ForecastConfig, forecast, purge_cache, refresh, travel_advice


def test_external_jobs_carry_full_metadata():
    for job in (forecast, travel_advice):
        decl = job.__functualize_job__
        assert decl.visibility == "external"
        assert decl.extra_description
        assert "weather" in decl.tags


def test_internal_job_is_marked_hidden():
    assert purge_cache.__functualize_job__.visibility == "internal"


def test_unannotated_job_has_no_declaration():
    assert not hasattr(refresh, "__functualize_job__")


def test_jobs_run_directly():
    rc = MagicMock()
    assert "Tokyo" in forecast(ForecastConfig(city="Tokyo"), rc)
    assert "Tokyo" in travel_advice(ForecastConfig(city="Tokyo"), rc)
