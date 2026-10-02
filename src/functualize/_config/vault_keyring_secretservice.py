"""The Linux keyring adapter: the Secret Service protocol, read without prompting.

Speaks the freedesktop Secret Service API through ``secretstorage``, so it
serves any implementation of it (gnome-keyring, KWallet 6, KeePassXC), not one
product.

**Why not ``keyring``'s own Secret Service backend.** Its read unlocks a locked
collection first — a blocking unlock prompt on every read. A run that does that
and then gives up (a deadline, Ctrl-C, an agent killing its child) leaves the
prompt to be abandoned, and on gnome-keyring 50 that can crash the daemon and
re-lock every keyring. So this adapter reads the protocol directly:

* :meth:`SecretServiceAdapter.read_silent` checks the collection's ``Locked``
  property and returns LOCKED at once if it is locked. Item attributes are
  clear text even while locked, so "is anything stored?" needs no unlock; the
  secret itself is read only from an unlocked collection.
* :meth:`SecretServiceAdapter.unlock` is the only method that asks the service
  to unlock, and it waits — with no deadline — for the prompt's own outcome.
  It never cancels the prompt from this side.
* It never creates a collection: ``secretstorage.get_default_collection``
  creates one when none exists, which is itself a prompt.

``secretstorage`` (and ``jeepney``, beneath it) is imported lazily, inside the
adapter, so nothing here loads on a platform that does not use it.
"""

from __future__ import annotations

import contextlib
import importlib
import threading
from typing import TYPE_CHECKING, Any, Protocol

from functualize._config.vault_keyring import AdapterOutcome, AdapterRead, UnlockHow
from functualize._types.enums import KeyAvailability

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["BusNames", "SecretServiceAdapter"]

#: The bus name gnome-keyring's daemon owns. The "did a dialog appear?" watcher
#: only applies when it is present: the prompter name below is gnome-keyring's.
_GNOME_KEYRING = "org.gnome.keyring"

#: The bus name of the process that shows gnome-keyring's unlock dialog.
_SYSTEM_PROMPTER = "org.gnome.keyring.SystemPrompter"


class BusNames(Protocol):
    """Whether a session-bus name has an owner; None when that cannot be told."""

    def has_owner(self, name: str) -> bool | None: ...


class _SessionBusNames:
    """Asks the session bus, on its own connection, through ``jeepney``."""

    def has_owner(self, name: str) -> bool | None:
        try:
            # Through importlib: jeepney ships no type information, and it is
            # used here for two calls.
            jeepney = importlib.import_module("jeepney")
            blocking = importlib.import_module("jeepney.io.blocking")
        except ImportError:
            return None
        try:
            with blocking.open_dbus_connection(bus="SESSION") as connection:
                reply = connection.send_and_get_reply(
                    jeepney.DBus().NameHasOwner(name), timeout=1.0
                )
            return bool(reply.body[0])
        except Exception:  # noqa: BLE001 - "cannot tell" is an answer here
            return None


class SecretServiceAdapter:
    """The vault key in a Secret Service collection, read without prompting."""

    def __init__(
        self,
        service: str,
        account: str,
        *,
        backend: Any = None,
        module: Any = None,
        bus_names: BusNames | None = None,
        state_bound: float = 1.0,
        prompt_appear_seconds: float = 3.0,
    ) -> None:
        """Initialise the adapter.

        Args:
            service: The item's ``service`` attribute.
            account: The item's ``username`` attribute.
            backend: The active ``keyring`` backend, if any. Its attribute
                scheme and ``preferred_collection`` are honoured, so this reads
                exactly the item ``keyring.set_password`` wrote.
            module: A ``secretstorage``-shaped module. Defaults to importing
                ``secretstorage`` on first use; tests pass a fake.
            bus_names: Session-bus name lookup, for the missing-dialog watcher.
            state_bound: How long :meth:`state` may take before it says UNKNOWN.
            prompt_appear_seconds: How long :meth:`unlock` lets gnome-keyring's
                dialog take to appear before reporting that none did.
        """
        self._service = service
        self._account = account
        self._backend = backend
        self._module = module
        self._bus_names: BusNames = bus_names or _SessionBusNames()
        self._state_bound = state_bound
        self._prompt_appear_seconds = prompt_appear_seconds

    @property
    def name(self) -> str:
        return "linux"

    # -- the three operations -----------------------------------------------

    def read_silent(self) -> AdapterRead:
        """The stored secret if the collection is unlocked. Never asks it to unlock."""
        ss = self._secretstorage()
        if ss is None:
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        try:
            connection = ss.dbus_init()
        except Exception:  # noqa: BLE001 - no service, no bus: no keyring here
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        try:
            return self._read(ss, connection)
        except ss.exceptions.LockedException:
            return AdapterRead(AdapterOutcome.LOCKED)
        except Exception:  # noqa: BLE001 - a D-Bus failure mid-read is "no keyring reachable", never a prompt
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        finally:
            _close(connection)

    def state(self) -> KeyAvailability:
        """Locked or unlocked, from the ``Locked`` property, within the bound."""
        answer: list[KeyAvailability] = []

        def ask() -> None:
            answer.append(self._state_once())

        thread = threading.Thread(
            target=ask, daemon=True, name="functualize-keyring-state"
        )
        thread.start()
        thread.join(self._state_bound)
        return answer[0] if answer else KeyAvailability.UNKNOWN

    def has_entry(self) -> bool | None:
        """Whether the vault key item exists, from its clear-text attributes.

        Readable while the collection is locked, and never reads the secret;
        None when the service cannot be asked.
        """
        ss = self._secretstorage()
        if ss is None:
            return None
        try:
            connection = ss.dbus_init()
        except Exception:  # noqa: BLE001 - "cannot tell" is an answer here
            return None
        try:
            collection = self._collection(ss, connection)
            return any(True for _ in collection.search_items(dict(self._attributes())))
        except Exception:  # noqa: BLE001 - "cannot tell" is an answer here
            return None
        finally:
            _close(connection)

    def unlock(self) -> AdapterRead:
        """Ask the service to unlock — the one call that may show a dialog.

        Waits for the dialog's own outcome, with no deadline, and never cancels
        it from this side: ending an active prompt from the client can crash
        the keyring daemon. The one exception is a dialog that never appears at
        all (gnome-keyring only, detected by its prompter not being on the
        bus): then the wait is reported as "no prompt" rather than lasting
        forever, and the pending request is left to the daemon.
        """
        before = self.read_silent()
        if before.outcome is AdapterOutcome.NO_KEYRING:
            return before
        if before.outcome is not AdapterOutcome.LOCKED:
            return AdapterRead(
                before.outcome, secret=before.secret, how=UnlockHow.ALREADY_UNLOCKED
            )

        ss = self._secretstorage()
        assert ss is not None  # read_silent answered LOCKED, so it imported
        done = threading.Event()
        result: dict[str, Any] = {}

        def run() -> None:
            try:
                connection = ss.dbus_init()
                try:
                    result["dismissed"] = bool(
                        self._collection(ss, connection).unlock()
                    )
                finally:
                    _close(connection)
            except Exception as exc:  # noqa: BLE001 - reported to the caller below
                result["error"] = exc
            finally:
                done.set()

        worker = threading.Thread(
            target=run, daemon=True, name="functualize-keyring-unlock"
        )
        worker.start()
        if not done.wait(self._prompt_appear_seconds) and self._no_dialog_appeared():
            return AdapterRead(AdapterOutcome.LOCKED, how=UnlockHow.NO_PROMPT)
        done.wait()

        if "error" in result:
            return AdapterRead(AdapterOutcome.NO_KEYRING)
        if result.get("dismissed"):
            return AdapterRead(AdapterOutcome.LOCKED, how=UnlockHow.CANCELLED)
        after = self.read_silent()
        return AdapterRead(
            after.outcome, secret=after.secret, how=UnlockHow.UNLOCKED_NOW
        )

    # -- internals ------------------------------------------------------------

    def _secretstorage(self) -> Any:
        if self._module is None:
            try:
                import secretstorage
            except ImportError:
                return None
            self._module = secretstorage
        return self._module

    def _attributes(self) -> Mapping[str, str]:
        """The attributes ``keyring`` writes, in the backend's scheme."""
        schemes = getattr(self._backend, "schemes", None)
        scheme_name = getattr(self._backend, "scheme", None)
        names = (schemes or {}).get(scheme_name) or {
            "username": "username",
            "service": "service",
        }
        return {names["username"]: self._account, names["service"]: self._service}

    def _collection(self, ss: Any, connection: Any) -> Any:
        """The collection ``keyring`` uses — never created, which would prompt."""
        preferred = getattr(self._backend, "preferred_collection", None)
        if preferred:
            return ss.Collection(connection, preferred)
        return ss.Collection(connection)

    def _read(self, ss: Any, connection: Any) -> AdapterRead:
        try:
            collection = self._collection(ss, connection)
        except ss.exceptions.ItemNotFoundException:
            # No such collection: nothing can be stored there, and creating
            # one would itself be a prompt.
            return AdapterRead(AdapterOutcome.NOT_STORED)
        if collection.is_locked():
            return AdapterRead(AdapterOutcome.LOCKED)
        for item in collection.search_items(dict(self._attributes())):
            secret = item.get_secret()
            return AdapterRead(
                AdapterOutcome.FOUND, secret=bytes(secret).decode("utf-8")
            )
        return AdapterRead(AdapterOutcome.NOT_STORED)

    def _state_once(self) -> KeyAvailability:
        ss = self._secretstorage()
        if ss is None:
            return KeyAvailability.UNKNOWN
        try:
            connection = ss.dbus_init()
        except Exception:  # noqa: BLE001 - a state probe never raises
            return KeyAvailability.UNKNOWN
        try:
            try:
                collection = self._collection(ss, connection)
            except ss.exceptions.ItemNotFoundException:
                return KeyAvailability.UNLOCKED
            return (
                KeyAvailability.LOCKED
                if collection.is_locked()
                else KeyAvailability.UNLOCKED
            )
        except Exception:  # noqa: BLE001 - a state probe never raises
            return KeyAvailability.UNKNOWN
        finally:
            _close(connection)

    def _no_dialog_appeared(self) -> bool:
        """True only when gnome-keyring is running and its prompter is not."""
        if self._bus_names.has_owner(_GNOME_KEYRING) is not True:
            return False
        return self._bus_names.has_owner(_SYSTEM_PROMPTER) is False


def _close(connection: Any) -> None:
    close = getattr(connection, "close", None)
    if close is not None:
        # Closing a dead connection is not an error.
        with contextlib.suppress(Exception):
            close()
