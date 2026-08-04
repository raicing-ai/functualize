"""Tests for the summarize example."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent))

from summarize import SummarizeConfig, Summary, run


def test_returns_structured_summary():
    config = SummarizeConfig(text="Functualize is a CLI framework", max_points=2)
    summary = run(config, MagicMock())
    assert isinstance(summary, Summary)
    assert len(summary.bullet_points) == 2
