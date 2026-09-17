"""The four public vault operations, exercised the way a user's code would.

These call `functualize.app.vault` directly rather than through `func`, which
is the point: the CLI is one caller of this seam, not where the behavior lives.
An app embedding functualize gets the same lifecycle with no CLI present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._config.vault import (
    VaultEntryExistsError,
    VaultOrigin,
    VaultOriginConflictError,
)
from functualize.app import FunctualizeApp, JobSources
from functualize.app.vault import (
    Readability,
    VaultKeySourceError,
    VaultPathError,
    vault_init,
    vault_inspect,
    vault_put,
    vault_remove,
)

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
        from functualize._config.vault_keys import resolve_vault_key
        from functualize._config.vault_paths import vault_path_for_project

        resolution = resolve_vault_key("ignored")
        assert resolution is not None
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
        from functualize._config.vault_keys import resolve_vault_key
        from functualize._config.vault_paths import vault_path_for_project

        resolution = resolve_vault_key("ignored")
        assert resolution is not None
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
