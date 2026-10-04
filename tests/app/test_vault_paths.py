"""Scope-aware vault identities are checked against live declarations."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from functualize.app import FunctualizeApp, JobSources
from functualize.app.vault import (
    Readability,
    VaultIdentity,
    VaultInitReport,
    VaultInspectionReport,
    VaultMutationReport,
    VaultPathError,
    resolve_vault_identity,
)
from functualize.job import GroupOptions
from functualize.types import Secret  # noqa: TC001 - pydantic resolves it at run time

_JOB_SOURCE = """
from pydantic import BaseModel, Field
from functualize.job import GroupOptions, RunContext
from functualize.job.decorators import job
from functualize.types import Secret

class DeployOptions(GroupOptions, group="deploy"):
    token: Secret[str]
    region: str = "eu"

class DeployConfig(BaseModel):
    token: Secret[str]
    api_token: Secret[str]
    region: str = "eu"
    legacy_key: str = Field(default="", json_schema_extra={"secret": True})

@job
def deploy(config: DeployConfig, options: DeployOptions, rc: RunContext) -> str:
    return "deployed"

@job
def bare(token: Secret[str], rc: RunContext) -> str:
    return "done"
"""


@pytest.fixture
def app(tmp_path: Path) -> FunctualizeApp:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "deploy.py").write_text(_JOB_SOURCE)
    return FunctualizeApp(
        "vaultlab", job_sources=JobSources(directories=[str(jobs)], lazy=False)
    )


def test_same_target_and_field_are_distinct_by_scope(app: FunctualizeApp) -> None:
    group = resolve_vault_identity(app, group="deploy", field="token")
    job = resolve_vault_identity(app, job="deploy", field="token")
    assert group == VaultIdentity("group", "deploy", "token")
    assert job == VaultIdentity("job", "deploy", "token")
    assert group.encode() != job.encode()


def test_nested_job_path_is_target_not_field(app: FunctualizeApp) -> None:
    app.register_dynamic_job("deploy.service", lambda: None, config_class=None)
    with pytest.raises(VaultPathError) as exc:
        resolve_vault_identity(app, job="deploy.service", field="token")
    assert exc.value.reason == "unknown_field"


def test_canonical_spelling_and_secret_marker(app: FunctualizeApp) -> None:
    assert resolve_vault_identity(
        app, job="deploy", field="api-token"
    ) == VaultIdentity("job", "deploy", "api_token")
    assert resolve_vault_identity(
        app, job="deploy", field="legacy-key"
    ) == VaultIdentity("job", "deploy", "legacy_key")


@pytest.mark.parametrize(
    ("scope", "target", "field", "reason"),
    [
        ("job", "missing", "token", "unknown_job"),
        ("job", "deploy", "missing", "unknown_field"),
        ("job", "deploy", "region", "field_not_secret"),
        ("group", "missing", "token", "unknown_group"),
        ("group", "deploy", "missing", "unknown_field"),
        ("group", "deploy", "region", "field_not_secret"),
        ("job", "bare", "token", "field_not_config_model"),
    ],
)
def test_ineligible_target_or_field(
    app: FunctualizeApp, scope: str, target: str, field: str, reason: str
) -> None:
    with pytest.raises(VaultPathError) as exc:
        resolve_vault_identity(app, **{scope: target}, field=field)
    assert exc.value.reason == reason


def test_exactly_one_scope_is_required(app: FunctualizeApp) -> None:
    for kwargs in ({}, {"group": "deploy", "job": "deploy"}):
        with pytest.raises(VaultPathError) as exc:
            resolve_vault_identity(app, field="token", **kwargs)
        assert exc.value.reason == "scope_required"


class _ReleaseOptions(GroupOptions, group="release"):
    api_token: Secret[str]


def _release_service(options: _ReleaseOptions) -> None:
    pass


def test_dynamic_group_declaration_is_visible() -> None:
    app = FunctualizeApp("dynamic", job_sources=JobSources(directories=[], lazy=False))
    app.register_dynamic_job("release.service", _release_service)
    assert resolve_vault_identity(app, group="release", field="api-token") == (
        VaultIdentity("group", "release", "api_token")
    )


@pytest.mark.parametrize(
    "report", [VaultInitReport, VaultMutationReport, VaultInspectionReport]
)
def test_reports_have_no_plaintext_field(report: type) -> None:
    forbidden = {"value", "secret", "plaintext", "ciphertext", "nonce", "key"}
    assert not ({f.name for f in fields(report)} & forbidden)


def test_readability_never_claims_secret_decryption() -> None:
    assert "decryption_failed" not in {r.value for r in Readability}


def test_resolution_precedes_secret_input() -> None:
    import inspect

    assert list(inspect.signature(resolve_vault_identity).parameters) == [
        "app",
        "group",
        "job",
        "field",
    ]
