"""SQLite-backed state store implementing StateStoreProtocol.

Provides persistent key-value state storage per job namespace, backed by
the SQLiteBackend's state table. Values are JSON-serialized for storage;
non-serializable values are replaced with a type-indicating placeholder.

Each SQLiteStateStore instance is scoped to a specific scope_id and
job_namespace, providing namespace isolation per job.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize_state_sqlite.sqlite_backend import SQLiteBackend

__all__ = ["SQLiteStateStore"]

logger = logging.getLogger(__name__)

_NON_SERIALIZABLE_TEMPLATE = "<non-serializable: {type_name}>"


def _serialize_value(value: Any) -> str:
    """Serialize a value to JSON string.

    If the value cannot be serialized, returns a JSON-encoded placeholder
    string containing the type name (Requirement 23.10).

    Args:
        value: Any Python value to serialize.

    Returns:
        A JSON string representation of the value.
    """
    try:
        return json.dumps(value)
    except (TypeError, ValueError, OverflowError):
        type_name = type(value).__name__
        placeholder = _NON_SERIALIZABLE_TEMPLATE.format(type_name=type_name)
        return json.dumps(placeholder)


def _deserialize_value(value_json: str) -> Any:
    """Deserialize a JSON string back to a Python value.

    Args:
        value_json: JSON string to deserialize.

    Returns:
        The deserialized Python value.
    """
    return json.loads(value_json)


class SQLiteStateStore:
    """StateStoreProtocol implementation backed by SQLite.

    Each instance is scoped to a specific (scope_id, job_namespace) pair,
    providing namespace isolation between jobs. All values are persisted
    immediately to the database on write.

    Args:
        backend: The SQLiteBackend instance managing the database connection.
        scope_id: The workflow scope identifier for state isolation.
        job_namespace: The job namespace (typically the job name) for this store.
    """

    def __init__(
        self,
        backend: SQLiteBackend,
        scope_id: str,
        job_namespace: str,
    ) -> None:
        self._backend = backend
        self._scope_id = scope_id
        self._job_namespace = job_namespace

    @property
    def scope_id(self) -> str:
        """The workflow scope identifier."""
        return self._scope_id

    @property
    def job_namespace(self) -> str:
        """The job namespace for this store instance."""
        return self._job_namespace

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key from the current job's namespace.

        Args:
            key: The state key to look up.
            default: Value to return if key not found.

        Returns:
            The deserialized value, or default if not found.
        """
        value_json = self._backend.get_state(self._scope_id, self._job_namespace, key)
        if value_json is None:
            return default
        return _deserialize_value(value_json)

    def set(self, key: str, value: Any) -> None:
        """Store a value under the given key in the current job's namespace.

        The value is immediately persisted to the database as JSON.
        Non-serializable values are stored as a placeholder string
        containing the type name.

        Args:
            key: The state key.
            value: The value to store (will be JSON-serialized).
        """
        value_json = _serialize_value(value)
        self._backend.upsert_state(self._scope_id, self._job_namespace, key, value_json)

    def delete(self, key: str) -> None:
        """Remove a key from the current job's namespace.

        No-op if the key doesn't exist.

        Args:
            key: The state key to delete.
        """
        self._backend.delete_state(self._scope_id, self._job_namespace, key)

    def keys(self) -> list[str]:
        """Return all stored key names in the current job's namespace.

        Returns:
            List of key strings.
        """
        return self._backend.get_namespace_keys(self._scope_id, self._job_namespace)

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of all state as a plain dict for the current namespace.

        Returns:
            Dict mapping keys to their deserialized values.
        """
        raw = self._backend.get_namespace_state(self._scope_id, self._job_namespace)
        return {key: _deserialize_value(value_json) for key, value_json in raw.items()}

    def clear(self) -> None:
        """Remove all stored state in the current job's namespace."""
        self._backend.clear_namespace_state(self._scope_id, self._job_namespace)

    def get_job_state(self, job_name: str, key: str, default: Any = None) -> Any:
        """Read a value from another job's namespace.

        Provides cross-job state access for coordination between jobs
        within the same workflow scope.

        Args:
            job_name: The job namespace to read from.
            key: The state key within that namespace.
            default: Value to return if key not found.

        Returns:
            The deserialized value from the specified job's namespace,
            or default if not found.
        """
        value_json = self._backend.get_state(self._scope_id, job_name, key)
        if value_json is None:
            return default
        return _deserialize_value(value_json)

    def list_job_namespaces(self) -> list[str]:
        """Return all job namespaces that have stored state in this scope.

        Returns:
            List of job namespace strings.
        """
        return self._backend.list_namespaces(self._scope_id)
