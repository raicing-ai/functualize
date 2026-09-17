"""Shared fixtures for functualize-state-sqlite plugin tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path for isolated SQLite tests."""
    return tmp_path / "test_state.db"


@pytest.fixture
def tmp_execution_db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path for execution store tests."""
    return tmp_path / "test_execution.db"
