"""A `keyring` backend for `func` subprocesses, selected by `PYTHON_KEYRING_BACKEND`.

``PYTHON_KEYRING_BACKEND=tests.integration._fake_keyring.FakeKeyring`` (with
the repository root on ``PYTHONPATH``) makes a child process's OS keyring this
class, so an end-to-end test can drive the real ``func`` console script with
stdout piped and still decide what the keyring does:

``FAKE_KEYRING_MODE``
    ``unlocked`` (default) answers with ``FAKE_KEYRING_KEY``; ``locked-blocks``
    never answers, like a locked keyring whose unlock dialog nobody answers;
    ``raises`` fails on any call, for runs that must not touch the keyring.
``FAKE_KEYRING_CALLS``
    A file that receives one line per construction and per call, so the
    parent process can count what the child asked — including that it asked
    nothing at all.
"""

from __future__ import annotations

import os
import time

from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError, PasswordSetError


def _record(what: str) -> None:
    path = os.environ.get("FAKE_KEYRING_CALLS")
    if path:
        with open(path, "a", encoding="utf-8") as calls:  # noqa: PTH123
            calls.write(f"{what}\n")


class FakeKeyring(KeyringBackend):
    """The keyring a test says it is."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        _record("init")

    def get_password(self, service: str, username: str) -> str | None:
        _record("get_password")
        mode = os.environ.get("FAKE_KEYRING_MODE", "unlocked")
        if mode == "raises":
            msg = "the keyring was touched by a run that must not touch it"
            raise AssertionError(msg)
        if mode == "locked-blocks":
            time.sleep(3600)
        return os.environ.get("FAKE_KEYRING_KEY") or None

    def set_password(self, service: str, username: str, password: str) -> None:
        _record("set_password")
        msg = "this fake keyring is read-only"
        raise PasswordSetError(msg)

    def delete_password(self, service: str, username: str) -> None:
        _record("delete_password")
        msg = "this fake keyring is read-only"
        raise PasswordDeleteError(msg)
