"""StateNamespace utility for prefix-scoped state operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize_state._protocols import StateBackend


class StateNamespace:
    """Prefix-scoped view over a StateBackend.

    All key operations are transparently prefixed, providing isolated
    read/write access to a specific key namespace within the backend.
    """

    def __init__(self, backend: StateBackend, prefix: str) -> None:
        self._backend = backend
        self._prefix = prefix

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value by key, scoped to this namespace's prefix."""
        return self._backend.get(self._prefix + key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a value for a key, scoped to this namespace's prefix."""
        self._backend.set(self._prefix + key, value)

    def delete(self, key: str) -> None:
        """Delete a key, scoped to this namespace's prefix."""
        self._backend.delete(self._prefix + key)

    def keys(self) -> list[str]:
        """Return all keys in this namespace with the prefix stripped."""
        prefix_len = len(self._prefix)
        return [k[prefix_len:] for k in self._backend.keys(self._prefix)]
