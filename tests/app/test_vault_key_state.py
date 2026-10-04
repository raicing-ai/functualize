"""`vault_key_state` — the one status function every surface uses (spec B8, A13).

Never prompts, never unlocks, never reads the secret, never raises; answers
within about 250 ms; with the env key set it never touches a keyring; and a
surface that polls it is served from a short cache on the app's resolver.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest

from functualize._config.vault import KEY_BYTES, SecretsVault
from functualize._config.vault_paths import vault_path_for_project
from functualize.app import FunctualizeApp, JobSources
from functualize.app.vault import VaultKeyStatus, vault_key_state
from functualize.plugin import KeyAvailability

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_KEY = b"\x44" * KEY_BYTES


class _Keyring:
    """A keyring-shaped provider that counts every way it could be touched."""

    def __init__(
        self,
        state: KeyAvailability = KeyAvailability.UNKNOWN,
        *,
        available: bool = True,
        hang: float = 0.0,
        raises: bool = False,
    ) -> None:
        self._state = state
        self._available = available
        self._hang = hang
        self._raises = raises
        self.get_key_calls = 0
        self.unlock_calls = 0
        self.probe_calls = 0
        self.calls = 0

    def identifier(self) -> str:
        self.calls += 1
        return "keychain"

    def interactive(self) -> bool:
        self.calls += 1
        return False

    def is_available(self) -> bool:
        self.calls += 1
        return self._available

    def get_key(self, project_id: str) -> bytes | None:
        self.calls += 1
        self.get_key_calls += 1
        return _KEY

    def probe(self) -> KeyAvailability:
        self.calls += 1
        self.probe_calls += 1
        if self._hang:
            time.sleep(self._hang)
        if self._raises:
            msg = "the bus fell over"
            raise RuntimeError(msg)
        return self._state

    def unlock(self) -> bool:
        self.calls += 1
        self.unlock_calls += 1
        return True


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".functualize").mkdir()
    (tmp_path / "jobs").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FUNCTUALIZE_VAULT_KEY", raising=False)
    return tmp_path


@pytest.fixture
def with_vault(project: Path) -> Path:
    SecretsVault(vault_path_for_project(project)).put(
        "deploy.api_token", "v", encryption_key=_KEY, provider="p", annotation="a"
    )
    return project


@pytest.fixture
def only(monkeypatch: pytest.MonkeyPatch) -> Callable[[_Keyring], _Keyring]:
    def install(fake: _Keyring) -> _Keyring:
        monkeypatch.setattr(
            "functualize._config.vault_key_resolver.default_providers",
            lambda: (fake,),
        )
        return fake

    return install


class TestWhatItAnswers:
    def test_no_vault_file_is_not_applicable(self, project: Path, only: Any) -> None:
        fake = only(_Keyring(KeyAvailability.UNLOCKED))
        assert vault_key_state(cwd=project).status is VaultKeyStatus.NOT_APPLICABLE
        assert fake.calls == 0

    def test_the_env_key_answers_without_a_keyring(
        self, with_vault: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._config.vault_keys import EnvKeyProvider

        monkeypatch.setenv("FUNCTUALIZE_VAULT_KEY", _KEY.hex())
        fake = _Keyring(KeyAvailability.LOCKED)
        monkeypatch.setattr(
            "functualize._config.vault_key_resolver.default_providers",
            lambda: (EnvKeyProvider(), fake),
        )
        state = vault_key_state(cwd=with_vault)
        assert state.status is VaultKeyStatus.UNLOCKED
        assert state.source == "env"
        assert fake.calls == 0

    def test_a_locked_keyring_is_locked_with_no_read_and_no_prompt(
        self, with_vault: Path, only: Any
    ) -> None:
        fake = only(_Keyring(KeyAvailability.LOCKED))
        state = vault_key_state(cwd=with_vault)
        assert state.status is VaultKeyStatus.LOCKED
        assert fake.get_key_calls == 0
        assert fake.unlock_calls == 0

    def test_an_unlocked_keyring_is_unlocked_without_reading_the_key(
        self, with_vault: Path, only: Any
    ) -> None:
        fake = only(_Keyring(KeyAvailability.UNLOCKED))
        assert vault_key_state(cwd=with_vault).status is VaultKeyStatus.UNLOCKED
        assert fake.get_key_calls == 0

    def test_no_reachable_keyring_is_no_keyring(
        self, with_vault: Path, only: Any
    ) -> None:
        only(_Keyring(available=False))
        assert vault_key_state(cwd=with_vault).status is VaultKeyStatus.NO_KEYRING


class TestItIsCheapAndSafe:
    def test_a_hung_backend_answers_unknown_within_the_cap(
        self, with_vault: Path, only: Any
    ) -> None:
        only(_Keyring(hang=5.0))
        started = time.monotonic()
        state = vault_key_state(cwd=with_vault)
        assert time.monotonic() - started < 1.0
        assert state.status is VaultKeyStatus.UNKNOWN

    def test_it_never_raises(self, with_vault: Path, only: Any) -> None:
        only(_Keyring(raises=True))
        assert vault_key_state(cwd=with_vault).status is VaultKeyStatus.UNKNOWN

    def test_repeated_calls_are_served_from_the_apps_cache(
        self, with_vault: Path, only: Any
    ) -> None:
        """The app's own resolver holds the answer, so a polling surface costs
        one probe per window, not one per poll."""
        fake = only(_Keyring(KeyAvailability.LOCKED))
        app = FunctualizeApp(
            "statelab",
            job_sources=JobSources(directories=[str(with_vault / "jobs")], lazy=False),
        )
        app.resolution_chain()
        for _ in range(5):
            assert vault_key_state(app, cwd=with_vault).status is VaultKeyStatus.LOCKED
        assert fake.probe_calls == 1


class TestWhereItCameFrom:
    def test_the_keychain_names_its_adapter_and_whether_the_key_is_stored(
        self, with_vault: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._config.vault_keyring import AdapterOutcome, AdapterRead
        from functualize._config.vault_keys import KeychainKeyProvider

        class _Adapter:
            name = "linux"
            secret_reads = 0

            def read_silent(self) -> AdapterRead:
                _Adapter.secret_reads += 1
                return AdapterRead(AdapterOutcome.FOUND, secret=_KEY.hex())

            def state(self) -> KeyAvailability:
                return KeyAvailability.UNLOCKED

            def unlock(self) -> AdapterRead:
                raise AssertionError("the state probe never unlocks")

            def has_entry(self) -> bool:
                return True

        class _Keychain(KeychainKeyProvider):
            def is_available(self) -> bool:
                return True

        keychain = _Keychain(adapter=_Adapter())  # type: ignore[arg-type]
        monkeypatch.setattr(
            "functualize._config.vault_key_resolver.default_providers",
            lambda: (keychain,),
        )
        state = vault_key_state(cwd=with_vault)
        assert state.status is VaultKeyStatus.UNLOCKED
        assert state.source == "linux"
        assert state.key_stored is True
        assert _Adapter.secret_reads == 0
