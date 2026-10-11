"""`vault status` reports the key's state without ever opening a keyring.

Spec A8: against a locked keyring status returns without invoking the unlock
path and says ``locked``; against an unlocked one it reads silently and says
``available``; against a backend that cannot say, ``unknown``. And
``vault sync`` waits on the keyring no longer than the configured timeout.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest

from functualize._config.vault import KEY_BYTES, KeyringLockedError
from functualize.app.utils import VaultKeyUnavailableError, vault_status, vault_sync
from functualize.plugin import KeyAvailability

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_KEY = b"\x33" * KEY_BYTES


class _FakeKeyring:
    """A keyring-shaped provider that counts reads; no probe."""

    def __init__(
        self,
        *,
        key: bytes | None = _KEY,
        locked: bool = False,
        delay: float = 0.0,
        available: bool = True,
    ) -> None:
        self._key = key
        self._locked = locked
        self._delay = delay
        self._available = available
        self.get_key_calls = 0

    def identifier(self) -> str:
        return "keychain"

    def interactive(self) -> bool:
        return False

    def is_available(self) -> bool:
        return self._available

    def get_key(self, project_id: str) -> bytes | None:
        self.get_key_calls += 1
        if self._delay:
            time.sleep(self._delay)
        if self._locked:
            msg = "locked"
            raise KeyringLockedError(msg)
        return self._key


class _ProbedKeyring(_FakeKeyring):
    def __init__(self, probe: KeyAvailability, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._probe = probe
        self.probe_calls = 0

    def probe(self) -> KeyAvailability:
        self.probe_calls += 1
        return self._probe


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".functualize").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FUNCTUALIZE_VAULT_KEY", raising=False)
    monkeypatch.delenv("FUNCTUALIZE_VAULT_KEYRING_TIMEOUT", raising=False)
    return tmp_path


@pytest.fixture
def only(monkeypatch: pytest.MonkeyPatch) -> Callable[[_FakeKeyring], _FakeKeyring]:
    """Make the given fake the only provider the resolver sees."""

    def install(fake: _FakeKeyring) -> _FakeKeyring:
        monkeypatch.setattr(
            "functualize._config.vault_key_resolver.default_providers",
            lambda: (fake,),
        )
        return fake

    return install


@pytest.fixture
def with_vault(project: Path) -> Path:
    """A project that has a vault file — the only case with a key state."""
    from functualize._config.vault import SecretsVault
    from functualize._config.vault_paths import vault_path_for_project

    SecretsVault(vault_path_for_project(project)).put(
        "deploy.api_token", "v", encryption_key=_KEY, provider="p", annotation="a"
    )
    return project


class TestKeyState:
    def test_a_locked_keyring_is_reported_and_never_read(
        self, with_vault: Path, only: Any
    ) -> None:
        fake = only(_ProbedKeyring(KeyAvailability.LOCKED))
        report = vault_status(cwd=with_vault)
        assert report.key_state == "locked"
        assert report.key_provider is None
        assert fake.get_key_calls == 0
        assert fake.probe_calls == 1

    def test_an_unlocked_keyring_is_read_silently(
        self, with_vault: Path, only: Any
    ) -> None:
        fake = only(_ProbedKeyring(KeyAvailability.UNLOCKED))
        report = vault_status(cwd=with_vault)
        assert report.key_state == "available"
        assert report.key_provider == "keychain"
        assert report.key_matches_store is True
        assert fake.get_key_calls == 1

    def test_a_backend_that_cannot_say_is_unknown(
        self, with_vault: Path, only: Any
    ) -> None:
        fake = only(_FakeKeyring())
        report = vault_status(cwd=with_vault)
        assert report.key_state == "unknown"
        assert report.key_provider is None
        assert fake.get_key_calls == 0

    def test_an_env_key_is_available(
        self, with_vault: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FUNCTUALIZE_VAULT_KEY", _KEY.hex())
        report = vault_status(cwd=with_vault)
        assert report.key_state == "available"
        assert report.key_provider == "env"

    def test_no_vault_file_has_no_key_state(self, project: Path) -> None:
        assert vault_status(cwd=project).key_state is None


class _DbField:
    name = "password"
    secret = True


class _DbSpec:
    group = "db"
    fields = (_DbField(),)


class _SyncApp:
    """Just enough app for `vault_sync`: one provider, one declaration."""

    class _Registry:
        def list_remote_providers(self) -> list[str]:
            return ["fake-sm"]

    class _FileSource:
        source_type = "file"
        per_file_values = [
            (
                "config.toml",
                {
                    "vault_secret": [
                        {"group": "db", "field": "password", "source": "fake-sm://p"}
                    ]
                },
            )
        ]

    class _Chain:
        sources = [None]

    def get_group_options_spec(self, group_path: str) -> Any:
        return _DbSpec() if group_path == "db" else None

    def __init__(self) -> None:
        self.config_registry = self._Registry()
        self._resolution_chain = self._Chain()
        self._resolution_chain.sources = [self._FileSource()]
        self._config_sources = None


class TestSyncIsBounded:
    def test_a_keyring_that_never_answers_costs_the_configured_wait(
        self, project: Path, only: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FUNCTUALIZE_VAULT_KEYRING_TIMEOUT", "1s")
        only(_FakeKeyring(delay=5.0))
        started = time.monotonic()
        with pytest.raises(VaultKeyUnavailableError) as exc:
            vault_sync(_SyncApp(), cwd=project)
        assert time.monotonic() - started < 3.0
        assert exc.value.reason == "key_locked"
        assert "did not answer within 1s" in str(exc.value)

    @pytest.mark.parametrize(
        ("fake", "reason"),
        [
            (_FakeKeyring(locked=True), "key_locked"),
            (_FakeKeyring(available=False), "no_keyring"),
            (_FakeKeyring(key=None), "key_not_stored"),
        ],
    )
    def test_the_refusal_names_why(
        self, project: Path, only: Any, fake: _FakeKeyring, reason: str
    ) -> None:
        only(fake)
        with pytest.raises(VaultKeyUnavailableError) as exc:
            vault_sync(_SyncApp(), cwd=project)
        assert exc.value.reason == reason
        if reason != "key_not_stored":
            assert "vault remove" not in str(exc.value)
            assert "vault clear" not in str(exc.value)
