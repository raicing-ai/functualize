"""A fake `secretstorage` for `func` subprocesses: a Secret Service with no D-Bus.

The end-to-end tests run the real ``func`` console script with stdout piped,
and select ``keyring``'s real Secret Service backend
(``PYTHON_KEYRING_BACKEND=keyring.backends.SecretService.Keyring``). That backend
— and functualize's own Linux keyring adapter — import ``secretstorage``; the
test puts a two-line ``secretstorage`` package that re-exports this module ahead
of the real one on the child's ``PYTHONPATH``. So the *real* provider and adapter
run end to end, against a keyring the test controls:

``FAKE_KEYRING_MODE``
    The keyring's starting state: ``unlocked`` (the key is stored, readable),
    ``locked`` (stored, behind the lock), ``empty`` (unlocked, nothing stored),
    ``absent`` (no Secret Service on the bus), or ``raises`` (fails the run on
    any use — for runs that must not touch the keyring).
``FAKE_KEYRING_UNLOCK``
    What the person does when asked to unlock: ``accept`` (default) or
    ``cancel``.
``FAKE_KEYRING_STATE``
    A file holding the keyring's state between processes, so a
    ``vault unlock`` in one process is what a later run finds.
``FAKE_KEYRING_CALLS``
    A file that receives one line per touch — ``import``, ``dbus_init``,
    ``get_secret``, and ``unlock`` (an unlock prompt was requested).
``FAKE_KEYRING_KEY``
    The stored vault key, hex.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__version_tuple__ = (3, 5, 0)

_DEFAULT = "/org/freedesktop/secrets/aliases/default"


def _record(what: str) -> None:
    path = os.environ.get("FAKE_KEYRING_CALLS")
    if path:
        with Path(path).open("a", encoding="utf-8") as calls:
            calls.write(f"{what}\n")


_record("import")


class SecretStorageException(Exception):  # noqa: N818 - mirrors secretstorage
    pass


class ItemNotFoundException(SecretStorageException):  # noqa: N818 - mirrors secretstorage
    pass


class LockedException(SecretStorageException):  # noqa: N818 - mirrors secretstorage
    pass


class SecretServiceNotAvailableException(SecretStorageException):  # noqa: N818 - mirrors secretstorage
    pass


def _mode() -> str:
    return os.environ.get("FAKE_KEYRING_MODE", "unlocked")


def _load() -> dict[str, Any]:
    path = Path(os.environ["FAKE_KEYRING_STATE"])
    if path.exists():
        return dict(json.loads(path.read_text()))
    mode = _mode()
    secret = None if mode == "empty" else os.environ.get("FAKE_KEYRING_KEY")
    return {"locked": mode == "locked", "secret": secret}


def _save(state: dict[str, Any]) -> None:
    Path(os.environ["FAKE_KEYRING_STATE"]).write_text(json.dumps(state))


class _Connection:
    def close(self) -> None:
        pass

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def dbus_init() -> _Connection:
    _record("dbus_init")
    mode = _mode()
    if mode == "raises":
        msg = "the keyring was touched by a run that must not touch it"
        raise AssertionError(msg)
    if mode == "absent":
        msg = "no Secret Service on the bus"
        raise SecretServiceNotAvailableException(msg)
    return _Connection()


def check_service_availability(connection: object) -> bool:
    return _mode() != "absent"


class _Item:
    def get_secret(self) -> bytes:
        state = _load()
        if state["locked"]:
            msg = "Item is locked!"
            raise LockedException(msg)
        _record("get_secret")
        return str(state["secret"]).encode()

    def is_locked(self) -> bool:
        return bool(_load()["locked"])


class Collection:
    def __init__(self, connection: object, collection_path: str = _DEFAULT) -> None:
        if collection_path != _DEFAULT:
            raise ItemNotFoundException(collection_path)
        self.connection = connection

    def is_locked(self) -> bool:
        return bool(_load()["locked"])

    def search_items(self, attributes: dict[str, str]) -> Any:
        if _load()["secret"] is not None:
            yield _Item()

    def unlock(self) -> bool:
        """Returns whether the prompt was dismissed, as `secretstorage` does."""
        _record("unlock")
        if os.environ.get("FAKE_KEYRING_UNLOCK", "accept") == "cancel":
            return True
        state = _load()
        state["locked"] = False
        _save(state)
        return False


def get_default_collection(connection: object, session: object = None) -> Collection:
    return Collection(connection)


#: What the shim's ``secretstorage.exceptions`` re-exports.
EXCEPTIONS = (
    "SecretStorageException",
    "ItemNotFoundException",
    "LockedException",
    "SecretServiceNotAvailableException",
)
