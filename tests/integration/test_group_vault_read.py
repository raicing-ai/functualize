"""E2E: a real job reads a group's secret through the public ``Vault`` capability.

Everything here goes through a public entry point -- ``FunctualizeApp.execute``
on the standard and static boot paths, and the ``func`` / app CLI surfaces --
with the job importing ``Vault`` from ``functualize.job``. Nothing calls the
adapter directly; `tests/app/test_vault_reader.py` does that.

Each test names the acceptance criterion of the F6 spec it exercises:

- AC-1 public call, ``Secret[str]``, passed on as an explicit value
- AC-2 candidate order
- AC-3 job-scope and other-environment exclusion
- AC-4 missing entry / missing vault file, nothing substituted
- AC-5 a stored unreadable entry stops the read, direct and provider origins
- AC-6 no provider contact during the run
- AC-7 no plaintext in stdout, stderr, logs, errors or vault diagnostics
- AC-8 existing identities and ordinary config resolution unchanged
"""

from __future__ import annotations

import logging
import os
import sqlite3
import types
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize._cli.builtins import register_builtin_commands
from functualize.app import FunctualizeApp, JobSources
from functualize.app.config import ConfigSources, PluginSources
from functualize.app.core import request_for
from functualize.app.vault import (
    VaultDecryptionError,
    VaultEntryMissingError,
    VaultEntryUnreadableError,
    VaultIdentity,
    VaultOrigin,
)

# Runtime, not TYPE_CHECKING: the static-path jobs below are local functions
# whose `vault: Vault` annotation the engine resolves from this module's globals.
from functualize.job import Vault  # noqa: TC001
from functualize.types import JobResult, RunStatus, Secret

#: Long and unique: every absence assertion is only as good as the
#: improbability of a coincidental match.
_MARKER = "F6-E2E-PLAINTEXT-9d27c4e1-must-never-appear"  # gitleaks:allow
_GROUP = "cloudflare_dev.d1.main"
_FIELD = "api_token"

_JOBS = f'''
from pydantic import BaseModel, Field

from functualize.app.vault import VaultEntryMissingError
from functualize.job import Log, Vault
from functualize.job.decorators import job
from functualize.types import Secret

GROUP = {_GROUP!r}
FIELD = {_FIELD!r}


def _trusted_work(token: Secret) -> str:
    """Where the job hands the value on: the only place it is unwrapped."""
    return f"used {{len(token.get_secret_value())}} chars"


@job
def which(vault: Vault) -> str:
    """Which entry won -- tests provision distinguishable non-secret values."""
    token = vault.read(GROUP, FIELD)
    return f"{{type(token).__name__}}:{{token.get_secret_value()}}"


@job
def deploy_target(vault: Vault, log: Log) -> str:
    """Renders the token every careless way a job might, then uses it."""
    token = vault.read(GROUP, FIELD)
    log(f"read token {{token}} / {{token!r}}")
    print(f"token={{token}} repr={{token!r}}")
    return _trusted_work(token)


class TargetConfig(BaseModel):
    api_token: Secret[str] = Field(default="config-default", validate_default=True)


@job
def config_fallthrough(config: TargetConfig, vault: Vault) -> str:
    """Ordinary config falls through on a miss; the explicit read does not."""
    try:
        vault.read(GROUP, FIELD)
    except VaultEntryMissingError:
        return f"missing;config={{config.api_token.get_secret_value()}}"
    return "read"
'''


@pytest.fixture
def project(
    tmp_path: Path, xdg_dirs: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> Any:
    from functualize._config.vault_keys import ENV_VAR, generate_key

    root = tmp_path / "project"
    # The convention directory, so `func` discovers the jobs from the cwd too.
    (root / ".functualize" / "jobs").mkdir(parents=True)
    (root / ".functualize" / "jobs" / "targets.py").write_text(_JOBS)
    monkeypatch.setenv(ENV_VAR, generate_key())
    monkeypatch.setenv("FUNCTUALIZE_ENV", "prod")
    monkeypatch.chdir(root)
    AppState.reset()
    yield root
    AppState.reset()


def _key() -> bytes:
    from functualize._config.vault_keys import ENV_VAR

    return bytes.fromhex(os.environ[ENV_VAR])


def _vault_path() -> Path:
    from functualize._config.vault_paths import vault_path_for_project

    return vault_path_for_project()


def _init() -> None:
    """`func builtin vault init`, as an operator runs it."""
    group = click.Group(name="func")
    register_builtin_commands(group)
    result = CliRunner().invoke(
        group, ["builtin", "vault", "init", "--key-source", "env"], obj={}
    )
    assert result.exit_code == 0, result.output


def _put(
    target: str,
    value: str,
    *,
    environment: str | None = "prod",
    scope: str = "group",
    origin: VaultOrigin = VaultOrigin.DIRECT,
) -> None:
    """Store one entry under the existing storage identity, as `put`/`sync` do."""
    from functualize._config.vault import SecretsVault

    if not _vault_path().exists():
        _init()
    provider = None if origin is VaultOrigin.DIRECT else "fake-sm"
    SecretsVault(_vault_path()).put(
        VaultIdentity(scope, target, _FIELD, environment).encode(),  # type: ignore[arg-type]
        value,
        encryption_key=_key(),
        origin=origin,
        provider=provider,
        annotation=None if provider is None else "fake-sm://prod/cf-token",
    )


def _standard(root: Path) -> FunctualizeApp:
    return FunctualizeApp(
        "f6",
        job_sources=JobSources(
            directories=[str(root / ".functualize" / "jobs")], lazy=False
        ),
    )


def _value(result: JobResult) -> Any:
    assert result.status is RunStatus.SUCCESS, result.exception
    return result.return_value


def _failure(result: JobResult) -> BaseException:
    assert result.status is not RunStatus.SUCCESS, result.return_value
    assert isinstance(result.exception, BaseException)
    return result.exception


class TestTheJobPath:
    def test_a_real_job_receives_a_secret_from_the_group_entry(
        self, project: Path
    ) -> None:
        """AC-1: public import, injection by type, `Secret[str]` back."""
        _put(_GROUP, "active-exact")

        assert _value(_standard(project).execute(request_for("which"))) == (
            "Secret:active-exact"
        )

    def test_the_token_is_passed_on_as_an_explicit_value(self, project: Path) -> None:
        """AC-1: the job hands the wrapper to its own work."""
        _put(_GROUP, _MARKER)

        assert _value(_standard(project).execute(request_for("deploy_target"))) == (
            f"used {len(_MARKER)} chars"
        )

    def test_the_static_boot_path_reads_the_project_vault(self, project: Path) -> None:
        """AC-1 on the second entry path: explicit wiring, a chain of its own
        with no vault source, and the same project vault read anyway."""
        from functualize._config.chain import ResolutionChain

        _put("cloudflare_dev", "active-ancestor")

        def static_which(vault: Vault) -> str:
            token = vault.read(_GROUP, _FIELD)
            return f"{type(token).__name__}:{token.get_secret_value()}"

        app = FunctualizeApp(
            "f6-static",
            job_sources=JobSources(functions=[static_which]),
            config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )

        assert _value(app.execute(request_for("static_which"))) == (
            "Secret:active-ancestor"
        )

    def test_vault_is_not_an_invocation_input(self, project: Path) -> None:
        """The capability never surfaces as a CLI/MCP argument."""
        from functualize.app.utils import job_input_schema

        descriptor = next(d for d in _standard(project).get_jobs() if d.name == "which")
        schema = job_input_schema(descriptor)

        assert "vault" not in schema.get("properties", {})
        assert "vault" not in [p.name for p in descriptor.parameters]


class TestCandidateOrder:
    """AC-2."""

    def test_active_exact_beats_everything(self, project: Path) -> None:
        _put(_GROUP, "active-exact")
        _put("cloudflare_dev", "active-ancestor")
        _put(_GROUP, "shared-exact", environment=None)

        assert _value(_standard(project).execute(request_for("which"))) == (
            "Secret:active-exact"
        )

    def test_an_active_ancestor_beats_a_shared_exact_entry(self, project: Path) -> None:
        _put("cloudflare_dev", "active-ancestor")
        _put(_GROUP, "shared-exact", environment=None)

        assert _value(_standard(project).execute(request_for("which"))) == (
            "Secret:active-ancestor"
        )

    def test_the_nearest_ancestor_wins_within_a_tier(self, project: Path) -> None:
        _put("cloudflare_dev", "far", environment=None)
        _put("cloudflare_dev.d1", "near", environment=None)

        assert _value(_standard(project).execute(request_for("which"))) == (
            "Secret:near"
        )

    def test_a_provider_origin_entry_is_read_the_same_way(self, project: Path) -> None:
        _put(_GROUP, "synced", origin=VaultOrigin.PROVIDER)

        assert _value(_standard(project).execute(request_for("which"))) == (
            "Secret:synced"
        )


class TestNotCandidates:
    """AC-3."""

    def test_a_job_scope_entry_is_never_read(self, project: Path) -> None:
        _put(_GROUP, "job-entry", scope="job")
        _put(_GROUP, "job-entry-shared", scope="job", environment=None)

        error = _failure(_standard(project).execute(request_for("which")))

        assert isinstance(error, VaultEntryMissingError)

    def test_another_named_environment_is_never_read(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _put(_GROUP, "staging-entry", environment="staging")

        error = _failure(_standard(project).execute(request_for("which")))
        assert isinstance(error, VaultEntryMissingError)

        # The same store read under the environment that owns the entry.
        monkeypatch.setenv("FUNCTUALIZE_ENV", "staging")
        assert _value(_standard(project).execute(request_for("which"))) == (
            "Secret:staging-entry"
        )


class TestAbsence:
    """AC-4."""

    def test_no_candidate_raises_the_missing_error(self, project: Path) -> None:
        _put("unrelated.group", "x")

        error = _failure(_standard(project).execute(request_for("which")))

        assert isinstance(error, VaultEntryMissingError)
        assert (error.group, error.field) == (_GROUP, _FIELD)

    def test_a_missing_vault_file_is_the_same_absence(self, project: Path) -> None:
        assert not _vault_path().exists()

        error = _failure(_standard(project).execute(request_for("which")))

        assert isinstance(error, VaultEntryMissingError)
        assert not _vault_path().exists(), "a read must not create the store"

    def test_no_environment_value_is_substituted(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An env var spelled every way config would accept is ignored."""
        for name in (
            "API_TOKEN",
            "CLOUDFLARE_DEV_D1_MAIN_API_TOKEN",
            "FUNCTUALIZE_CLOUDFLARE_DEV_D1_MAIN_API_TOKEN",
        ):
            monkeypatch.setenv(name, "from-environment")

        error = _failure(_standard(project).execute(request_for("which")))

        assert isinstance(error, VaultEntryMissingError)

    def test_ordinary_config_still_falls_through_on_a_miss(self, project: Path) -> None:
        """AC-8 / C2: the config chain keeps its miss behaviour; only the
        explicit read reports absence."""
        _put("unrelated.group", "x")

        assert _value(
            _standard(project).execute(request_for("config_fallthrough"))
        ) == ("missing;config=config-default")


class TestUnreadableStops:
    """AC-5."""

    @pytest.mark.parametrize("origin", [VaultOrigin.DIRECT, VaultOrigin.PROVIDER])
    def test_a_wrong_key_for_the_active_entry_refuses_before_the_shared_one(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, origin: VaultOrigin
    ) -> None:
        from functualize._config.vault_keys import ENV_VAR

        _put(_GROUP, _MARKER, origin=origin)
        _put(_GROUP, "readable-shared", environment=None)
        monkeypatch.setenv(ENV_VAR, "09" * 32)

        error = _failure(_standard(project).execute(request_for("which")))

        assert isinstance(error, VaultEntryUnreadableError)
        assert _MARKER not in str(error)

    def test_a_stored_ancestor_stops_later_candidates(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._config.vault_keys import ENV_VAR

        _put("cloudflare_dev", "stored-ancestor")
        _put(_GROUP, "readable-shared", environment=None)
        monkeypatch.setenv(ENV_VAR, "09" * 32)

        error = _failure(_standard(project).execute(request_for("which")))

        assert isinstance(error, VaultEntryUnreadableError)

    def test_an_entry_that_will_not_authenticate_is_a_decryption_error(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._config.vault_keys import ENV_VAR

        _put(_GROUP, _MARKER)
        _put(_GROUP, "readable-shared", environment=None)
        with sqlite3.connect(_vault_path()) as conn:
            conn.execute("DELETE FROM vault_meta")
        monkeypatch.setenv(ENV_VAR, "09" * 32)

        error = _failure(_standard(project).execute(request_for("which")))

        assert isinstance(error, VaultDecryptionError)
        assert _MARKER not in str(error)


class TestOffline:
    def test_the_read_opens_no_socket(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6. Sockets refused outright, so a library that opened its own
        connection fails the run rather than slipping past a mock."""
        _put(_GROUP, "synced", origin=VaultOrigin.PROVIDER)
        app = _standard(project)

        import socket

        def _refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("the run opened a socket")

        monkeypatch.setattr(socket, "socket", _refuse)
        monkeypatch.setattr(socket, "create_connection", _refuse)

        assert _value(app.execute(request_for("which"))) == "Secret:synced"


class TestNoPlaintextAnywhere:
    """AC-7, read off captured streams and log records, not off report types."""

    @staticmethod
    def _assert_clean(*texts: str) -> None:
        for text in texts:
            assert _MARKER not in text

    def test_a_successful_read_renders_only_the_mask(
        self, project: Path, cli_run: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        _put(_GROUP, _MARKER)

        with caplog.at_level(logging.DEBUG):
            result = cli_run(["deploy_target"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert "token=•••" in result.stdout
        self._assert_clean(result.stdout, result.stderr, caplog.text)

    def test_a_missing_read_reports_without_a_value(
        self, project: Path, cli_run: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        _put(_GROUP, _MARKER, environment="staging")

        with caplog.at_level(logging.DEBUG):
            result = cli_run(["deploy_target"], cwd=project)

        assert result.exit_code != 0
        assert "VaultEntryMissingError" in result.stdout + result.stderr
        self._assert_clean(result.stdout, result.stderr, caplog.text)

    def test_an_unreadable_read_reports_without_a_value(
        self,
        project: Path,
        cli_run: Any,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from functualize._config.vault_keys import ENV_VAR

        _put(_GROUP, _MARKER)
        monkeypatch.setenv(ENV_VAR, "09" * 32)

        with caplog.at_level(logging.DEBUG):
            result = cli_run(["deploy_target"], cwd=project)

        assert result.exit_code != 0
        self._assert_clean(result.stdout, result.stderr, caplog.text)

    def test_vault_list_and_inspect_stay_metadata_only(self, project: Path) -> None:
        _put(_GROUP, _MARKER)
        _put(_GROUP, _MARKER, environment=None, origin=VaultOrigin.PROVIDER)
        group = click.Group(name="func")
        register_builtin_commands(group)
        runner = CliRunner()
        app = _standard(project)

        listed = runner.invoke(group, ["builtin", "vault", "list"], obj={"app": app})
        inspected = runner.invoke(
            group,
            ["builtin", "vault", "inspect", "--group", _GROUP, "--field", _FIELD],
            obj={"app": app},
        )

        assert listed.exit_code == 0, listed.output
        assert _GROUP in listed.output
        self._assert_clean(listed.output, inspected.output)

    def test_the_returned_wrapper_never_renders_the_value(self, project: Path) -> None:
        _put(_GROUP, _MARKER)
        seen: list[Secret] = []

        def capture(vault: Vault) -> None:
            seen.append(vault.read(_GROUP, _FIELD))

        from functualize._config.chain import ResolutionChain

        app = FunctualizeApp(
            "f6-capture",
            job_sources=JobSources(functions=[capture]),
            config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        _value(app.execute(request_for("capture")))

        (token,) = seen
        self._assert_clean(str(token), repr(token), f"{token}", f"{token!r}")
        assert token.get_secret_value() == _MARKER
