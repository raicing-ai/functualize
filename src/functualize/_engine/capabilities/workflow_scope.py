"""Workflow scope module providing a logical grouping of job executions.

A WorkflowScope groups job executions that share a StateStore, enabling
cross-job state persistence. It is a generic building block — not coupled
to any orchestration provider. Orchestration plugins consume this primitive
to implement durable workflows.
"""

from __future__ import annotations

from typing import Any

from functualize._engine.capabilities.protocols import StateStoreProtocol
from functualize._engine.capabilities.state_store import StateStore

__all__ = ["WorkflowScope"]


class WorkflowScope:
    """Logical grouping of job executions sharing state.

    A generic building block — not coupled to any orchestration provider.
    Orchestration plugins consume this primitive to implement durable
    workflows.

    Args:
        scope_id: Unique identifier for this workflow scope.
        metadata: Optional provider-specific metadata (e.g., remote
            workflow ID, run URL).
    """

    __slots__ = ("_scope_id", "_state_store", "_metadata", "_closed")

    def __init__(
        self, scope_id: str, *, metadata: dict[str, Any] | None = None
    ) -> None:
        self._scope_id = scope_id
        self._state_store: StateStoreProtocol = StateStore()
        self._metadata: dict[str, Any] = metadata or {}
        self._closed = False

    @property
    def scope_id(self) -> str:
        """The unique identifier for this workflow scope."""
        return self._scope_id

    @property
    def state_store(self) -> StateStoreProtocol:
        """The shared state store for this scope."""
        return self._state_store

    @property
    def metadata(self) -> dict[str, Any]:
        """Provider-specific metadata attached at creation time."""
        return self._metadata

    @property
    def closed(self) -> bool:
        """Whether this scope has been closed."""
        return self._closed

    def replace_state_store(self, store: Any) -> None:
        """Replace the backing state store with a new implementation.

        The new store must satisfy StateStoreProtocol. No data migration
        is performed — the new store starts empty (or with whatever data
        it already contains).

        Args:
            store: An object satisfying StateStoreProtocol.

        Raises:
            InvalidStateTransitionError: If the scope is already closed.
            TypeError: If the store does not satisfy StateStoreProtocol,
                indicating which required methods are missing.
        """
        from functualize._engine.capabilities.runcontext import (
            InvalidStateTransitionError,
        )

        if self._closed:
            raise InvalidStateTransitionError(
                f"Workflow scope '{self._scope_id}' is closed; "
                "cannot replace state store"
            )

        # Validate protocol compliance
        if not isinstance(store, StateStoreProtocol):
            # Determine which methods are missing
            required_methods = [
                "get",
                "set",
                "delete",
                "keys",
                "to_dict",
                "clear",
                "get_job_state",
                "list_job_namespaces",
            ]
            missing = [
                m
                for m in required_methods
                if not hasattr(store, m) or not callable(getattr(store, m))
            ]
            raise TypeError(
                f"State store does not satisfy StateStoreProtocol. "
                f"Missing methods: {missing}"
            )

        self._state_store = store

    def close(self) -> None:
        """Mark scope as completed and close the underlying StateStore.

        Prevents further state mutations via the shared StateStore.

        Raises:
            InvalidStateTransitionError: If the scope is already closed.
        """
        from functualize._engine.capabilities.runcontext import (
            InvalidStateTransitionError,
        )

        if self._closed:
            raise InvalidStateTransitionError(
                f"Workflow scope '{self._scope_id}' is already closed"
            )
        self._closed = True
        # Only call _close() if the store has it (in-memory StateStore does)
        if hasattr(self._state_store, "_close"):
            self._state_store._close()
