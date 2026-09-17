"""E2E: the journey starts where the user starts.

`init` → `put` → run an ordinary job, through the public surfaces, with the
value arriving as a `Secret[str]`. Component tests can all pass against a
feature that is wired to nothing; this is the test that cannot.

Covers AC-1 (the happy path), AC-2 (the same value through `FunctualizeApp`,
not only `func`), AC-3 (cold discovery and a warm cache agree), AC-4
(precedence), AC-5 (a project with no store is unchanged) and AC-11 (the run
makes no provider call).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize._cli.builtins import register_builtin_commands
from functualize.app import FunctualizeApp, JobSources
from functualize.app.core import request_for
from functualize.app.utils import ExitCode

#: Distinctive on purpose: every assertion about absence below is only as good
#: as the improbability of a coincidental match.
_SECRET = "E2E-PLAINTEXT-4f1c9a-never-printed"  # gitleaks:allow

_JOB = '''
from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job
from functualize.types import Secret


class DeployConfig(BaseModel):
    region: str = Field(default="eu-west-1")
    api_token: Secret[str] = Field(description="Required credential")


@job
def deploy(config: DeployConfig, rc: RunContext) -> str:
    """Report the *type* and a fingerprint, never the value."""
    token = config.api_token
    return f"{type(token).__name__}:{token.get_secret_value()}"
'''


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from functualize._config.vault_keys import ENV_VAR, generate_key

    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    (root / "jobs").mkdir()
    (root / "jobs" / "deploy.py").write_text(_JOB)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv(ENV_VAR, generate_key())
    monkeypatch.chdir(root)
    AppState.reset()
    yield root
    AppState.reset()


def _app(project: Path) -> FunctualizeApp:
    return FunctualizeApp(
        "e2e", job_sources=JobSources(directories=[str(project / "jobs")], lazy=False)
    )


def _cli_run(args: list[str], *, app: Any = None, stdin: str | None = None) -> Any:
    group = click.Group(name="func")
    register_builtin_commands(group)
    return CliRunner().invoke(
        group, ["builtin", "vault", *args], obj={"app": app} if app else {}, input=stdin
    )


def _provision(project: Path, value: str = _SECRET) -> None:
    """The user's two commands, through the real CLI."""
    assert _cli_run(["init", "--key-source", "env"]).exit_code == ExitCode.OK
    result = _cli_run(
        ["put", "deploy.api_token", "--stdin"], app=_app(project), stdin=value
    )
    assert result.exit_code == ExitCode.OK, result.output


class TestTheHappyPath:
    def test_a_provisioned_secret_reaches_an_ordinary_job(self, project: Path) -> None:
        """AC-1. No remote provider, no preset, no custom app."""
        _provision(project)

        result = _app(project).execute(request_for("deploy"))

        assert result.return_value == f"Secret:{_SECRET}"

    def test_the_job_receives_the_declared_wrapper_not_a_raw_string(
        self, project: Path
    ) -> None:
        """AC-1/US-2: the job's contract is unchanged by where the value came
        from. A vault that delivered a bare `str` would break redaction."""
        _provision(project)

        assert (
            _app(project)
            .execute(request_for("deploy"))
            .return_value.startswith("Secret:")
        )

    def test_it_resolves_through_functualize_app_not_only_func(
        self, project: Path
    ) -> None:
        """AC-2. The composition wire is in boot, not in `func`'s dispatch.

        Three capabilities once shipped built, unit-tested and unreachable
        because only one entry point was wired.
        """
        _provision(project)

        app = _app(project)
        assert app.execute(request_for("deploy")).return_value == f"Secret:{_SECRET}"


class TestColdAndWarm:
    def test_the_second_boot_agrees_with_the_first(self, project: Path) -> None:
        """AC-3. Four of the defects in `pitfalls.md` were visible only warm.

        The second app reads the discovery cache the first one wrote, so the
        descriptor it sees is deserialized rather than freshly extracted —
        which is where `secret` and `from_config_model` would be lost if they
        did not travel with the field.
        """
        _provision(project)

        cold = _app(project).execute(request_for("deploy"))
        warm = _app(project).execute(request_for("deploy"))

        assert cold.return_value == warm.return_value == f"Secret:{_SECRET}"


class TestPrecedence:
    def test_the_vault_outranks_the_environment(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-4. This is the preset's whole proposition."""
        _provision(project)
        monkeypatch.setenv("DEPLOY_API_TOKEN", "from-environment")

        assert (
            _app(project).execute(request_for("deploy")).return_value
            == f"Secret:{_SECRET}"
        )

    def test_an_explicit_argument_outranks_the_vault(self, project: Path) -> None:
        """AC-4. What the caller typed for this run wins over everything."""
        _provision(project)

        result = _app(project).execute(
            request_for("deploy", api_token="explicit-value")
        )

        assert result.return_value == "Secret:explicit-value"

    def test_removing_the_entry_restores_the_previous_resolution(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-4's other half: the vault stops mattering when it is emptied."""
        _provision(project)
        monkeypatch.setenv("DEPLOY_API_TOKEN", "from-environment")

        removed = _cli_run(["remove", "deploy.api_token", "--yes"], app=_app(project))
        assert removed.exit_code == ExitCode.OK

        assert (
            _app(project).execute(request_for("deploy")).return_value
            == "Secret:from-environment"
        )


class TestTheDormantDefault:
    def test_a_project_with_no_store_is_unchanged(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-5. Nothing was provisioned, so nothing about this run differs."""
        monkeypatch.setenv("DEPLOY_API_TOKEN", "from-environment")

        assert (
            _app(project).execute(request_for("deploy")).return_value
            == "Secret:from-environment"
        )

    def test_a_store_without_a_matching_path_is_also_unchanged(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-5. A vault that holds *something else* must not interfere."""
        from functualize._config.vault import SecretsVault, VaultOrigin
        from functualize._config.vault_keys import resolve_vault_key
        from functualize._config.vault_paths import vault_path_for_project

        resolution = resolve_vault_key("ignored")
        assert resolution is not None
        SecretsVault(vault_path_for_project(project)).put(
            "other.thing",
            "irrelevant",
            encryption_key=resolution.key,
            origin=VaultOrigin.DIRECT,
        )
        monkeypatch.setenv("DEPLOY_API_TOKEN", "from-environment")

        assert (
            _app(project).execute(request_for("deploy")).return_value
            == "Secret:from-environment"
        )


class TestTheRunIsOffline:
    def test_no_provider_is_contacted(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-11. ADR-016's central promise, now extended to direct entries.

        Sockets are disabled outright rather than mocked: a test that asserts
        "the provider object was not called" proves nothing about a library
        that opened its own connection.
        """
        _provision(project)

        import socket

        def _refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("the run opened a socket")

        monkeypatch.setattr(socket, "socket", _refuse)
        monkeypatch.setattr(socket, "create_connection", _refuse)

        assert (
            _app(project).execute(request_for("deploy")).return_value
            == f"Secret:{_SECRET}"
        )
