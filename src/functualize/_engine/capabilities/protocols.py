"""Protocol definitions for the context module.

Defines the structural typing contracts for state storage backends.
Any class implementing these methods can be used as a state store,
enabling replacement with persistent backends (e.g., SQLite).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["StateStoreProtocol"]


@runtime_checkable
class StateStoreProtocol(Protocol):
    """Runtime-checkable protocol defining the key-value state storage contract.

    Any object satisfying this protocol can serve as the backing state store
    for a WorkflowScope. The in-memory StateStore satisfies this by default;
    plugins (e.g., SQLiteStateStore) can provide persistent implementations.

    Methods provide basic CRUD, cross-job namespace access, and bulk operations.
    """

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key, returning default if not found."""
        ...

    def set(self, key: str, value: Any) -> None:
        """Store a value under the given key."""
        ...

    def delete(self, key: str) -> None:
        """Remove a key from the store. No-op if key doesn't exist."""
        ...

    def keys(self) -> list[str]:
        """Return all stored key names."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of all state as a plain dict."""
        ...

    def clear(self) -> None:
        """Remove all stored state."""
        ...

    def get_job_state(self, job_name: str, key: str, default: Any = None) -> Any:
        """Read a value from another job's namespace.

        Args:
            job_name: The job namespace to read from.
            key: The state key within that namespace.
            default: Value to return if key not found.

        Returns:
            The stored value, or default if not found.
        """
        ...

    def list_job_namespaces(self) -> list[str]:
        """Return all job namespaces that have stored state."""
        ...
