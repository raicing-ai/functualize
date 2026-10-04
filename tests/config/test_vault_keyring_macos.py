"""The macOS adapter reads with interaction disabled, under one process-wide guard.

Runs on any OS: the adapter's real ctypes layer runs over a fake Security
framework. Whether the real framework behaves as the fake does is what the
macOS CI smoke job and the manual checklist decide.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from typing import Any

import pytest

import functualize._config.vault_keyring_macos as macos
from functualize._config.vault_keyring import AdapterOutcome, AdapterRead, UnlockHow
from functualize._config.vault_keyring_macos import MacKeychainAdapter
from tests.contracts._fake_platforms import Answer, Recorder, World, mac_adapter

_SECRET = "ef" * 32


class TestInteractionIsDisabledAroundTheRead:
    def test_a_silent_read_runs_with_interaction_off(self) -> None:
        adapter, keychain = mac_adapter(World.UNLOCKED, _SECRET, Recorder())
        adapter.read_silent()
        assert keychain.copies == [False]

    def test_it_is_put_back_afterwards(self) -> None:
        adapter, keychain = mac_adapter(World.LOCKED, _SECRET, Recorder())
        adapter.read_silent()
        assert keychain.allowed is True

    def test_it_is_put_back_and_released_even_when_the_read_raises(self) -> None:
        adapter, keychain = mac_adapter(World.UNLOCKED, _SECRET, Recorder())

        def boom(query: Any, out: Any) -> int:
            raise RuntimeError("Security framework failure")

        keychain.SecItemCopyMatching = boom  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            adapter.read_silent()
        assert keychain.allowed is True
        assert not macos._INTERACTION_LOCK.locked()

    def test_a_silent_store_runs_with_interaction_off(self) -> None:
        recorder = Recorder()
        adapter, keychain = mac_adapter(World.LOCKED, _SECRET, recorder)
        assert adapter.store_silent(_SECRET) is AdapterOutcome.LOCKED
        assert recorder.prompts == 0
        assert keychain.allowed is True

    def test_unlock_reads_with_interaction_on(self) -> None:
        adapter, keychain = mac_adapter(
            World.LOCKED, _SECRET, Recorder(answer=Answer.ACCEPT)
        )
        read = adapter.unlock()
        assert keychain.copies == [False, True]
        assert read.how is UnlockHow.UNLOCKED_NOW

    def test_a_held_flag_is_locked_not_waited_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unlock dialog elsewhere in this process holds the flag for as long
        as the person takes; a silent read answers LOCKED instead of waiting."""
        monkeypatch.setattr(macos, "_SILENT_WAIT_SECONDS", 0.05)
        adapter, keychain = mac_adapter(World.UNLOCKED, _SECRET, Recorder())
        with macos._INTERACTION_LOCK:
            read = adapter.read_silent()
            stored = adapter.store_silent(_SECRET)
        assert read.outcome is AdapterOutcome.LOCKED
        assert stored is AdapterOutcome.LOCKED
        assert keychain.copies == []


class TestTwoAdaptersInOneProcess:
    """The process-wide interaction flag cannot turn a silent read into a prompt.

    Two adapters, each with its own ctypes layer, over one Security framework —
    two apps in one process, as `select_adapter` builds them. While the
    reader's silent read is in flight, the other adapter's `unlock()` tries to
    turn interaction on for its own dialog. Guarded per adapter, it could, and
    the reader's read prompted; guarded per process, it waits.
    """

    def test_a_silent_read_stays_silent_while_another_adapter_unlocks(self) -> None:
        recorder = Recorder(answer=Answer.ACCEPT)
        reader, keychain = mac_adapter(World.LOCKED, _SECRET, recorder)
        unlocker, _ = mac_adapter(World.LOCKED, _SECRET, recorder, keychain=keychain)
        reader_in_read = threading.Event()
        turned_on = threading.Event()

        def hold_the_read_open() -> None:
            if threading.current_thread().name == "reader":
                reader_in_read.set()
                # Long enough for an unguarded unlocker to turn interaction on.
                turned_on.wait(0.5)

        def note_the_flag(allowed: bool) -> None:
            if allowed and threading.current_thread().name == "unlocker":
                turned_on.set()

        keychain.on_copy = hold_the_read_open
        keychain.on_set = note_the_flag
        reads: list[AdapterRead] = []
        reading = threading.Thread(
            target=lambda: reads.append(reader.read_silent()), name="reader"
        )
        unlocking = threading.Thread(target=unlocker.unlock, name="unlocker")

        reading.start()
        assert reader_in_read.wait(2.0)
        unlocking.start()
        reading.join(5.0)
        unlocking.join(5.0)

        assert reads[0].outcome is AdapterOutcome.LOCKED
        # One prompt: the unlocker's own dialog, after the read. None from the read.
        assert recorder.prompts == 1
        assert keychain.world is World.UNLOCKED


class TestStatusCodes:
    def test_interaction_not_allowed_is_locked(self) -> None:
        adapter, _ = mac_adapter(World.LOCKED, _SECRET, Recorder())
        assert adapter.read_silent().outcome is AdapterOutcome.LOCKED

    def test_a_cancelled_dialog_is_cancelled(self) -> None:
        adapter, _ = mac_adapter(World.LOCKED, _SECRET, Recorder(answer=Answer.CANCEL))
        read = adapter.unlock()
        assert read.outcome is AdapterOutcome.LOCKED
        assert read.how is UnlockHow.CANCELLED

    @pytest.mark.parametrize(
        ("status", "outcome"),
        [
            (0, AdapterOutcome.FOUND),
            (-25308, AdapterOutcome.LOCKED),
            (-25293, AdapterOutcome.LOCKED),
            (-25291, AdapterOutcome.NO_KEYRING),
        ],
    )
    def test_a_store_status_maps_to_its_outcome(
        self, status: int, outcome: AdapterOutcome
    ) -> None:
        adapter, keychain = mac_adapter(World.EMPTY, _SECRET, Recorder())
        keychain.SecItemAdd = lambda *_: status  # type: ignore[method-assign]
        assert adapter.store_silent(_SECRET) is outcome


class TestTheFrameworkIsLoadedOnlyWhenUsed:
    def test_importing_the_adapter_loads_no_keyring(self) -> None:
        code = (
            "import sys;"
            "import functualize._config.vault_keyring_macos;"
            "loaded = [m for m in ('keyring', 'keyring.backends.macOS') if m in sys.modules];"
            "assert not loaded, loaded"
        )
        subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603

    def test_off_a_mac_there_is_no_keyring(self) -> None:
        """`keyring`'s macOS api module cannot load here; the adapter says
        "no keyring" rather than raising."""
        if sys.platform == "darwin":  # pragma: no cover - the CI smoke covers macOS
            return
        adapter = MacKeychainAdapter("functualize-vault", "vault-key")
        assert adapter.read_silent().outcome is AdapterOutcome.NO_KEYRING
