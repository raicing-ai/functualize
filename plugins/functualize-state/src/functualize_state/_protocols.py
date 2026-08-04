"""Protocol definitions for the State Domain SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from functualize_state._types import ExecutionRecord, PhaseRecord


@runtime_checkable
class StateBackend(Protocol):
    """Backend-agnostic key-value state operations."""

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value by key, returning default if not found."""
        ...

    def set(self, key: str, value: Any) -> None:
        """Set a value for a key."""
        ...

    def delete(self, key: str) -> None:
        """Delete a key from the state backend."""
        ...

    def keys(self, prefix: str = "") -> list[str]:
        """Return all keys, optionally filtered by prefix."""
        ...


@runtime_checkable
class ExecutionStore(Protocol):
    """Backend-agnostic execution record persistence operations."""

    def insert_execution(self, record: ExecutionRecord) -> str:
        """Insert an execution record, returning the execution ID."""
        ...

    def update_execution(self, execution_id: str, **updates: Any) -> None:
        """Update fields on an existing execution record."""
        ...

    def get_session_executions(
        self, session_id: str, limit: int = 50
    ) -> list[ExecutionRecord]:
        """Get execution records for a session, limited by count."""
        ...

    def insert_phase(self, execution_id: str, phase: PhaseRecord) -> None:
        """Insert a phase record for an execution."""
        ...

    def get_execution_phases(self, execution_id: str) -> list[PhaseRecord]:
        """Get all phase records for an execution."""
        ...
