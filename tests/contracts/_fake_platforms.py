"""Fake keyring worlds, and the registry of adapters the contract suite runs over.

Every keyring adapter is held to one contract (`test_keyring_adapter_contract.py`).
An adapter takes part by adding a *harness* to :data:`HARNESSES`: something that
builds the real adapter over a fake of its platform library, put into one of the
:class:`World` states, with a :class:`Recorder` that counts what a person would
have seen — above all, **whether an unlock prompt was requested**.

The placeholder harness below drives an honest in-memory adapter, so the suite
runs (and pins the contract) before any platform adapter exists.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from functualize._config.vault_keyring import AdapterOutcome, AdapterRead, UnlockHow
from functualize._types.enums import KeyAvailability

if TYPE_CHECKING:
    from functualize._config.vault_keyring import KeyringAdapter


class World(Enum):
    """The states a keyring can be in when an adapter is asked."""

    UNLOCKED = "unlocked"
    """Unlocked, and the vault key is stored."""

    LOCKED = "locked"
    """Locked; the vault key is stored behind the lock."""

    EMPTY = "empty"
    """Unlocked, and no vault key is stored."""

    ABSENT = "absent"
    """No keyring backend at all."""

    HUNG = "hung"
    """A backend that never answers."""


class Answer(Enum):
    """What the person does when an unlock dialog appears."""

    ACCEPT = "accept"
    CANCEL = "cancel"
    NO_DIALOG = "no_dialog"
    """The keyring was asked to unlock and no dialog ever appeared."""


@dataclass
class Recorder:
    """What the fake platform observed. The contract reads it."""

    answer: Answer = Answer.ACCEPT
    prompts: int = 0
    """Unlock prompts requested from the keyring — the number a run must keep at 0."""

    secret_reads: int = 0
    """Times the stored secret itself was read."""


#: Long enough that any adapter that waits on a hung backend fails its bound.
HANG_SECONDS = 30.0


class Harness(Protocol):
    """Builds one real adapter over a fake platform in a given world."""

    name: str
    worlds: frozenset[World]
    """The worlds this platform can be in (no lock model -> no LOCKED)."""

    proves_silence: bool
    """False only for the generic adapter, which refuses to read at all."""

    detects_missing_prompt: bool
    """True when the adapter can tell that no unlock dialog appeared."""

    def build(self, world: World, secret: str, recorder: Recorder) -> KeyringAdapter:
        """The adapter under test, in ``world``, holding ``secret``."""
        ...


# --------------------------------------------------------------------------
# The placeholder: an honest in-memory adapter, so the suite pins the contract
# before any platform adapter exists.
# --------------------------------------------------------------------------


class _InMemoryAdapter:
    def __init__(self, world: World, secret: str, recorder: Recorder) -> None:
        self._world = world
        self._secret = secret
        self._recorder = recorder

    @property
    def name(self) -> str:
        return "in-memory"

    def read_silent(self) -> AdapterRead:
        if self._world is World.HUNG:
            time.sleep(HANG_SECONDS)
        if self._world is World.ABSENT:
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        if self._world is World.LOCKED:
            return AdapterRead(AdapterOutcome.LOCKED)
        if self._world is World.EMPTY:
            return AdapterRead(AdapterOutcome.NOT_STORED)
        self._recorder.secret_reads += 1
        return AdapterRead(AdapterOutcome.FOUND, secret=self._secret)

    def state(self) -> KeyAvailability:
        if self._world is World.LOCKED:
            return KeyAvailability.LOCKED
        if self._world in (World.UNLOCKED, World.EMPTY):
            return KeyAvailability.UNLOCKED
        return KeyAvailability.UNKNOWN

    def unlock(self) -> AdapterRead:
        if self._world is World.LOCKED:
            self._recorder.prompts += 1
            if self._recorder.answer is Answer.CANCEL:
                return AdapterRead(AdapterOutcome.LOCKED, how=UnlockHow.CANCELLED)
            if self._recorder.answer is Answer.NO_DIALOG:
                return AdapterRead(AdapterOutcome.LOCKED, how=UnlockHow.NO_PROMPT)
            self._world = World.UNLOCKED
            read = self.read_silent()
            return AdapterRead(
                read.outcome, secret=read.secret, how=UnlockHow.UNLOCKED_NOW
            )
        read = self.read_silent()
        how = (
            UnlockHow.ALREADY_UNLOCKED
            if read.outcome is not AdapterOutcome.NO_KEYRING
            else None
        )
        return AdapterRead(read.outcome, secret=read.secret, how=how)


class _InMemoryHarness:
    name = "in-memory"
    worlds = frozenset(World)
    proves_silence = True
    detects_missing_prompt = True

    def build(self, world: World, secret: str, recorder: Recorder) -> KeyringAdapter:
        return _InMemoryAdapter(world, secret, recorder)


#: Every adapter the contract suite holds to the contract. An adapter task adds
#: its harness here.
HARNESSES: list[Harness] = [_InMemoryHarness()]
