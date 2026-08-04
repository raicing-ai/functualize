"""Tests for the pipeline example (the jobs flow-viz visualizes)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent))

from jobs import ForecastConfig, morning_report


def test_pipeline_emits_invokes_and_phases():
    rc = MagicMock()
    morning_report(ForecastConfig(city="Tokyo"), rc)
    invoked = [call.args[0] for call in rc.invoke.call_args_list]
    assert invoked == ["forecast", "alert"]
    assert rc.track_phase.call_count == 4
