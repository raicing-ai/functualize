"""The Windows adapter: Credential Manager has no lock, so nothing ever prompts.

Runs on any OS with a fake backend. Whether real Credential Manager behaves the
same is what the Windows CI smoke job decides.
"""

from __future__ import annotations

import subprocess
import sys

from functualize._config.vault_keyring import AdapterOutcome, UnlockHow
from functualize._config.vault_keyring_windows import WindowsCredentialAdapter
from functualize._types.enums import KeyAvailability
from tests.contracts._fake_platforms import FakeWinLoader, Recorder, World

_SECRET = "12" * 32


def _adapter(world: World) -> WindowsCredentialAdapter:
    return WindowsCredentialAdapter(
        "functualize-vault",
        "vault-key",
        loader=FakeWinLoader(world, _SECRET, Recorder()),
    )


class TestNothingToUnlock:
    def test_unlock_reads_and_says_there_was_nothing_to_do(self) -> None:
        read = _adapter(World.UNLOCKED).unlock()
        assert read.outcome is AdapterOutcome.FOUND
        assert read.how is UnlockHow.NOTHING_TO_UNLOCK

    def test_nothing_stored_is_still_nothing_to_unlock(self) -> None:
        read = _adapter(World.EMPTY).unlock()
        assert read.outcome is AdapterOutcome.NOT_STORED
        assert read.how is UnlockHow.NOTHING_TO_UNLOCK

    def test_state_is_unlocked_whenever_it_is_there(self) -> None:
        assert _adapter(World.UNLOCKED).state() is KeyAvailability.UNLOCKED
        assert _adapter(World.ABSENT).state() is KeyAvailability.UNKNOWN


class TestTheBackendIsLoadedOnlyWhenUsed:
    def test_importing_the_adapter_loads_no_windows_library(self) -> None:
        code = (
            "import sys;"
            "import functualize._config.vault_keyring_windows;"
            "loaded = [m for m in ('keyring', 'win32ctypes') if m in sys.modules];"
            "assert not loaded, loaded"
        )
        subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603

    def test_off_windows_there_is_no_keyring(self) -> None:
        if sys.platform == "win32":  # pragma: no cover - the CI smoke covers Windows
            return
        adapter = WindowsCredentialAdapter("functualize-vault", "vault-key")
        assert adapter.read_silent().outcome is AdapterOutcome.NO_KEYRING
