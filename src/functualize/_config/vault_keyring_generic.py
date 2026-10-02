"""The fail-safe adapter for a ``keyring`` backend nobody has proven silent.

``keyring`` supports many backends beyond the three platform keyrings this
package has adapters for. Whether any of them can be read without raising a
prompt is unknown, and a run must never create one. So for a backend that is
not on the allowlist a run **does not read at all**:
:meth:`GenericAdapter.read_silent` answers UNVERIFIED, which the refusal turns
into "this keyring cannot be read without a possible prompt" with the two ways
round it (``FUNCTUALIZE_VAULT_KEY``, or ``func builtin vault unlock``).

:meth:`GenericAdapter.unlock` reads once through ``keyring`` in the
foreground. The backend may prompt; that is acceptable there, because a person
ran the command and is present to answer.
"""

from __future__ import annotations

from typing import Any

from functualize._config.vault_keyring import AdapterOutcome, AdapterRead, UnlockHow
from functualize._types.enums import KeyAvailability

__all__ = ["GenericAdapter"]


class GenericAdapter:
    """A keyring backend that cannot be read without a possible prompt."""

    def __init__(self, service: str, account: str, *, backend: Any) -> None:
        """Initialise the adapter.

        Args:
            service: The ``keyring`` service name.
            account: The ``keyring`` username.
            backend: The active ``keyring`` backend, or None when there is none.
        """
        self._service = service
        self._account = account
        self._backend = backend

    @property
    def name(self) -> str:
        return "keyring"

    def read_silent(self) -> AdapterRead:
        """Refuse to read: silence cannot be proven for this backend."""
        if self._backend is None:
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        return AdapterRead(AdapterOutcome.UNVERIFIED)

    def state(self) -> KeyAvailability:
        """Unknown: there is no way to ask this backend without reading it."""
        return KeyAvailability.UNKNOWN

    def unlock(self) -> AdapterRead:
        """Read once in the foreground — the backend may prompt; a person is there."""
        if self._backend is None:
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        try:
            from keyring.errors import KeyringLocked
        except ImportError:
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        try:
            secret = self._backend.get_password(self._service, self._account)
        except KeyringLocked:
            return AdapterRead(AdapterOutcome.LOCKED, how=UnlockHow.CANCELLED)
        except Exception:  # noqa: BLE001 - a failing backend is no keyring reachable
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        if secret is None:
            return AdapterRead(AdapterOutcome.NOT_STORED, how=UnlockHow.UNLOCKED_NOW)
        return AdapterRead(
            AdapterOutcome.FOUND, secret=str(secret), how=UnlockHow.UNLOCKED_NOW
        )
