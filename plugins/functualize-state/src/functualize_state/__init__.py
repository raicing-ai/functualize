"""functualize-state: State Domain SDK for state persistence and execution tracking.

Provides well-defined protocols for state persistence and execution tracking,
enabling custom storage backend implementations without coupling to SQLite.
"""

from functualize_state._errors import KeyNotFoundError, StateNotAvailableError
from functualize_state._events import (
    STATE_EXECUTION_COMPLETED,
    STATE_EXECUTION_STARTED,
    STATE_PHASE_CHANGED,
)
from functualize_state._metadata import DomainMetadata, domain_metadata
from functualize_state._namespace import StateNamespace
from functualize_state._protocols import ExecutionStore, StateBackend
from functualize_state._types import ExecutionRecord, PhaseRecord, SessionRecord
from functualize_state.testing._in_memory import InMemoryState

__all__ = [
    # Protocols
    "StateBackend",
    "ExecutionStore",
    # Utility
    "StateNamespace",
    # Types
    "ExecutionRecord",
    "PhaseRecord",
    "SessionRecord",
    # Errors
    "StateNotAvailableError",
    "KeyNotFoundError",
    # Event Constants
    "STATE_EXECUTION_STARTED",
    "STATE_EXECUTION_COMPLETED",
    "STATE_PHASE_CHANGED",
    # Testing Doubles
    "InMemoryState",
    # Metadata
    "DomainMetadata",
    "domain_metadata",
]
