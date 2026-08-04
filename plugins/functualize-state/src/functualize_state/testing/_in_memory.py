"""In-memory StateBackend implementation for testing."""

from __future__ import annotations

from typing import Any


class InMemoryState:
    """Dict-backed StateBackend for testing.

    Satisfies the StateBackend protocol using a plain dict as the backing store.
    Useful for unit tests and integration tests that don't need persistence.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key, returning default if not found."""
        return self._store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Store a value under the given key."""
        self._store[key] = value

    def delete(self, key: str) -> None:
        """Remove a key from the store. No-op if key doesn't exist."""
        self._store.pop(key, None)

    def keys(self, prefix: str = "") -> list[str]:
        """Return all keys matching the given prefix."""
        if not prefix:
            return list(self._store.keys())
        return [k for k in self._store if k.startswith(prefix)]
