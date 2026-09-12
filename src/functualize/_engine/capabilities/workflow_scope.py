"""Workflow scope module providing a logical grouping of job executions.

A WorkflowScope groups job executions that share one scope's state, enabling
cross-job persistence. It is a generic building block — not coupled to any
orchestration provider. Orchestration plugins consume this primitive to
implement durable workflows.

**There is no `replace_state_store` any more** (`store-substrate`/T5, AC-5).
A plugin that wanted a database used to swap a key-value store in here, at a
second seam one level below the real one — which is how the split-brain in
spec §D became reachable: a scope could be given a SQLite store for the job
state while its *records* stayed on the filesystem, so a resumed run found its
steps and not its variables. The seam is the substrate now, and there is one of
it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._engine.capabilities.state import ScopeBackedStateStore

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
        state_store: The backing store. **Injected, never defaulted here.**
            It used to default to an in-memory dict, which made every scope
            built anywhere silently non-durable — and since `_scope_registry`
            is reset at boot, a resume in a new process got a fresh scope and
            an empty store while its step records came back fine. Requiring the
            caller to supply one means a scope that cannot persist is visible
            at construction instead of at the first lost write.
    """

    __slots__ = ("_scope_id", "_state_store", "_metadata", "_closed")

    def __init__(
        self,
        scope_id: str,
        *,
        metadata: dict[str, Any] | None = None,
        state_store: ScopeBackedStateStore | None = None,
    ) -> None:
        self._scope_id = scope_id
        self._state_store: ScopeBackedStateStore | None = state_store
        self._metadata: dict[str, Any] = metadata or {}
        self._closed = False

    @property
    def scope_id(self) -> str:
        """The unique identifier for this workflow scope."""
        return self._scope_id

    @property
    def state_store(self) -> ScopeBackedStateStore | None:
        """The shared state store for this scope, or None if none was given.

        None rather than an empty stand-in: `State` raises a named error on
        first use, which says where the problem is. A stand-in would accept
        writes nothing will ever read.
        """
        return self._state_store

    @property
    def metadata(self) -> dict[str, Any]:
        """Provider-specific metadata attached at creation time."""
        return self._metadata

    @property
    def closed(self) -> bool:
        """Whether this scope has been closed."""
        return self._closed

    def close(self) -> None:
        """Mark scope as completed and close the underlying FreshStore.

        Prevents further state mutations via the shared FreshStore.

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
        # Optional on the protocol: a store that wants to seal itself against
        # further writes may say so. The durable default has nothing to seal —
        # `scopes.json` is written per call — and a plugin backend may want to
        # drop a connection, so this stays a capability the store opts into
        # rather than a method every implementation must carry.
        closer = getattr(self._state_store, "_close", None)
        if closer is not None:
            closer()
