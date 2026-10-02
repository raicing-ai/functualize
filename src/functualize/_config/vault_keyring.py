"""The keyring port: three operations every platform adapter implements.

The vault key lives in the OS keyring, and every platform's keyring behaves
differently when it is locked. Some show a dialog on any read; one has no lock
at all. What functualize needs from all of them is the same three answers, so
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
``unlock()``
    The only operation that may prompt. ``func builtin vault unlock`` calls it
    because a person asked; it waits for the prompt's own outcome and never
    cancels a prompt from the client side.

Adapters import their platform library lazily and only on their own platform,
so a Linux-only library never loads on macOS or Windows and the reverse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from functualize._types.enums import KeyAvailability

__all__ = [
    "AdapterOutcome",
    "AdapterRead",
    "KeyringAdapter",
    "UnlockHow",
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

    def unlock(self) -> AdapterRead:
        """Ask the keyring to unlock — may prompt — and then read."""
        ...
