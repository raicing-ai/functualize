"""The macOS adapter reads with interaction disabled, and always restores it.

Runs on any OS: the Security framework is behind a four-call seam and faked
here. Whether the real framework behaves as the fake does is what the macOS CI
smoke job and the manual checklist decide (the adapter is unverified on a real
Mac until then).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from functualize._config.vault_keyring import AdapterOutcome, UnlockHow
from functualize._config.vault_keyring_macos import MacKeychainAdapter
from tests.contracts._fake_platforms import Answer, Recorder, World, mac_adapter

_SECRET = "ef" * 32


class TestInteractionIsDisabledAroundTheRead:
    def test_a_silent_read_runs_with_interaction_off(self) -> None:
        adapter, security = mac_adapter(World.UNLOCKED, _SECRET, Recorder())
        adapter.read_silent()
        assert security.allowed_at_copy == [False]

    def test_it_is_put_back_afterwards(self) -> None:
        adapter, security = mac_adapter(World.LOCKED, _SECRET, Recorder())
        security.allowed = True
        adapter.read_silent()
        assert security.allowed is True

    def test_it_is_put_back_even_when_the_read_raises(self) -> None:
        adapter, security = mac_adapter(World.UNLOCKED, _SECRET, Recorder())

        def boom(service: str, account: str) -> tuple[int, str | None]:
            raise RuntimeError("Security framework failure")

        security.copy_password = boom  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            adapter.read_silent()
        assert security.allowed is True

    def test_unlock_reads_with_interaction_on(self) -> None:
        adapter, security = mac_adapter(
            World.LOCKED, _SECRET, Recorder(answer=Answer.ACCEPT)
        )
        read = adapter.unlock()
        assert security.allowed_at_copy == [False, True]
        assert read.how is UnlockHow.UNLOCKED_NOW


class TestStatusCodes:
    def test_interaction_not_allowed_is_locked(self) -> None:
        adapter, _ = mac_adapter(World.LOCKED, _SECRET, Recorder())
        assert adapter.read_silent().outcome is AdapterOutcome.LOCKED

    def test_a_cancelled_dialog_is_cancelled(self) -> None:
        adapter, _ = mac_adapter(World.LOCKED, _SECRET, Recorder(answer=Answer.CANCEL))
        read = adapter.unlock()
        assert read.outcome is AdapterOutcome.LOCKED
        assert read.how is UnlockHow.CANCELLED


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
