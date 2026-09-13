"""Shared fixtures for the context tests.

`new_state_store` moved to `tests/_state_support.py` once four directories
needed it; re-exported here so the existing imports keep working and there is
still one implementation.
"""

from __future__ import annotations

from tests._state_support import new_state_store

__all__ = ["new_state_store"]
