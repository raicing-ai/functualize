"""AI state fallback logic for graceful degradation.

When the State domain (functualize-state) is not installed as a runtime plugin
providing a real StateBackend, the AI SDK falls back to an ephemeral in-memory
store for budget tracking and checkpoint data. A boot-time warning is emitted
to inform the user that data will not persist across sessions.

When the State domain IS installed but fails at runtime (e.g., SQLite error),
the AI SDK does NOT silently fall back — it propagates the error so the user
is aware of the issue.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = [
    "EphemeralStateBackend",
    "StrictStateBackendWrapper",
    "resolve_ai_state_backend",
]

logger = logging.getLogger(__name__)

_EPHEMERAL_WARNING = (
    "[functualize-ai] State domain is not installed. "
    "AI budget tracking and checkpoint data will be ephemeral (in-memory only) "
    "and will not persist across sessions. "
    "Install functualize-state-sqlite for persistent storage."
)


class EphemeralStateBackend:
    """In-memory state backend used as a fallback when State domain is absent.

    Satisfies the StateBackend protocol (get, set, delete, keys) using a plain
    dict. Data is lost when the process exits.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key, returning default if not found."""
        return self._store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Store a value under the given key."""
        self._store[key] = value

    def delete(self, key: str) -> None:
        """Remove a key from the store. No-op if key doesn't exist."""
        self._store.pop(key, None)

    def keys(self, prefix: str = "") -> list[str]:
        """Return all keys matching the given prefix."""
        if not prefix:
            return list(self._store.keys())
        return [k for k in self._store if k.startswith(prefix)]


class StrictStateBackendWrapper:
    """Wrapper around a real StateBackend that propagates all runtime errors.

    When the State domain IS installed, this wrapper ensures that any failure
    in the underlying backend (e.g., SQLite connection error, corruption) is
    NOT silently swallowed. Errors propagate directly to the caller.

    This implements the "fail entirely, no silent fallback" requirement.
    """

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def get(self, key: str, default: Any = None) -> Any:
        """Delegate to real backend — propagates any runtime error."""
        return self._backend.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Delegate to real backend — propagates any runtime error."""
        self._backend.set(key, value)

    def delete(self, key: str) -> None:
        """Delegate to real backend — propagates any runtime error."""
        self._backend.delete(key)

    def keys(self, prefix: str = "") -> list[str]:
        """Delegate to real backend — propagates any runtime error."""
        return self._backend.keys(prefix)


def resolve_ai_state_backend(
    state_backend: Any | None = None,
) -> Any:
    """Resolve the state backend for the AI domain.

    Determines whether to use a real StateBackend (wrapped strictly) or
    fall back to an ephemeral in-memory store.

    Args:
        state_backend: A StateBackend instance if the State domain is installed
            and has provided one, or None if State domain is absent.

    Returns:
        A state backend (either StrictStateBackendWrapper or EphemeralStateBackend)
        suitable for use with StateNamespace.

    Side Effects:
        Emits a WARNING log when falling back to ephemeral storage.
    """
    if state_backend is not None:
        # State domain IS installed — wrap strictly so runtime errors propagate
        return StrictStateBackendWrapper(state_backend)

    # State domain NOT installed — fall back to ephemeral in-memory store
    logger.warning(_EPHEMERAL_WARNING)
    return EphemeralStateBackend()


def is_state_domain_available() -> bool:
    """Check if the functualize-state package is importable.

    This is a simple availability check — it doesn't verify that a real
    StateBackend provider (e.g., functualize-state-sqlite) is actually
    registered. That check happens at boot time via the DI registry.

    Returns:
        True if functualize_state can be imported, False otherwise.
    """
    try:
        import functualize_state  # noqa: F401

        return True
    except ImportError:
        return False
