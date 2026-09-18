"""Where the AI SDK keeps budget counters and checkpoints: in memory, always.

**There is no persistent alternative, and this module used to say there was.**
It described itself as a *fallback* for when "the State domain
(functualize-state) is not installed", and told the user to *"install
functualize-state-sqlite for persistent storage"*. Both halves are false:

- `functualize-state` was **removed** by
  `contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md`, so it
  cannot be installed. There is no state domain to be absent.
- The sqlite plugin — now `functualize-substrate-sqlite` — installs a
  `StoreSubstrate`. It does not provide the `StateBackend` this module wants,
  so installing it changes nothing here. The advice sent a user to fetch a
  package that could not satisfy the need it named.

`plugin-taxonomy`/T9 makes the documentation match the code rather than the
other way round, which is the choice `spec.md` D.1-4 offers: *"its
budget/checkpoint state either uses the app's substrate or is honestly
documented as ephemeral."* Moving it onto the substrate is a real feature — the
counters would need a document, a key and a discard rule — and is not something
to smuggle in under a doc fix.

So: **AI budget tracking and checkpoints live for the length of the process.**
That is a limitation, stated once, where a reader will find it.

`StrictStateBackendWrapper` survives because the distinction it draws still
matters: a store that is *present and failing* must raise rather than silently
degrade, so a caller cannot mistake a broken backend for an absent one.
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

#: Said once, and without an instruction the user cannot act on. The previous
#: text ended "Install functualize-state-sqlite for persistent storage", which
#: named a plugin that provides a `StoreSubstrate` rather than the `StateBackend`
#: this module uses — so following it changed nothing.
_EPHEMERAL_WARNING = (
    "[functualize-ai] AI budget tracking and checkpoint data are kept in "
    "memory and do not survive the process. There is no persistent backend "
    "for them today."
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
        state_backend: A backend the app provided, or None when it has none.
            It used to mean "is the `functualize-state` domain installed",
            which `store-substrate`/T6 retired; it now means what it says.

    Returns:
        A state backend (either StrictStateBackendWrapper or EphemeralStateBackend)
        suitable for the AI plugin's own prefixed keys.

    Side Effects:
        Emits a WARNING log when falling back to ephemeral storage.
    """
    if state_backend is not None:
        # State domain IS installed — wrap strictly so runtime errors propagate
        return StrictStateBackendWrapper(state_backend)

    # State domain NOT installed — fall back to ephemeral in-memory store
    logger.warning(_EPHEMERAL_WARNING)
    return EphemeralStateBackend()
