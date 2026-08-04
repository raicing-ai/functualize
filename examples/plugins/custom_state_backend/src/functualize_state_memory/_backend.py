"""In-memory StateBackend with TTL (time-to-live) support.

This implements the StateBackend protocol from functualize-state,
adding optional key expiration — useful for caching and session data.
"""

from __future__ import annotations

import time
from typing import Any

from functualize_state import StateBackend


class MemoryTTLBackend:
    """StateBackend implementation with optional TTL on keys.

    Keys expire after `default_ttl` seconds. Set `default_ttl=None`
    for no expiration (keys persist until explicitly deleted).

    This class satisfies the StateBackend protocol:
    - get(key, default=None)
    - set(key, value)
    - delete(key)
    - keys(prefix="")
    """

    def __init__(self, default_ttl: float | None = None) -> None:
        """Initialize the backend.

        Args:
            default_ttl: Default TTL in seconds for new keys. None = no expiry.
        """
        self._store: dict[str, tuple[Any, float | None]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value, returning default if missing or expired."""
        entry = self._store.get(key)
        if entry is None:
            return default

        value, expires_at = entry
        if expires_at is not None and time.time() > expires_at:
            # Key has expired — remove and return default
            del self._store[key]
            return default

        return value

    def set(self, key: str, value: Any, ttl: float | None = ...) -> None:
        """Store a value with optional TTL override.

        Args:
            key: Storage key.
            value: Any JSON-serializable value.
            ttl: TTL in seconds. Use None for no expiry.
                 Use ... (ellipsis) to use the default_ttl.
        """
        effective_ttl = self._default_ttl if ttl is ... else ttl
        expires_at = (
            (time.time() + effective_ttl) if effective_ttl is not None else None
        )
        self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        """Remove a key from storage."""
        self._store.pop(key, None)

    def keys(self, prefix: str = "") -> list[str]:
        """List non-expired keys matching the prefix."""
        now = time.time()
        result = []
        expired = []

        for key, (_, expires_at) in self._store.items():
            if expires_at is not None and now > expires_at:
                expired.append(key)
                continue
            if key.startswith(prefix):
                result.append(key)

        # Clean up expired keys
        for key in expired:
            del self._store[key]

        return result

    @property
    def size(self) -> int:
        """Return the number of non-expired entries."""
        return len(self.keys())


# Verify protocol compliance at import time
assert isinstance(MemoryTTLBackend(), StateBackend), (
    "MemoryTTLBackend must satisfy the StateBackend protocol"
)
