"""The keyring port: four operations every platform adapter implements.

The vault key lives in the OS keyring, and every platform's keyring behaves
differently when it is locked. Some show a dialog on any read; one has no lock
at all. What functualize needs from all of them is the same four answers, so
the platform code sits behind one small contract and nothing above this module
knows which platform it is on:

``read_silent()``
    The key if the keyring is unlocked, otherwise a typed outcome — **never a
    prompt**. A run calls this, whether or not it has a terminal. A run must
    never create an unlock prompt: a prompt the client later abandons (a
    deadline, Ctrl-C, an agent killing its child) can crash the keyring daemon
    and re-lock every keyring the user has.
``state()``
    Locked, unlocked or unknown, answered within about a second, never a
    prompt. For status surfaces.
``store_silent(secret)``
    Write the key into an unlocked keyring — **never a prompt** either: a
    locked keyring answers LOCKED and nothing is written. ``func builtin vault
    init`` stores through this, so creating a key cannot open a dialog.
``unlock()``
    The only operation that may prompt. ``func builtin vault unlock`` calls it
    because a person asked; it waits for the prompt's own outcome and never
    cancels a prompt from the client side.

Adapters import their platform library lazily and only on their own platform,
so a Linux-only library never loads on macOS or Windows and the reverse.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

if TYPE_CHECKING:
    from functualize._types.enums import KeyAvailability

__all__ = [
    "AdapterOutcome",
    "AdapterRead",
    "KeyringAdapter",
    "UnlockHow",
    "select_adapter",
]


class AdapterOutcome(Enum):
    """What a keyring answered."""

    FOUND = "found"
    LOCKED = "locked"
    """Locked, and not opened: a silent read never asks it to unlock."""

    NO_KEYRING = "no_keyring"
    """No backend, no daemon, no session bus."""

    NOT_STORED = "not_stored"
    """An unlocked keyring answered and holds no entry."""

    UNVERIFIED = "unverified"
    """A backend this adapter cannot read without risking a prompt, so it
    refused to read at all (the generic adapter only)."""


class UnlockHow(Enum):
    """How an :meth:`KeyringAdapter.unlock` call ended, for the person who ran it."""

    ALREADY_UNLOCKED = "already_unlocked"
    UNLOCKED_NOW = "unlocked"
    NOTHING_TO_UNLOCK = "nothing_to_unlock"
    """A platform with no lock model (Windows)."""

    CANCELLED = "cancelled"
    """The person cancelled in the keyring's own dialog."""

    NO_PROMPT = "no_prompt"
    """The keyring was asked to unlock and no dialog ever appeared."""


@dataclass(frozen=True, slots=True)
class AdapterRead:
    """One adapter answer. The secret never appears in the repr.

    ``secret`` is the stored value exactly as the keyring holds it (hex text);
    the key provider decodes and validates it, so every adapter shares one
    decoding rule.
    """

    outcome: AdapterOutcome
    secret: str | None = field(default=None, repr=False)
    how: UnlockHow | None = None
    """Set by :meth:`KeyringAdapter.unlock` only."""


@runtime_checkable
class KeyringAdapter(Protocol):
    """One platform's keyring, behind the three operations above."""

    @property
    def name(self) -> str:
        """A neutral name for messages, e.g. ``"secret-service"``."""
        ...

    def read_silent(self) -> AdapterRead:
        """The stored secret if the keyring is unlocked. Never prompts."""
        ...

    def state(self) -> KeyAvailability:
        """Whether a silent read would succeed. Never prompts; about 1 s at most."""
        ...

    def store_silent(self, secret: str) -> AdapterOutcome:
        """Store ``secret`` without prompting.

        FOUND when it is stored and a later :meth:`read_silent` finds it;
        LOCKED when the keyring is locked (nothing written); NO_KEYRING when
        there is no keyring to write to; UNVERIFIED when silence cannot be
        proven for this backend (the generic adapter).
        """
        ...

    def unlock(self) -> AdapterRead:
        """Ask the keyring to unlock — may prompt — and then read."""
        ...


# -- choosing the adapter ------------------------------------------------------
#
# A short ordered allowlist of (backend class, platform) rather than a strategy
# registry: four entries, and every one of them is a decision about which
# backends have been proven silent. Backends are matched by module and class
# name, so choosing never imports another platform's backend module.

_SECRET_SERVICE: Final = frozenset(
    {
        ("keyring.backends.SecretService", "Keyring"),
        ("keyring.backends.libsecret", "Keyring"),
    }
)
_MACOS: Final = frozenset({("keyring.backends.macOS", "Keyring")})
_WINDOWS: Final = frozenset({("keyring.backends.Windows", "WinVaultKeyring")})
_NONE: Final = frozenset(
    {("keyring.backends.fail", "Keyring"), ("keyring.backends.null", "Keyring")}
)
_CHAINER: Final = ("keyring.backends.chainer", "ChainerBackend")

#: Distinguishes "no backend passed" from an explicit ``backend=None``.
_ACTIVE: Any = object()


def select_adapter(
    service: str,
    account: str,
    *,
    platform: str | None = None,
    backend: Any = _ACTIVE,
) -> KeyringAdapter:
    """The adapter for this platform's active ``keyring`` backend.

    Only backends proven silent get a platform adapter: the Secret Service
    family (off macOS and Windows), the macOS Keychain on darwin, Credential
    Manager on win32. Anything else — a third-party backend, or a platform
    backend on the wrong platform — gets the generic adapter, which a run never
    reads through. No backend at all is the generic adapter with none, which
    answers "no keyring".

    Args:
        service: The keyring service name of the vault key.
        account: The keyring account name of the vault key.
        platform: ``sys.platform`` unless given (tests).
        backend: The active ``keyring`` backend unless given (tests); None
            means there is none.
    """
    from functualize._config.vault_keyring_generic import GenericAdapter

    chosen_platform = sys.platform if platform is None else platform
    active = _active_backend() if backend is _ACTIVE else backend
    active = _first_in_chain(active)
    ident = _ident(active)
    if active is None or ident in _NONE:
        return GenericAdapter(service, account, backend=None)
    if ident in _SECRET_SERVICE and chosen_platform not in ("darwin", "win32"):
        from functualize._config.vault_keyring_secretservice import SecretServiceAdapter

        return SecretServiceAdapter(service, account, backend=active)
    if ident in _MACOS and chosen_platform == "darwin":
        from functualize._config.vault_keyring_macos import MacKeychainAdapter

        return MacKeychainAdapter(service, account)
    if ident in _WINDOWS and chosen_platform == "win32":
        from functualize._config.vault_keyring_windows import WindowsCredentialAdapter

        return WindowsCredentialAdapter(service, account, loader=_GivenBackend(active))
    return GenericAdapter(service, account, backend=active)


class _GivenBackend:
    """A backend loader over a backend already chosen."""

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def load(self) -> Any:
        return self._backend


def _active_backend() -> Any:
    """``keyring``'s active backend, or None when there is no ``keyring`` or none loads."""
    try:
        import keyring
    except ImportError:
        return None
    try:
        return keyring.get_keyring()
    except Exception:  # noqa: BLE001 - a backend that cannot load is no backend
        return None


def _first_in_chain(backend: Any) -> Any:
    """A chainer reads its backends in priority order; the first one decides."""
    if _ident(backend) != _CHAINER:
        return backend
    for member in getattr(backend, "backends", ()) or ():
        if _ident(member) not in _NONE:
            return member
    return None


def _ident(backend: Any) -> tuple[str, str] | None:
    if backend is None:
        return None
    kind = type(backend)
    return (kind.__module__, kind.__qualname__)
