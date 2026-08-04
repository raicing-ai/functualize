"""Tests for the counter example."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent))

import counter


def test_counter_increments_across_runs():
    rc = MagicMock()
    first = counter.bump(rc)
    second = counter.bump(rc)
    assert second == first + 1


def test_namespace_isolates_keys():
    # The raw backend key carries the namespace prefix
    assert counter._backend.get("counter:runs") is not None
    assert counter._backend.get("runs") is None
