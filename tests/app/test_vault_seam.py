"""The four public vault operations, exercised the way a user's code would.

These call `functualize.app.vault` directly rather than through `func`, which
is the point: the CLI is one caller of this seam, not where the behavior lives.
An app embedding functualize gets the same lifecycle with no CLI present.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from functualize._config.vault import (
    KeyringLockedError,
    VaultEntryExistsError,
    VaultOrigin,
    VaultOriginConflictError,
)
from functualize.app import FunctualizeApp, JobSources
from functualize.app.vault import (
    Readability,
    UnlockAbandonedError,
    VaultKeySourceError,
    VaultPathError,
    vault_init,
    vault_inspect,
    vault_put,
    vault_remove,
    vault_unlock,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_SECRET = "correct-horse-battery-staple-9f3a"  # gitleaks:allow

_JOB_SOURCE = '''
from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job
from functualize.types import Secret


class DeployConfig(BaseModel):
    region: str = Field(default="eu-west-1")
    api_token: Secret[str] = Field(description="Required credential")


@job
def deploy(config: DeployConfig, rc: RunContext) -> str:
    """Deploy something."""
    return "deployed"
'''


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with a key exported, the route that needs no keyring."""
    from functualize._config.vault_keys import ENV_VAR, generate_key

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "deploy.py").write_text(_JOB_SOURCE)
    (tmp_path / ".functualize").mkdir()
    monkeypatch.setenv(ENV_VAR, generate_key())
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def app(project: Path) -> FunctualizeApp:
    return FunctualizeApp(
        "vaultlab",
        job_sources=JobSources(directories=[str(project / "jobs")], lazy=False),
    )


class TestInit:
    def test_env_source_validates_and_writes_nothing(self, project: Path) -> None:
        """The CI preflight. It must not create a store as a side effect."""
        from functualize._config.vault_paths import vault_path_for_project

        report = vault_init(key_source="env", cwd=project)

        assert report.created is False
        assert report.key_provider == "env"
        assert report.key_scope == "user"
        assert not vault_path_for_project(project).exists()

    def test_an_unknown_source_is_refused_by_name(self, project: Path) -> None:
        with pytest.raises(VaultKeySourceError) as exc:
            vault_init(key_source="nosuchthing", cwd=project)
        assert exc.value.reason == "unknown_key_source"

    def test_env_cannot_create_a_key(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the operator can set an environment variable, so `init` says so
        and names the command that produces one."""
        from functualize._config.vault_keys import ENV_VAR

        monkeypatch.delenv(ENV_VAR)

        with pytest.raises(VaultKeySourceError) as exc:
            vault_init(key_source="env", cwd=project)

        assert exc.value.reason == "key_source_not_initializable"
        assert "vault keygen" in str(exc.value)

    def test_with_no_source_at_all_it_teaches_both_routes(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What a stock install meets. Naming only the missing half would send
        someone to install a keyring they may not want."""
        from functualize._config.vault_keys import ENV_VAR

        monkeypatch.delenv(ENV_VAR)
        monkeypatch.setattr(
            "functualize._config.vault_keys.KeychainKeyProvider.is_available",
            lambda self: False,
        )

        with pytest.raises(VaultKeySourceError) as exc:
            vault_init(cwd=project)

        message = str(exc.value)
        assert "functualize[keychain]" in message
        assert "FUNCTUALIZE_VAULT_KEY" in message
        assert exc.value.reason == "key_source_unavailable"

    def test_it_needs_no_app(self) -> None:
        """Signature-level. One key opens every project, so there is no project
        to discover and no app to boot."""
        import inspect

        assert "app" not in inspect.signature(vault_init).parameters


class TestPut:
    def test_it_stores_a_value_and_reports_metadata_only(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        report = vault_put(app, "deploy.api_token", _SECRET, cwd=project)

        assert report.path == "deploy.api_token"
        assert report.origin is VaultOrigin.DIRECT
        assert report.created is True
        assert _SECRET not in str(report)

    def test_a_bad_path_is_refused_before_the_value_is_used(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """Validation precedes storage, so a typo cannot half-commit."""
        from functualize._config.vault_paths import vault_path_for_project

        with pytest.raises(VaultPathError):
            vault_put(app, "deploy.region", _SECRET, cwd=project)

        assert not vault_path_for_project(project).exists()

    def test_a_second_write_needs_replace(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        vault_put(app, "deploy.api_token", _SECRET, cwd=project)

        with pytest.raises(VaultEntryExistsError):
            vault_put(app, "deploy.api_token", "other", cwd=project)

        report = vault_put(app, "deploy.api_token", "other", replace=True, cwd=project)
        assert report.replaced is True
        assert report.created is False

    def test_it_cannot_take_over_a_provider_entry(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        from functualize._config.vault import SecretsVault
        from functualize._config.vault_key_resolver import resolve_vault_key
        from functualize._config.vault_paths import vault_path_for_project

        resolution = resolve_vault_key("ignored")
        assert resolution.key is not None
        SecretsVault(vault_path_for_project(project)).put(
            "deploy.api_token",
            "from-aws",
            encryption_key=resolution.key,
            annotation="aws-sm://x",
            provider="aws-sm",
        )

        with pytest.raises(VaultOriginConflictError):
            vault_put(app, "deploy.api_token", _SECRET, replace=True, cwd=project)


class TestRemove:
    def test_it_removes_and_warns_only_for_a_direct_entry(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        vault_put(app, "deploy.api_token", _SECRET, cwd=project)

        report = vault_remove(app, "deploy.api_token", cwd=project)

        assert report.removed is True
        assert report.origin is VaultOrigin.DIRECT
        assert report.warning is not None

    def test_a_missing_entry_is_success(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        report = vault_remove(app, "deploy.api_token", cwd=project)

        assert report.removed is False
        assert report.origin is None

    def test_it_needs_no_key(
        self, app: FunctualizeApp, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The scenario the command exists for: the key is what you lost."""
        from functualize._config.vault_keys import ENV_VAR

        vault_put(app, "deploy.api_token", _SECRET, cwd=project)
        monkeypatch.delenv(ENV_VAR)

        assert vault_remove(app, "deploy.api_token", cwd=project).removed is True

    def test_an_orphan_from_a_deleted_job_can_still_be_removed(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """Why remove does not validate against the current schema.

        The entries most needing removal are the ones whose job was renamed or
        deleted. Requiring them to resolve would make the orphans this command
        exists to clear unreachable.
        """
        from functualize._config.vault import SecretsVault
        from functualize._config.vault_key_resolver import resolve_vault_key
        from functualize._config.vault_paths import vault_path_for_project

        resolution = resolve_vault_key("ignored")
        assert resolution.key is not None
        SecretsVault(vault_path_for_project(project)).put(
            "deleted-job.token",
            _SECRET,
            encryption_key=resolution.key,
            origin=VaultOrigin.DIRECT,
        )

        report = vault_remove(app, "deleted-job.token", cwd=project)

        assert report.removed is True


class TestInspect:
    def test_it_reports_a_stored_entry_without_its_value(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        vault_put(app, "deploy.api_token", _SECRET, cwd=project)

        report = vault_inspect(app, "deploy.api_token", cwd=project)

        assert report.exists is True
        assert report.eligible is True
        assert report.origin is VaultOrigin.DIRECT
        assert report.readability is Readability.READABLE
        assert _SECRET not in str(report)

    def test_an_absent_entry_is_reported_not_raised(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        report = vault_inspect(app, "deploy.api_token", cwd=project)

        assert report.exists is False
        assert report.eligible is True
        assert report.readability is Readability.ABSENT

    def test_an_ineligible_path_is_explained_not_raised(
        self, app: FunctualizeApp, project: Path
    ) -> None:
        """ "Why can I not store this here?" is the question it exists for."""
        report = vault_inspect(app, "deploy.region", cwd=project)

        assert report.eligible is False

    def test_a_missing_key_is_reported_as_such(
        self, app: FunctualizeApp, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._config.vault_keys import ENV_VAR

        vault_put(app, "deploy.api_token", _SECRET, cwd=project)
        monkeypatch.delenv(ENV_VAR)
        monkeypatch.setattr(
            "functualize._config.vault_keys.KeychainKeyProvider.is_available",
            lambda self: False,
        )

        report = vault_inspect(app, "deploy.api_token", cwd=project)

        assert report.readability is Readability.KEY_UNAVAILABLE
        assert report.exists is True
        assert report.origin is VaultOrigin.DIRECT

    def test_a_wrong_key_is_reported_without_decrypting_a_secret(
        self, app: FunctualizeApp, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._config.vault_keys import ENV_VAR, generate_key

        vault_put(app, "deploy.api_token", _SECRET, cwd=project)
        monkeypatch.setenv(ENV_VAR, generate_key())

        report = vault_inspect(app, "deploy.api_token", cwd=project)

        assert report.readability is Readability.WRONG_KEY


class _FakeKeyring:
    """A keyring-shaped provider: never needs a terminal."""

    def __init__(
        self,
        *,
        key: bytes | None = None,
        locked: bool = False,
        available: bool = True,
        delay: float = 0.0,
    ) -> None:
        self._key = key
        self._locked = locked
        self._available = available
        self._delay = delay
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


@pytest.fixture
def keyring_only(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[_FakeKeyring], _FakeKeyring]:
    """No env key; the given fake is the only provider the resolver sees."""
    from functualize._config.vault_keys import ENV_VAR

    def install(fake: _FakeKeyring) -> _FakeKeyring:
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr(
            "functualize._config.vault_key_resolver.default_providers",
            lambda: (fake,),
        )
        return fake

    return install


class TestPutTellsWhyThereIsNoKey:
    """B3 through the public seam: three reasons, none destructive."""

    def test_a_locked_keyring_is_key_locked(
        self, app: FunctualizeApp, project: Path, keyring_only: Any
    ) -> None:
        keyring_only(_FakeKeyring(locked=True))
        with pytest.raises(VaultKeySourceError) as exc:
            vault_put(app, "deploy.api_token", _SECRET, cwd=project)
        assert exc.value.reason == "key_locked"
        message = str(exc.value)
        assert "func builtin vault unlock" in message
        assert "vault remove" not in message
        assert "vault clear" not in message

    def test_no_keyring_is_no_keyring(
        self, app: FunctualizeApp, project: Path, keyring_only: Any
    ) -> None:
        keyring_only(_FakeKeyring(available=False))
        with pytest.raises(VaultKeySourceError) as exc:
            vault_put(app, "deploy.api_token", _SECRET, cwd=project)
        assert exc.value.reason == "no_keyring"
        assert "functualize[keychain]" in str(exc.value)

    def test_nothing_stored_is_key_not_stored(
        self, app: FunctualizeApp, project: Path, keyring_only: Any
    ) -> None:
        keyring_only(_FakeKeyring(key=None))
        with pytest.raises(VaultKeySourceError) as exc:
            vault_put(app, "deploy.api_token", _SECRET, cwd=project)
        assert exc.value.reason == "key_not_stored"
        assert "func builtin vault init" in str(exc.value)

    def test_put_is_bounded_by_the_keyring_timeout(
        self,
        app: FunctualizeApp,
        project: Path,
        keyring_only: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`put` runs from scripts too: a keyring that never answers costs the
        configured wait, then a refusal — not a hang."""
        monkeypatch.setenv("FUNCTUALIZE_VAULT_KEYRING_TIMEOUT", "1s")
        keyring_only(_FakeKeyring(key=b"\x01" * 32, delay=5.0))
        started = time.monotonic()
        with pytest.raises(VaultKeySourceError) as exc:
            vault_put(app, "deploy.api_token", _SECRET, cwd=project)
        assert time.monotonic() - started < 3.0
        assert exc.value.reason == "key_locked"
        assert "did not answer within 1s" in str(exc.value)

    def test_the_legacy_reason_spelling_means_no_keyring(self) -> None:
        assert VaultKeySourceError("key_unavailable", "x").reason == "no_keyring"


class TestUnlock:
    def test_it_names_the_provider_and_never_returns_the_key(
        self, project: Path, keyring_only: Any
    ) -> None:
        key = b"\x5a" * 32
        keyring_only(_FakeKeyring(key=key))
        lookup = vault_unlock(cwd=project)
        assert lookup.provider_id == "keychain"
        assert lookup.key is None
        assert key.hex() not in repr(lookup)

    def test_it_applies_no_deadline(
        self, project: Path, keyring_only: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A person is answering a dialog; the configured wait does not apply."""
        monkeypatch.setenv("FUNCTUALIZE_VAULT_KEYRING_TIMEOUT", "1s")
        keyring_only(_FakeKeyring(key=b"\x5a" * 32, delay=1.5))
        assert vault_unlock(cwd=project).provider_id == "keychain"

    @pytest.mark.parametrize(
        ("fake", "reason"),
        [
            (_FakeKeyring(locked=True), "key_locked"),
            (_FakeKeyring(available=False), "no_keyring"),
            (_FakeKeyring(key=None), "key_not_stored"),
        ],
    )
    def test_a_failure_raises_with_its_reason(
        self, project: Path, keyring_only: Any, fake: _FakeKeyring, reason: str
    ) -> None:
        keyring_only(fake)
        with pytest.raises(VaultKeySourceError) as exc:
            vault_unlock(cwd=project)
        assert exc.value.reason == reason


class _UnlockableKeyring(_FakeKeyring):
    """A keyring that can be asked to unlock, and counts whether it was."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.unlock_calls = 0

    def unlock(self) -> bool:
        self.unlock_calls += 1
        return True


class TestInspectNeverPrompts:
    """B5 — a locked keyring is reported, never asked to unlock."""

    def test_a_locked_keyring_is_never_unlocked(
        self, app: FunctualizeApp, project: Path, keyring_only: Any
    ) -> None:
        vault_put(app, "deploy.api_token", _SECRET, cwd=project)
        fake = keyring_only(_UnlockableKeyring(locked=True))
        report = vault_inspect(app, "deploy.api_token", cwd=project)
        assert report.readability is Readability.KEY_UNAVAILABLE
        assert fake.unlock_calls == 0

    def test_an_unlocked_keyring_is_read_silently(
        self, app: FunctualizeApp, project: Path, keyring_only: Any
    ) -> None:
        """`get_key` never prompts (the provider contract), so inspect may
        read: here the key is a different one, and inspect says so."""
        vault_put(app, "deploy.api_token", _SECRET, cwd=project)
        fake = keyring_only(_UnlockableKeyring(key=b"\x5a" * 32))
        report = vault_inspect(app, "deploy.api_token", cwd=project)
        assert report.readability is Readability.WRONG_KEY
        assert fake.unlock_calls == 0


def _scripted_keychain(unlocked: Any) -> Any:
    """The shipped keychain provider over an adapter whose unlock answers `unlocked`."""
    from functualize._config.vault_keyring import AdapterOutcome, AdapterRead
    from functualize._config.vault_keys import KeychainKeyProvider

    class _Adapter:
        name = "linux"

        def read_silent(self) -> AdapterRead:
            return AdapterRead(AdapterOutcome.LOCKED)

        def state(self) -> Any:
            from functualize._types.enums import KeyAvailability

            return KeyAvailability.LOCKED

        def unlock(self) -> AdapterRead:
            return unlocked

    class _Keychain(KeychainKeyProvider):
        def is_available(self) -> bool:
            return True

    return _Keychain(adapter=_Adapter())  # type: ignore[arg-type]


class TestUnlockOutcomes:
    """B4' — how the dialog ended is reported, never the key."""

    def test_unlocked_now_says_so(self, project: Path, keyring_only: Any) -> None:
        from functualize._config.vault_keyring import (
            AdapterOutcome,
            AdapterRead,
            UnlockHow,
        )

        key_hex = "5a" * 32
        keyring_only(
            _scripted_keychain(
                AdapterRead(
                    AdapterOutcome.FOUND, secret=key_hex, how=UnlockHow.UNLOCKED_NOW
                )
            )
        )
        lookup = vault_unlock(cwd=project)
        assert lookup.unlock_how is UnlockHow.UNLOCKED_NOW
        assert lookup.key is None
        assert key_hex not in repr(lookup)

    @pytest.mark.parametrize(
        ("how", "reason"),
        [("cancelled", "cancelled"), ("no_prompt", "no_prompt")],
    )
    def test_a_dialog_that_ended_without_a_key_names_why(
        self, project: Path, keyring_only: Any, how: str, reason: str
    ) -> None:
        from functualize._config.vault_keyring import (
            AdapterOutcome,
            AdapterRead,
            UnlockHow,
        )

        keyring_only(
            _scripted_keychain(AdapterRead(AdapterOutcome.LOCKED, how=UnlockHow(how)))
        )
        with pytest.raises(VaultKeySourceError) as exc:
            vault_unlock(cwd=project)
        assert exc.value.reason == reason
        assert "keychain" not in str(exc.value).lower()


class _InterruptingKeyring(_FakeKeyring):
    """Answers slowly, sending this process `interrupts` SIGINTs while it waits.

    The signals come from inside the read, so they always arrive while
    `vault_unlock`'s handlers are installed — never into the test runner.
    """

    def __init__(self, *, interrupts: int, answer_after: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._interrupts = interrupts
        self._answer_after = answer_after

    def get_key(self, project_id: str) -> bytes | None:
        import os
        import signal

        for _ in range(self._interrupts):
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(0.3)
        time.sleep(self._answer_after)
        return super().get_key(project_id)


class TestUnlockSignalPolicy:
    """B4' — the first interrupt warns and keeps waiting; a second stops."""

    def test_the_first_interrupt_only_warns(
        self,
        project: Path,
        keyring_only: Any,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import signal

        before = signal.getsignal(signal.SIGINT)
        keyring_only(
            _InterruptingKeyring(interrupts=1, answer_after=0.3, key=b"\x5a" * 32)
        )
        with caplog.at_level("WARNING"):
            lookup = vault_unlock(cwd=project)
        assert lookup.provider_id == "keychain"
        assert any(
            "answer or cancel it there" in r.getMessage() for r in caplog.records
        )
        assert signal.getsignal(signal.SIGINT) is before

    def test_a_second_interrupt_stops_waiting(
        self, project: Path, keyring_only: Any
    ) -> None:
        import signal

        before = signal.getsignal(signal.SIGINT)
        keyring_only(
            _InterruptingKeyring(interrupts=2, answer_after=10.0, key=b"\x5a" * 32)
        )
        started = time.monotonic()
        with pytest.raises(UnlockAbandonedError) as exc:
            vault_unlock(cwd=project)
        assert time.monotonic() - started < 5.0
        assert exc.value.reason == "unlock_abandoned"
        assert signal.getsignal(signal.SIGINT) is before
