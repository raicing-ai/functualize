"""Tests for the todo example."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent))

from todo import plan_release


def test_completed_task_leaves_the_list():
    remaining = plan_release(MagicMock())
    assert remaining == ["Run smoke tests", "Tag release"]
