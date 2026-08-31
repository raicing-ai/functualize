"""State capability — per-invocation key-value store.

Provides a simple dict-backed state store for job functions.
Each job invocation receives its own State instance, ensuring
isolation between invocations.
"""

from __future__ import annotations

from typing import Any

from functualize._engine.capabilities.spec import CapabilitySpec


class State:
    """Per-invocation key-value state store.

    Backed by a plain dict. Values should be JSON-serializable to
    support future persistence backends.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key, returning default if not found.

        Args:
            key: The state key to look up.
            default: Value to return if key is not present.

        Returns:
            The stored value, or default.
        """
        return self._store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Store a value by key.

        Args:
            key: The state key.
            value: The value to store (should be JSON-serializable).
        """
        self._store[key] = value

    def delete(self, key: str) -> None:
        """Remove a key from state. No-op if key doesn't exist.

        Args:
            key: The state key to remove.
        """
        self._store.pop(key, None)

    def keys(self, prefix: str = "") -> list[str]:
        """Return stored keys, optionally filtered by prefix.

        Args:
            prefix: If non-empty, only keys starting with this prefix
                are returned (case-sensitive). Default "" returns all.

        Returns:
            List of matching keys (unordered).

        Raises:
            TypeError: If prefix is not a string.
        """
        if not isinstance(prefix, str):
            raise TypeError(f"prefix must be a str, got {type(prefix).__name__}")
        if not prefix:
            return list(self._store.keys())
        return [k for k in self._store if k.startswith(prefix)]


# ── Registry entry (ADR-014) ───────────────────────────────────────────────

CAPABILITY = CapabilitySpec(
    name="State",
    type=State,
    factory=lambda ctx: State(),
)
