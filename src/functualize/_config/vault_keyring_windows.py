"""The Windows keyring adapter: Credential Manager, which has no lock to prompt for.

Credentials are read with ``CredRead`` through ``keyring``'s Windows backend.
Credential Manager is unlocked whenever the user is logged in, so there is no
locked state for a read to wait on and no dialog for it to raise: a read is
silent by construction. :meth:`WindowsCredentialAdapter.unlock` therefore has
nothing to do and says so.

``keyring``'s Windows backend (and the ``win32ctypes`` it needs) is imported
lazily and only when the adapter is used, so nothing here loads elsewhere.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol

from functualize._config.vault_keyring import AdapterOutcome, AdapterRead, UnlockHow
from functualize._types.enums import KeyAvailability

__all__ = ["BackendLoader", "WindowsCredentialAdapter"]


class BackendLoader(Protocol):
    """Produces the ``keyring`` Windows backend, or None where it cannot load."""

    def load(self) -> Any | None: ...


class _KeyringWindowsLoader:
    def load(self) -> Any | None:
        # Through importlib: neither module ships type information. The backend
        # module imports even where its dependency is missing; importing the
        # dependency first is what tells.
        try:
            importlib.import_module("win32ctypes.pywin32.win32cred")
        except ImportError:
            return None
        try:
            backend_module = importlib.import_module("keyring.backends.Windows")
            return backend_module.WinVaultKeyring()
        except Exception:  # noqa: BLE001 - an unloadable backend is no keyring
            return None


class WindowsCredentialAdapter:
    """The vault key in Windows Credential Manager."""

    def __init__(
        self, service: str, account: str, *, loader: BackendLoader | None = None
    ) -> None:
        self._service = service
        self._account = account
        self._loader: BackendLoader = loader or _KeyringWindowsLoader()
        self._backend: Any = None
        self._loaded = False

    @property
    def name(self) -> str:
        return "windows"

    def read_silent(self) -> AdapterRead:
        """``CredRead``: no lock model, so this never prompts."""
        backend = self._load()
        if backend is None:
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        try:
            secret = backend.get_password(self._service, self._account)
        except Exception:  # noqa: BLE001 - a failing Credential Manager is no keyring reachable
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        if secret is None:
            return AdapterRead(AdapterOutcome.NOT_STORED)
        return AdapterRead(AdapterOutcome.FOUND, secret=str(secret))

    def state(self) -> KeyAvailability:
        """Unlocked whenever Credential Manager is there; it cannot be locked."""
        return (
            KeyAvailability.UNLOCKED
            if self._load() is not None
            else KeyAvailability.UNKNOWN
        )

    def unlock(self) -> AdapterRead:
        """Nothing to unlock: read, and say there was nothing to do."""
        read = self.read_silent()
        if read.outcome is AdapterOutcome.NO_KEYRING:
            return read
        return AdapterRead(
            read.outcome, secret=read.secret, how=UnlockHow.NOTHING_TO_UNLOCK
        )

    def _load(self) -> Any | None:
        if not self._loaded:
            self._backend = self._loader.load()
            self._loaded = True
        return self._backend
