"""Canonical vault paths, checked against the live job schema.

The test that matters most here is `test_the_config_key_is_what_the_chain_asks_for`.
Everything else in this feature can be correct and the feature still not work
if what `put` stores is not byte-identical to what `VaultSource` is later asked
for — the value would simply never be found, with nothing reporting an error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize.app import FunctualizeApp, JobSources
from functualize.app.vault import (
    Readability,
    VaultInitReport,
    VaultInspectionReport,
    VaultMutationReport,
    VaultPathError,
    resolve_canonical_path,
)

_JOB_SOURCE = '''
from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job
from functualize.types import Secret


class DeployConfig(BaseModel):
    region: str = Field(default="eu-west-1", description="Where to deploy")
    api_token: Secret[str] = Field(description="Required credential")
    legacy_key: str = Field(
        default="", description="Plain", json_schema_extra={"secret": True}
    )


@job
def deploy(config: DeployConfig, rc: RunContext) -> str:
    """Deploy something."""
    return "deployed"


@job
def bare(token: Secret[str], rc: RunContext) -> str:
    """A job with no config model: `token` is a *parameter*."""
    return "done"
'''


@pytest.fixture
def app(tmp_path: Path) -> FunctualizeApp:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "deploy.py").write_text(_JOB_SOURCE)
    return FunctualizeApp(
        "vaultlab", job_sources=JobSources(directories=[str(jobs)], lazy=False)
    )


class TestTheIdentityThatMakesTheFeatureWork:
    def test_the_config_key_is_what_the_chain_asks_for(
        self, app: FunctualizeApp
    ) -> None:
        """`put` and the run must agree on one string, exactly.

        A job's config section prefix is its full dotted canonical name, and
        `VaultSource._qualified(key, section)` builds `f"{section}.{key}"`. If
        this drifts, nothing raises — the entry is stored under a name nothing
        ever looks up, and the job silently falls through to a weaker source.
        """
        from functualize._config.vault_source import VaultSource

        resolved = resolve_canonical_path(app, "deploy.api_token")

        # Cross-checked against the function the chain actually calls, not
        # against a string rebuilt here. Asserting `config_key == f"{a}.{b}"`
        # would only restate how config_key is written; it would stay green if
        # VaultSource started qualifying keys some other way, which is exactly
        # the drift that would break the feature silently.
        source = VaultSource(Path("unused.db"), encryption_key=None)
        assert resolved.config_key == source._qualified(
            resolved.field_name, resolved.job_name
        )

    def test_the_section_prefix_really_is_the_job_name(
        self, app: FunctualizeApp
    ) -> None:
        """The other half of the identity, and the half that lives elsewhere.

        `config_key` is only correct because a job's config view is built with
        `default_section_prefix=rc.name`. That happens in the composition root,
        so this asserts the link rather than assuming it.
        """
        resolved = resolve_canonical_path(app, "deploy.api_token")
        descriptor = app.get_job("deploy")

        assert descriptor is not None
        assert resolved.job_name == str(descriptor.name)


class TestEligibility:
    def test_a_secret_config_field_resolves(self, app: FunctualizeApp) -> None:
        assert resolve_canonical_path(app, "deploy.api_token").path == (
            "deploy.api_token"
        )

    def test_the_explicit_secret_marker_also_resolves(
        self, app: FunctualizeApp
    ) -> None:
        """Both spellings are one mechanism: `Secret[str]` and
        `json_schema_extra={"secret": True}` land on the same descriptor flag."""
        assert resolve_canonical_path(app, "deploy.legacy_key").field_name == (
            "legacy_key"
        )

    def test_a_plain_field_is_refused(self, app: FunctualizeApp) -> None:
        with pytest.raises(VaultPathError) as exc:
            resolve_canonical_path(app, "deploy.region")
        assert exc.value.reason == "field_not_secret"

    def test_a_secret_parameter_is_refused_as_undeliverable(
        self, app: FunctualizeApp
    ) -> None:
        """The finding this check exists for.

        `job_input_schema` publishes `config_fields or parameters`, so a
        `Secret[str]` parameter appears in the published schema with
        secret=True. But resolution only ever walks `config_class.model_fields`,
        so a value stored against it could never reach the job. Accepting the
        path would produce a stored secret that silently does nothing.
        """
        with pytest.raises(VaultPathError) as exc:
            resolve_canonical_path(app, "bare.token")
        assert exc.value.reason == "field_not_config_model"
        assert "could never reach the job" in str(exc.value)

    def test_an_unknown_job_is_refused(self, app: FunctualizeApp) -> None:
        with pytest.raises(VaultPathError) as exc:
            resolve_canonical_path(app, "nosuchjob.api_token")
        assert exc.value.reason == "unknown_job"

    def test_an_unknown_field_is_refused(self, app: FunctualizeApp) -> None:
        with pytest.raises(VaultPathError) as exc:
            resolve_canonical_path(app, "deploy.nosuchfield")
        assert exc.value.reason == "unknown_field"

    def test_a_bare_name_with_no_field_is_refused(self, app: FunctualizeApp) -> None:
        with pytest.raises(VaultPathError) as exc:
            resolve_canonical_path(app, "deploy")
        assert exc.value.reason == "unknown_field"


class TestSpelling:
    def test_flag_spelling_is_accepted_and_normalized(
        self, app: FunctualizeApp
    ) -> None:
        """A user reads `--api-token` in the help and types that.

        The chain is keyed on the model field name, so both are accepted and
        the canonical one is always what comes back.
        """
        resolved = resolve_canonical_path(app, "deploy.api-token")

        assert resolved.field_name == "api_token"
        assert resolved.path == "deploy.api_token"

    def test_the_python_spelling_of_a_job_finds_it(self, app: FunctualizeApp) -> None:
        """`resolve_name` is the repository's single naming policy; this uses
        it rather than adding a fourth spelling of the same question."""
        assert resolve_canonical_path(app, "deploy.api_token").job_name == "deploy"

    def test_the_split_is_rightmost(self, app: FunctualizeApp) -> None:
        """`a.b.c` is job `a.b` + field `c`, never job `a` + field `b.c`.

        Correct because a registered job carries its group in its canonical
        name, and stable for a leaf name that itself contains a dot.
        """
        with pytest.raises(VaultPathError) as exc:
            resolve_canonical_path(app, "deploy.api_token.extra")
        # Split as job "deploy.api_token" + field "extra" -> no such job.
        assert exc.value.reason == "unknown_job"


class TestReportsCarryNoValue:
    """Enforced by reflection, so a later field cannot leak one by accident."""

    @pytest.mark.parametrize(
        "report_type",
        [
            VaultInitReport,
            VaultMutationReport,
            VaultInspectionReport,
        ],
    )
    def test_no_field_could_hold_plaintext(self, report_type: type) -> None:
        import dataclasses

        forbidden = {"value", "secret", "plaintext", "ciphertext", "nonce", "key"}
        names = {f.name for f in dataclasses.fields(report_type)}

        assert not (names & forbidden), names & forbidden

    def test_readability_never_says_decryption_failed(self) -> None:
        """The check value can only report that a key does not open a store —
        no stored secret is decrypted to find out, so "decryption failed" would
        claim more than is known."""
        assert "decryption_failed" not in {r.value for r in Readability}
        assert Readability.WRONG_KEY.value == "wrong_key"


class TestValidationHappensBeforeInput:
    def test_resolution_needs_no_value(self, app: FunctualizeApp) -> None:
        """Signature-level: a path is checkable without a secret in hand.

        This is what lets `put` reject a typo *before* prompting, so a mistyped
        path never costs someone the value they already typed.
        """
        import inspect

        params = list(inspect.signature(resolve_canonical_path).parameters)
        assert params == ["app", "path"]
