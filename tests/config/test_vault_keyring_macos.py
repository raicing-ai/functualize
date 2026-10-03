"""The macOS adapter reads with interaction disabled per call, never per process.

Runs on any OS: the Security framework is behind a small seam and faked here.
Whether the real framework behaves as the fake does is what the macOS CI smoke
job and the manual checklist decide.
"""

from __future__ import annotations

import subprocess
import sys
import threading

import pytest

from functualize._config.vault_keyring import AdapterOutcome, AdapterRead, UnlockHow
from functualize._config.vault_keyring_macos import MacKeychainAdapter
from tests.contracts._fake_platforms import (
    Answer,
    FakeSecurity,
    Recorder,
    World,
    mac_adapter,
)

_SECRET = "ef" * 32


class TestInteractionIsDisabledPerCall:
    def test_a_silent_read_asks_the_call_to_fail_rather_than_show_ui(self) -> None:
        adapter, security = mac_adapter(World.UNLOCKED, _SECRET, Recorder())
        adapter.read_silent()
        assert [interactive for interactive, _ in security.copies] == [False]

    def test_a_silent_read_leaves_the_process_wide_flag_alone(self) -> None:
        adapter, security = mac_adapter(World.LOCKED, _SECRET, Recorder())
        flips: list[bool] = []
        security.set_interaction_allowed = flips.append  # type: ignore[method-assign]
        adapter.read_silent()
        adapter.store_silent(_SECRET)
        assert flips == []

    def test_unlock_reads_with_interaction_on_and_puts_it_back(self) -> None:
        adapter, security = mac_adapter(
            World.LOCKED, _SECRET, Recorder(answer=Answer.ACCEPT)
        )
        security.allowed = False
        read = adapter.unlock()
        assert security.copies == [(False, False), (True, True)]
        assert read.how is UnlockHow.UNLOCKED_NOW
        assert security.allowed is False

    def test_unlock_puts_the_flag_back_even_when_the_read_raises(self) -> None:
        adapter, security = mac_adapter(World.LOCKED, _SECRET, Recorder())
        real = security.copy_password

        def boom(service: str, account: str, *, interactive: bool) -> tuple[int, None]:
            if interactive:
                raise RuntimeError("Security framework failure")
            return real(service, account, interactive=interactive)  # type: ignore[return-value]

        security.copy_password = boom  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            adapter.unlock()
        assert security.allowed is True


class TestTwoAdaptersInOneProcess:
    """The process-wide interaction flag cannot turn a silent read into a prompt.

    Two adapters share one ``FakeSecurity`` — one process. While the reader's
    silent read is in flight, the other adapter's ``unlock()`` turns
    interaction on for its own dialog. With the flag as the only guard, the
    reader's read would see interaction on and prompt; the per-call option
    keeps it silent.
    """

    def test_a_silent_read_stays_silent_while_another_adapter_unlocks(self) -> None:
        recorder = Recorder(answer=Answer.ACCEPT)
        security = FakeSecurity(World.LOCKED, _SECRET, recorder)
        reader = MacKeychainAdapter("functualize-vault", "vault-key", security=security)
        unlocker = MacKeychainAdapter(
            "functualize-vault", "vault-key", security=security
        )
        reader_in_read = threading.Event()
        interaction_on = threading.Event()
        reader_done = threading.Event()

        def interleave(interactive: bool) -> None:
            name = threading.current_thread().name
            if name == "reader":
                reader_in_read.set()
                interaction_on.wait(2.0)
            elif name == "unlocker" and interactive and security.allowed:
                # The unlocker's dialog is up, interaction is on, and the
                # keychain is still locked: the reader reads now.
                interaction_on.set()
                reader_done.wait(2.0)

        security.on_copy = interleave
        reads: list[AdapterRead] = []

        def read() -> None:
            reads.append(reader.read_silent())
            reader_done.set()

        reading = threading.Thread(target=read, name="reader")
        unlocking = threading.Thread(target=unlocker.unlock, name="unlocker")
        reading.start()
        assert reader_in_read.wait(2.0)
        unlocking.start()
        reading.join(5.0)
        unlocking.join(5.0)

        assert interaction_on.is_set(), "the unlocker never reached its dialog"
        assert reads[0].outcome is AdapterOutcome.LOCKED
        # One prompt: the unlocker's own dialog. None from the silent read.
        assert recorder.prompts == 1


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
        adapter, security = mac_adapter(World.EMPTY, _SECRET, Recorder())
        security.add_password = lambda *_: status  # type: ignore[method-assign]
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
