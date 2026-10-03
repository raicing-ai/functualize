"""The macOS keyring adapter: the Keychain, read with user interaction disabled.

``keyring``'s macOS backend reads with interaction allowed, so a locked keychain
may raise a system dialog in the middle of a run — the prompt a run must never
create. This adapter reads the same item (``kSecClassGenericPassword``, service
and account) with interaction **disabled for that one call**, so a locked
keychain answers ``errSecInteractionNotAllowed`` (``-25308``) instead of a
dialog, which maps to LOCKED.

**Per call, not per process.** The query carries
``kSecUseAuthenticationUI = kSecUseAuthenticationUIFail``. The older switch,
``SecKeychainSetUserInteractionAllowed``, is one flag for the whole process: two
adapters in one process — two apps, or a run beside a ``vault unlock`` — could
interleave so that one turns interaction back on while the other is mid-read,
and the "silent" read prompts. Only :meth:`MacKeychainAdapter.unlock`, which
may prompt anyway, still sets that flag.

**Unverified on a real Mac.** The calls are the documented ones, but this has
not been run against a real locked keychain here; the macOS CI smoke job and the
manual checklist decide whether it holds. The ctypes layer is a thin seam
(:class:`SecurityAPI`) so the outcome logic is tested everywhere with a fake.

The Security framework is reached through ``keyring``'s own ctypes handle,
imported lazily and only when the adapter is used — never on another platform.
"""

from __future__ import annotations

import contextlib
import threading
from typing import TYPE_CHECKING, Any, Protocol

from functualize._config.vault_keyring import AdapterOutcome, AdapterRead, UnlockHow
from functualize._types.enums import KeyAvailability

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["MacKeychainAdapter", "SecurityAPI"]

#: ``errSecItemNotFound``.
ITEM_NOT_FOUND = -25300
#: ``errSecInteractionNotAllowed`` — interaction was needed and is disabled.
INTERACTION_NOT_ALLOWED = -25308
#: ``userCanceledErr`` — the person cancelled the dialog.
USER_CANCELED = -128
#: ``errSecAuthFailed`` — the wrong password, or a locked keychain refused.
AUTH_FAILED = -25293

#: The statuses that mean "locked, and not opened".
_LOCKED_STATUSES = frozenset({INTERACTION_NOT_ALLOWED, USER_CANCELED, AUTH_FAILED})


class SecurityAPI(Protocol):
    """The Security-framework operations the adapter needs."""

    def interaction_allowed(self) -> bool: ...

    def set_interaction_allowed(self, allowed: bool) -> None: ...

    def copy_password(
        self, service: str, account: str, *, interactive: bool
    ) -> tuple[int, str | None]:
        """``(OSStatus, secret)`` — the secret only when the status is 0.

        ``interactive=False`` adds the per-call "fail rather than show UI"
        option to the query; True leaves the query as ``keyring`` writes it.
        """
        ...

    def add_password(self, service: str, account: str, secret: str) -> int:
        """Add the item with the per-call "fail rather than show UI" option."""
        ...

    def default_keychain_unlocked(self) -> bool | None:
        """Whether the default keychain is unlocked; None when it cannot say."""
        ...


class _CtypesSecurity:
    """The real calls, through ``keyring``'s Security handle (darwin only)."""

    def __init__(self, api: Any) -> None:
        import ctypes

        self._api = api
        self._ctypes = ctypes
        # Resolved up front: a Security framework without it cannot read
        # silently, and the adapter then reports no keychain instead.
        self._ui_fail = api.k_("kSecUseAuthenticationUIFail")
        sec = api._sec
        self._get = sec.SecKeychainGetUserInteractionAllowed
        self._get.restype = ctypes.c_int32
        self._get.argtypes = (ctypes.POINTER(ctypes.c_ubyte),)
        self._set = sec.SecKeychainSetUserInteractionAllowed
        self._set.restype = ctypes.c_int32
        self._set.argtypes = (ctypes.c_ubyte,)
        self._copy_default = sec.SecKeychainCopyDefault
        self._copy_default.restype = ctypes.c_int32
        self._copy_default.argtypes = (ctypes.POINTER(ctypes.c_void_p),)
        self._status = sec.SecKeychainGetStatus
        self._status.restype = ctypes.c_int32
        self._status.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))

    def interaction_allowed(self) -> bool:
        flag = self._ctypes.c_ubyte(1)
        self._get(self._ctypes.byref(flag))
        return bool(flag.value)

    def set_interaction_allowed(self, allowed: bool) -> None:
        self._set(1 if allowed else 0)

    def copy_password(
        self, service: str, account: str, *, interactive: bool
    ) -> tuple[int, str | None]:
        api = self._api
        fields: dict[str, Any] = {
            "kSecClass": api.k_("kSecClassGenericPassword"),
            "kSecMatchLimit": api.k_("kSecMatchLimitOne"),
            "kSecAttrService": service,
            "kSecAttrAccount": account,
            "kSecReturnData": True,
        }
        if not interactive:
            fields["kSecUseAuthenticationUI"] = self._ui_fail
        query = api.create_query(**fields)
        data = self._ctypes.c_void_p()
        status = int(api.SecItemCopyMatching(query, self._ctypes.byref(data)))
        if status != 0:
            return status, None
        return 0, api.cfstr_to_str(data)

    def add_password(self, service: str, account: str, secret: str) -> int:
        api = self._api
        query = api.create_query(
            kSecClass=api.k_("kSecClassGenericPassword"),
            kSecAttrService=service,
            kSecAttrAccount=account,
            kSecValueData=secret,
            kSecUseAuthenticationUI=self._ui_fail,
        )
        return int(api.SecItemAdd(query, None))

    def default_keychain_unlocked(self) -> bool | None:
        keychain = self._ctypes.c_void_p()
        if self._copy_default(self._ctypes.byref(keychain)) != 0:
            return None
        status = self._ctypes.c_uint32(0)
        if self._status(keychain, self._ctypes.byref(status)) != 0:
            return None
        return bool(status.value & 0x1)  # kSecUnlockStateStatus


class MacKeychainAdapter:
    """The vault key in the macOS Keychain, read with interaction disabled."""

    def __init__(
        self,
        service: str,
        account: str,
        *,
        security: SecurityAPI | None = None,
        state_bound: float = 1.0,
    ) -> None:
        self._service = service
        self._account = account
        self._security = security
        self._state_bound = state_bound

    @property
    def name(self) -> str:
        return "macos"

    def read_silent(self) -> AdapterRead:
        """Read with interaction disabled for this call: a locked keychain answers."""
        security = self._api()
        if security is None:
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        status, secret = security.copy_password(
            self._service, self._account, interactive=False
        )
        return _outcome(status, secret)

    def store_silent(self, secret: str) -> AdapterOutcome:
        """Add the item with interaction disabled for this call; locked is LOCKED."""
        security = self._api()
        if security is None:
            return AdapterOutcome.NO_KEYRING
        status = security.add_password(self._service, self._account, secret)
        if status == 0:
            return AdapterOutcome.FOUND
        if status in _LOCKED_STATUSES:
            return AdapterOutcome.LOCKED
        return AdapterOutcome.NO_KEYRING

    def state(self) -> KeyAvailability:
        security = self._api()
        if security is None:
            return KeyAvailability.UNKNOWN
        answer: list[bool | None] = []

        def ask() -> None:
            try:
                answer.append(security.default_keychain_unlocked())
            except Exception:  # noqa: BLE001 - a state probe never raises
                answer.append(None)

        thread = threading.Thread(
            target=ask, daemon=True, name="functualize-keychain-state"
        )
        thread.start()
        thread.join(self._state_bound)
        if not answer or answer[0] is None:
            return KeyAvailability.UNKNOWN
        return KeyAvailability.UNLOCKED if answer[0] else KeyAvailability.LOCKED

    def unlock(self) -> AdapterRead:
        """Read with interaction allowed — the system may show its dialog."""
        before = self.read_silent()
        if before.outcome is not AdapterOutcome.LOCKED:
            how = (
                None
                if before.outcome is AdapterOutcome.NO_KEYRING
                else UnlockHow.ALREADY_UNLOCKED
            )
            return AdapterRead(before.outcome, secret=before.secret, how=how)
        security = self._api()
        assert security is not None
        with self._interaction(security, allowed=True):
            status, secret = security.copy_password(
                self._service, self._account, interactive=True
            )
        if status == USER_CANCELED:
            return AdapterRead(AdapterOutcome.LOCKED, how=UnlockHow.CANCELLED)
        read = _outcome(status, secret)
        return AdapterRead(read.outcome, secret=read.secret, how=UnlockHow.UNLOCKED_NOW)

    def _api(self) -> SecurityAPI | None:
        if self._security is None:
            try:
                from keyring.backends.macOS import api
            except Exception:  # noqa: BLE001 - no Security framework: no keychain
                return None
            try:
                self._security = _CtypesSecurity(api)
            except Exception:  # noqa: BLE001 - cannot read silently: no keychain
                return None
        return self._security

    @staticmethod
    @contextlib.contextmanager
    def _interaction(security: SecurityAPI, *, allowed: bool) -> Iterator[None]:
        """Allow interaction for the one prompting read, and always put it back."""
        previous = security.interaction_allowed()
        security.set_interaction_allowed(allowed)
        try:
            yield
        finally:
            security.set_interaction_allowed(previous)


def _outcome(status: int, secret: str | None) -> AdapterRead:
    if status == 0 and secret is not None:
        return AdapterRead(AdapterOutcome.FOUND, secret=secret)
    if status == ITEM_NOT_FOUND:
        return AdapterRead(AdapterOutcome.NOT_STORED)
    if status in _LOCKED_STATUSES:
        return AdapterRead(AdapterOutcome.LOCKED)
    return AdapterRead(AdapterOutcome.NO_KEYRING)
