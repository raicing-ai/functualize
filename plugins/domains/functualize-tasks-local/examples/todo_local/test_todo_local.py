"""Tests for the todo_local example."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent))

from todo_local import checklist


def test_one_item_remains_open():
    assert checklist(MagicMock()) == 1
