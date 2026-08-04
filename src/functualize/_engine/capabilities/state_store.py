"""State store module providing typed key-value state container.

The StateStore validates JSON-serializability at write time, supports
typed reads with runtime type checking, and can be closed to prevent
further mutations (used by WorkflowScope).
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["StateStore"]


class StateStore:
    """Typed key-value state container.

    Validates JSON-serializability at write time. Supports typed reads
    with runtime type checking. When attached to a Workflow_Scope, state
    persists across RunContext instances sharing that scope.

    When closed (via ``_close()``), mutation attempts raise
    ``InvalidStateTransitionError``.

    Also supports cross-job namespace access via ``get_job_state()``
    and ``list_job_namespaces()`` for protocol compliance.
    """

    __slots__ = ("_data", "_closed", "_job_namespaces")

    def __init__(self, *, _closed: bool = False) -> None:
        self._data: dict[str, Any] = {}
        self._closed = _closed
        self._job_namespaces: dict[str, dict[str, Any]] = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key.

        Args:
            key: The state key.
            default: Value to return if key is not found (default: None).
                For backward compatibility, if a type is passed, performs
                typed get with runtime type checking.

        Returns:
            The stored value, or default if key not found.

        Raises:
            TypeError: If default is a type and stored value is not an
                instance of that type (backward-compatible typed get).
        """
        if isinstance(default, type):
            # Backward-compatible typed get: get(key, str) style
            if key not in self._data:
                return None
            value = self._data[key]
            if not isinstance(value, default):
                raise TypeError(
                    f"State key '{key}': expected {default.__name__}, "
                    f"got {type(value).__name__}"
                )
            return value
        # Protocol-compliant get: get(key, default_value) style
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Store a value, validating JSON-serializability.

        Args:
            key: The state key.
            value: The value to store (must be JSON-serializable).

        Raises:
            TypeError: If value is not JSON-serializable.
            InvalidStateTransitionError: If the store is closed.
        """
        if self._closed:
            from functualize._engine.capabilities.runcontext import (
                InvalidStateTransitionError,
            )

            raise InvalidStateTransitionError(
                "Cannot mutate state on a closed Workflow_Scope"
            )
        # Validate JSON-serializability
        try:
            json.dumps(value)
        except (TypeError, ValueError, OverflowError) as e:
            raise TypeError(
                f"State value for key '{key}' is not JSON-serializable: {e}"
            ) from e
        self._data[key] = value

    def keys(self) -> list[str]:
        """Return list of currently stored key names."""
        return list(self._data.keys())

    def clear(self) -> None:
        """Remove all stored state.

        Raises:
            InvalidStateTransitionError: If the store is closed.
        """
        if self._closed:
            from functualize._engine.capabilities.runcontext import (
                InvalidStateTransitionError,
            )

            raise InvalidStateTransitionError(
                "Cannot mutate state on a closed Workflow_Scope"
            )
        self._data.clear()

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of all state as a plain dict."""
        return dict(self._data)

    def delete(self, key: str) -> None:
        """Remove a key from the store. No-op if key doesn't exist.

        Args:
            key: The state key to remove.

        Raises:
            InvalidStateTransitionError: If the store is closed.
        """
        if self._closed:
            from functualize._engine.capabilities.runcontext import (
                InvalidStateTransitionError,
            )

            raise InvalidStateTransitionError(
                "Cannot mutate state on a closed Workflow_Scope"
            )
        self._data.pop(key, None)

    def get_job_state(self, job_name: str, key: str, default: Any = None) -> Any:
        """Read a value from another job's namespace.

        In the in-memory implementation, job namespaces are stored in a
        separate dict keyed by job name. This enables cross-job state access
        for coordination between jobs sharing a WorkflowScope.

        Args:
            job_name: The job namespace to read from.
            key: The state key within that namespace.
            default: Value to return if key not found.

        Returns:
            The stored value, or default if not found.
        """
        namespace = self._job_namespaces.get(job_name, {})
        return namespace.get(key, default)

    def list_job_namespaces(self) -> list[str]:
        """Return all job namespaces that have stored state.

        Returns:
            List of job names that have at least one state entry.
        """
        return list(self._job_namespaces.keys())

    def _set_job_state(self, job_name: str, key: str, value: Any) -> None:
        """Store a value under a job namespace (internal use).

        Args:
            job_name: The job namespace to write to.
            key: The state key within that namespace.
            value: The value to store.

        Raises:
            InvalidStateTransitionError: If the store is closed.
        """
        if self._closed:
            from functualize._engine.capabilities.runcontext import (
                InvalidStateTransitionError,
            )

            raise InvalidStateTransitionError(
                "Cannot mutate state on a closed Workflow_Scope"
            )
        if job_name not in self._job_namespaces:
            self._job_namespaces[job_name] = {}
        self._job_namespaces[job_name][key] = value

    def _load(self, data: dict[str, Any]) -> None:
        """Load state from a dict (used by Workflow_Scope hydration).

        Replaces the current internal data with the provided dict.

        Args:
            data: Dictionary of key-value pairs to load.
        """
        self._data = dict(data)

    def _close(self) -> None:
        """Mark the store as closed (no further mutations allowed)."""
        self._closed = True
