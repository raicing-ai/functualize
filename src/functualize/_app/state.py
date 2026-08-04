"""Thread-safe global state container for CLI-wide runtime values.

AppState provides class-level get/set/reset methods without requiring
instantiation. All operations are protected by a threading.Lock for
safe concurrent access.

This module imports ONLY from Python stdlib.
"""

from __future__ import annotations

import threading
from typing import Any, TypedDict


class AppStateKeys(TypedDict, total=False):
    """Known state keys for IDE autocompletion and static analysis."""

    config_directory: str
    environment: str
    dotenv_path: str | None


class AppState:
    """Thread-safe global state container for CLI-wide runtime values.

    Provides class-level get/set/reset methods without requiring instantiation.
    All operations are protected by a threading.Lock for safe concurrent access.
    """

    _state: dict[str, Any] = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, key: str) -> Any | None:
        """Retrieve a value by key. Returns None if the key has not been set."""
        with cls._lock:
            return cls._state.get(key)

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """Store a value by key."""
        with cls._lock:
            cls._state[key] = value

    @classmethod
    def reset(cls) -> None:
        """Remove all stored key-value pairs. Useful for testing."""
        with cls._lock:
            cls._state.clear()
