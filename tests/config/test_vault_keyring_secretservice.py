"""The Linux adapter reads the Secret Service without ever prompting.

The shared contract (`tests/contracts/`) holds it to the rules every adapter
keeps; these are the Linux-specific ones: it reads exactly the item `keyring`
wrote (attribute scheme and preferred collection), it never creates a
collection (that prompts), it never loads `secretstorage` until used, and the
"no dialog appeared" report applies only where it can be told.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from functualize._config.vault_keyring import AdapterOutcome, UnlockHow
from functualize._config.vault_keyring_secretservice import SecretServiceAdapter
from tests.contracts._fake_platforms import (
    Answer,
    FakeBusNames,
    FakeSecretService,
    FakeSecretStorageModule,
    Recorder,
    World,
    secret_service_adapter,
)

if TYPE_CHECKING:
    import pytest

_SECRET = "cd" * 32


class TestItReadsWhatKeyringWrote:
    def test_the_backend_scheme_names_the_attributes(self) -> None:
        """KeePassXC's scheme spells the attributes differently."""

        class _Backend:
            schemes = {"KeePassXC": {"username": "UserName", "service": "Title"}}
            scheme = "KeePassXC"

        recorder = Recorder()
        service = FakeSecretService(
            World.UNLOCKED,
            _SECRET,
            recorder,
            attributes={"UserName": "vault-key", "Title": "functualize-vault"},
        )
        adapter = SecretServiceAdapter(
            "functualize-vault",
            "vault-key",
            backend=_Backend(),
            module=FakeSecretStorageModule(service),
            bus_names=FakeBusNames(recorder),
        )
        assert adapter.read_silent().secret == _SECRET

    def test_the_preferred_collection_is_the_one_read(self) -> None:
        """`KEYRING_PROPERTY_PREFERRED_COLLECTION` points `keyring` at a
        collection; the adapter reads that one, never the default."""
        path = "/org/freedesktop/secrets/collection/throwaway"

        class _Backend:
            preferred_collection = path

        recorder = Recorder()
        service = FakeSecretService(
            World.UNLOCKED, _SECRET, recorder, collections=(path,)
        )
        adapter = SecretServiceAdapter(
            "functualize-vault",
            "vault-key",
            backend=_Backend(),
            module=FakeSecretStorageModule(service),
            bus_names=FakeBusNames(recorder),
        )
        assert adapter.read_silent().secret == _SECRET
        assert service.opened == [path]


class TestItNeverCreatesACollection:
    def test_a_missing_collection_is_nothing_stored(self) -> None:
        recorder = Recorder()
        service = FakeSecretService(World.UNLOCKED, _SECRET, recorder, collections=())
        adapter = SecretServiceAdapter(
            "functualize-vault",
            "vault-key",
            module=FakeSecretStorageModule(service),
            bus_names=FakeBusNames(recorder),
        )
        assert adapter.read_silent().outcome is AdapterOutcome.NOT_STORED
        assert service.created == []
        assert recorder.prompts == 0


class TestTheMissingDialogReport:
    def test_it_is_reported_when_gnome_keyring_has_no_prompter(self) -> None:
        adapter, _ = secret_service_adapter(
            World.LOCKED, _SECRET, Recorder(answer=Answer.NO_DIALOG)
        )
        read = adapter.unlock()
        assert read.outcome is AdapterOutcome.LOCKED
        assert read.how is UnlockHow.NO_PROMPT

    def test_elsewhere_a_slow_dialog_is_waited_for(self) -> None:
        """Not gnome-keyring: its prompter name means nothing, so a dialog
        that takes longer than the watcher's window is still waited for."""

        class _NoPrompterAnywhere:
            def has_owner(self, name: str) -> bool | None:
                return False

        recorder = Recorder(answer=Answer.ACCEPT)
        adapter, service = secret_service_adapter(
            World.LOCKED, _SECRET, recorder, bus_names=_NoPrompterAnywhere()
        )
        service.unlock_delay = 0.8  # longer than the 0.3 s watcher window
        read = adapter.unlock()
        assert read.outcome is AdapterOutcome.FOUND
        assert read.how is UnlockHow.UNLOCKED_NOW
        assert recorder.prompts == 1


class TestTheLibraryIsLoadedOnlyWhenUsed:
    def test_importing_the_adapter_loads_no_secretstorage(self) -> None:
        code = (
            "import sys;"
            "import functualize._config.vault_keyring_secretservice;"
            "loaded = [m for m in ('secretstorage', 'jeepney') if m in sys.modules];"
            "assert not loaded, loaded"
        )
        subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603

    def test_no_secretstorage_is_no_keyring(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "secretstorage", None)
        adapter = SecretServiceAdapter("functualize-vault", "vault-key")
        assert adapter.read_silent().outcome is AdapterOutcome.NO_KEYRING
        assert adapter.unlock().outcome is AdapterOutcome.NO_KEYRING
