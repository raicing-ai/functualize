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
from typing import TYPE_CHECKING, Any, Protocol

from functualize._config.vault_keyring import AdapterOutcome, AdapterRead, UnlockHow
from functualize._types.enums import KeyAvailability

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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

    def store_silent(self, secret: str) -> AdapterOutcome:
        if self._world is World.HUNG:
            time.sleep(HANG_SECONDS)
        if self._world is World.ABSENT:
            return AdapterOutcome.NO_KEYRING
        if self._world is World.LOCKED:
            return AdapterOutcome.LOCKED
        self._world = World.UNLOCKED
        self._secret = secret
        return AdapterOutcome.FOUND

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


# --------------------------------------------------------------------------
# Linux: a fake `secretstorage` module (no D-Bus).
# --------------------------------------------------------------------------


class _SecretStorageError(Exception):
    pass


class _ItemNotFoundError(_SecretStorageError):
    pass


class _LockedError(_SecretStorageError):
    pass


class _NotAvailableError(_SecretStorageError):
    pass


class _Exceptions:
    SecretStorageException = _SecretStorageError
    ItemNotFoundException = _ItemNotFoundError
    LockedException = _LockedError
    SecretServiceNotAvailableException = _NotAvailableError


class FakeSecretService:
    """The service's state, shared by every connection a test opens."""

    def __init__(
        self,
        world: World,
        secret: str,
        recorder: Recorder,
        *,
        attributes: dict[str, str] | None = None,
        collections: tuple[str, ...] = ("/org/freedesktop/secrets/aliases/default",),
    ) -> None:
        self.world = world
        self.secret = secret
        self.recorder = recorder
        self.attributes = attributes or {
            "username": "vault-key",
            "service": "functualize-vault",
        }
        self.collections = set(collections)
        self.created: list[str] = []
        self.opened: list[str] = []
        self.stored: list[dict[str, str]] = []
        """The attributes of every item written."""
        self.unlock_delay = 0.0
        """How long the person takes to answer the dialog."""


class _FakeItem:
    def __init__(self, service: FakeSecretService) -> None:
        self._service = service

    def get_secret(self) -> bytes:
        if self._service.world is World.LOCKED:
            raise _LockedError("Item is locked!")
        self._service.recorder.secret_reads += 1
        return self._service.secret.encode()


class _FakeCollection:
    def __init__(self, service: FakeSecretService, path: str) -> None:
        if path not in service.collections:
            raise _ItemNotFoundError(path)
        service.opened.append(path)
        self._service = service

    def is_locked(self) -> bool:
        if self._service.world is World.HUNG:
            time.sleep(HANG_SECONDS)
        return self._service.world is World.LOCKED

    def search_items(self, attributes: dict[str, str]) -> Iterator[_FakeItem]:
        if self._service.world is World.EMPTY or attributes != self._service.attributes:
            return
        yield _FakeItem(self._service)

    def create_item(
        self,
        label: str,
        attributes: dict[str, str],
        secret: bytes,
        replace: bool = False,
    ) -> None:
        """As `secretstorage` does: a locked collection raises, it never prompts."""
        if self._service.world is World.LOCKED:
            raise _LockedError("Collection is locked!")
        self._service.stored.append(dict(attributes))
        self._service.secret = secret.decode()
        self._service.world = World.UNLOCKED

    def unlock(self) -> bool:
        """Returns whether the prompt was dismissed, as `secretstorage` does."""
        recorder = self._service.recorder
        recorder.prompts += 1
        if self._service.unlock_delay:
            time.sleep(self._service.unlock_delay)
        if recorder.answer is Answer.NO_DIALOG:
            time.sleep(HANG_SECONDS)
        if recorder.answer is Answer.CANCEL:
            return True
        self._service.world = World.UNLOCKED
        return False


class _FakeConnection:
    def close(self) -> None:
        pass


class FakeSecretStorageModule:
    """Just the surface of `secretstorage` the adapter uses."""

    exceptions = _Exceptions

    def __init__(self, service: FakeSecretService) -> None:
        self._service = service

    def dbus_init(self) -> _FakeConnection:
        if self._service.world is World.ABSENT:
            raise _NotAvailableError("no Secret Service on the bus")
        return _FakeConnection()

    def Collection(  # noqa: N802 - mirrors secretstorage.Collection
        self, connection: object, path: str = "/org/freedesktop/secrets/aliases/default"
    ) -> _FakeCollection:
        return _FakeCollection(self._service, path)

    def create_collection(self, *args: object, **kwargs: object) -> None:
        self._service.created.append(str(args))
        msg = "the adapter must never create a collection: that prompts"
        raise AssertionError(msg)

    def get_default_collection(self, *args: object, **kwargs: object) -> None:
        msg = (
            "get_default_collection creates a collection when none exists: that prompts"
        )
        raise AssertionError(msg)


class FakeBusNames:
    """gnome-keyring on the bus; its prompter present unless no dialog appears."""

    def __init__(self, recorder: Recorder, *, gnome: bool = True) -> None:
        self._recorder = recorder
        self._gnome = gnome

    def has_owner(self, name: str) -> bool | None:
        if name == "org.gnome.keyring":
            return self._gnome
        if name == "org.gnome.keyring.SystemPrompter":
            return self._recorder.answer is not Answer.NO_DIALOG
        return None


def secret_service_adapter(
    world: World, secret: str, recorder: Recorder, **kwargs: Any
) -> tuple[KeyringAdapter, FakeSecretService]:
    from functualize._config.vault_keyring_secretservice import SecretServiceAdapter

    service = FakeSecretService(world, secret, recorder)
    adapter = SecretServiceAdapter(
        "functualize-vault",
        "vault-key",
        module=FakeSecretStorageModule(service),
        bus_names=kwargs.pop("bus_names", FakeBusNames(recorder)),
        state_bound=0.5,
        prompt_appear_seconds=0.3,
        **kwargs,
    )
    return adapter, service


class _SecretServiceHarness:
    name = "linux"
    worlds = frozenset(World)
    proves_silence = True
    detects_missing_prompt = True

    def build(self, world: World, secret: str, recorder: Recorder) -> KeyringAdapter:
        return secret_service_adapter(world, secret, recorder)[0]


# --------------------------------------------------------------------------
# macOS: a fake of the four Security-framework calls the adapter makes.
# --------------------------------------------------------------------------


class FakeSecurity:
    """The Security framework as ``keyring``'s macOS ``api`` module exposes it.

    The adapter's **real** ctypes layer runs over this, so the code that sets,
    guards and restores the interaction flag is the production code. ``allowed``
    is ``SecKeychainSetUserInteractionAllowed`` — **one flag for the whole
    process** — so two adapters built over one ``FakeSecurity`` are two
    adapters in one process. A locked keychain read or written while it is True
    shows a dialog (counted as a prompt); while it is False the call fails with
    ``errSecInteractionNotAllowed``.
    """

    def __init__(self, world: World, secret: str, recorder: Recorder) -> None:
        self.world = world
        self.secret = secret
        self.recorder = recorder
        self.allowed = True
        self.copies: list[bool] = []
        """The flag as each read saw it."""

        self.on_copy: Callable[[], None] | None = None
        """Called as a read begins, before it looks at the flag; tests interleave here."""

        self.on_set: Callable[[bool], None] | None = None
        """Called after the flag is set, with its new value."""

        self._sec = _FakeSecLibrary(self)

    # -- the `api` module surface ---------------------------------------------

    def k_(self, name: str) -> str:
        return name

    def create_query(self, **fields: Any) -> dict[str, Any]:
        return fields

    def SecItemCopyMatching(self, query: dict[str, Any], out: Any) -> int:  # noqa: N802 - mirrors the C name
        if self.on_copy is not None:
            self.on_copy()
        self.copies.append(self.allowed)
        if self.world is World.HUNG:
            time.sleep(HANG_SECONDS)
        if self.world is World.ABSENT:
            return -25291  # errSecNotAvailable
        if self.world is World.EMPTY:
            return -25300
        if self.world is World.LOCKED:
            if not self.allowed:
                return -25308
            self.recorder.prompts += 1
            if self.recorder.answer is Answer.CANCEL:
                return -128
            self.world = World.UNLOCKED
        self.recorder.secret_reads += 1
        out._obj.value = 1
        return 0

    def cfstr_to_str(self, data: Any) -> str:
        return self.secret

    def SecItemAdd(self, query: dict[str, Any], result: Any) -> int:  # noqa: N802 - mirrors the C name
        if self.world is World.HUNG:
            time.sleep(HANG_SECONDS)
        if self.world is World.ABSENT:
            return -25291
        if self.world is World.LOCKED:
            if not self.allowed:
                return -25308
            self.recorder.prompts += 1
            return -128
        self.secret = query["kSecValueData"]
        self.world = World.UNLOCKED
        return 0


class _FakeSecLibrary:
    """``api._sec``: the four keychain calls the ctypes layer binds by name.

    Plain functions, because the ctypes layer sets ``restype`` and ``argtypes``
    on each, as it would on a real ``CDLL`` symbol.
    """

    def __init__(self, keychain: FakeSecurity) -> None:
        def get_interaction(out: Any) -> int:
            out._obj.value = 1 if keychain.allowed else 0
            return 0

        def set_interaction(allowed: int) -> int:
            keychain.allowed = bool(allowed)
            if keychain.on_set is not None:
                keychain.on_set(bool(allowed))
            return 0

        def copy_default(out: Any) -> int:
            if keychain.world is World.HUNG:
                time.sleep(HANG_SECONDS)
            if keychain.world is World.ABSENT:
                return -25291
            out._obj.value = 1
            return 0

        def get_status(keychain_ref: Any, out: Any) -> int:
            out._obj.value = 0 if keychain.world is World.LOCKED else 1
            return 0

        self.SecKeychainGetUserInteractionAllowed = get_interaction
        self.SecKeychainSetUserInteractionAllowed = set_interaction
        self.SecKeychainCopyDefault = copy_default
        self.SecKeychainGetStatus = get_status


def mac_adapter(
    world: World, secret: str, recorder: Recorder, *, keychain: FakeSecurity | None = None
) -> tuple[KeyringAdapter, FakeSecurity]:
    """A macOS adapter over its real ctypes layer and a fake Security framework.

    Pass ``keychain`` to build a second adapter in the same "process".
    """
    from functualize._config.vault_keyring_macos import (
        MacKeychainAdapter,
        _CtypesSecurity,
    )

    security = keychain or FakeSecurity(world, secret, recorder)
    return (
        MacKeychainAdapter(
            "functualize-vault",
            "vault-key",
            security=_CtypesSecurity(security),
            state_bound=0.5,
        ),
        security,
    )


class _MacHarness:
    name = "macos"
    worlds = frozenset(World)
    proves_silence = True
    detects_missing_prompt = False

    def build(self, world: World, secret: str, recorder: Recorder) -> KeyringAdapter:
        return mac_adapter(world, secret, recorder)[0]


# --------------------------------------------------------------------------
# Windows: a fake of keyring's Windows backend (Credential Manager).
# --------------------------------------------------------------------------


class FakeWinBackend:
    def __init__(self, world: World, secret: str, recorder: Recorder) -> None:
        self.world = world
        self.secret = secret
        self.recorder = recorder

    def get_password(self, service: str, username: str) -> str | None:
        if self.world is World.EMPTY:
            return None
        self.recorder.secret_reads += 1
        return self.secret

    def set_password(self, service: str, username: str, password: str) -> None:
        self.secret = password
        self.world = World.UNLOCKED


class FakeWinLoader:
    """Credential Manager present, unless the world says there is none."""

    def __init__(self, world: World, secret: str, recorder: Recorder) -> None:
        self.backend = (
            None if world is World.ABSENT else FakeWinBackend(world, secret, recorder)
        )

    def load(self) -> FakeWinBackend | None:
        return self.backend


class _WindowsHarness:
    name = "windows"
    # No lock model, so there is no locked world; and no state query that
    # could hang, so no hung one either.
    worlds = frozenset({World.UNLOCKED, World.EMPTY, World.ABSENT})
    proves_silence = True
    detects_missing_prompt = False

    def build(self, world: World, secret: str, recorder: Recorder) -> KeyringAdapter:
        from functualize._config.vault_keyring_windows import WindowsCredentialAdapter

        return WindowsCredentialAdapter(
            "functualize-vault",
            "vault-key",
            loader=FakeWinLoader(world, secret, recorder),
        )


# --------------------------------------------------------------------------
# Anything else: a fake third-party `keyring` backend that may prompt.
# --------------------------------------------------------------------------


class FakeUnknownBackend:
    """A `keyring` backend whose get_password prompts on a locked store."""

    def __init__(self, world: World, secret: str, recorder: Recorder) -> None:
        self.world = world
        self.secret = secret
        self.recorder = recorder

    def get_password(self, service: str, username: str) -> str | None:
        from keyring.errors import KeyringLocked

        if self.world is World.HUNG:
            time.sleep(HANG_SECONDS)
        if self.world is World.LOCKED:
            self.recorder.prompts += 1
            if self.recorder.answer is not Answer.ACCEPT:
                msg = "the person cancelled"
                raise KeyringLocked(msg)
            self.world = World.UNLOCKED
        if self.world is World.EMPTY:
            return None
        self.recorder.secret_reads += 1
        return self.secret


class _GenericHarness:
    name = "generic"
    worlds = frozenset(World)
    proves_silence = False
    detects_missing_prompt = False

    def build(self, world: World, secret: str, recorder: Recorder) -> KeyringAdapter:
        from functualize._config.vault_keyring_generic import GenericAdapter

        backend = (
            None
            if world is World.ABSENT
            else FakeUnknownBackend(world, secret, recorder)
        )
        return GenericAdapter("functualize-vault", "vault-key", backend=backend)


#: Every adapter the contract suite holds to the contract. An adapter task adds
#: its harness here.
HARNESSES: list[Harness] = [
    _InMemoryHarness(),
    _SecretServiceHarness(),
    _MacHarness(),
    _WindowsHarness(),
    _GenericHarness(),
]
