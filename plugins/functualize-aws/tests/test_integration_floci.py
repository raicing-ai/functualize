"""Against a real AWS API surface, not a fake (spec.md A9).

The fakes in `test_providers.py` prove the plugin's own logic. They cannot
prove that `get_secret_value` is the right call, that `WithDecryption` actually
decrypts, or that a `SecureString` differs from a `String` in the way this
plugin assumes — every one of those is an assertion about AWS, and a fake
restates the assumption instead of testing it.

The endpoint comes from `AWS_ENDPOINT_URL`, which botocore honours itself, so
any LocalStack-compatible emulator works and the plugin needs no knowledge of
one. Floci (`floci/floci:latest`, port 4566) is what this was developed
against:

    docker run -d --name floci -p 4566:4566 floci/floci:latest
    AWS_ENDPOINT_URL=http://localhost:4566 uv run pytest plugins/functualize-aws

Without a reachable endpoint the module skips. It does *not* fall back to a
fake: a green run that silently tested nothing is worse than a skip that says
so.
"""

from __future__ import annotations

import os
import socket
import uuid
from typing import Any
from urllib.parse import urlparse

import pytest
from functualize_aws import (
    ParameterStoreProvider,
    SecretNotFoundError,
    SecretsManagerProvider,
)

pytestmark = pytest.mark.integration

_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "")


def _reachable(endpoint: str) -> bool:
    if not endpoint:
        return False
    parsed = urlparse(endpoint)
    if parsed.hostname is None:
        return False
    try:
        with socket.create_connection(
            (parsed.hostname, parsed.port or 443), timeout=1.5
        ):
            return True
    except OSError:
        return False


pytest.importorskip("boto3")

if not _reachable(_ENDPOINT):
    pytest.skip(
        "No AWS emulator reachable. Set AWS_ENDPOINT_URL (e.g. "
        "http://localhost:4566) and run `docker run -d --name floci -p 4566:4566 "
        "floci/floci:latest`.",
        allow_module_level=True,
    )


@pytest.fixture(scope="module", autouse=True)
def emulator_credentials() -> Any:
    """The emulator accepts anything; boto3 still insists on something.

    Module-scoped and set via `os.environ` rather than `monkeypatch`, because
    the seeding fixture below builds its clients at module scope too.
    """
    saved = {
        k: os.environ.get(k)
        for k in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_DEFAULT_REGION",
            "AWS_EC2_METADATA_DISABLED",
        )
    }
    os.environ.update(
        AWS_ACCESS_KEY_ID="test",
        AWS_SECRET_ACCESS_KEY="test",  # gitleaks:allow
        AWS_DEFAULT_REGION="us-east-1",
        AWS_EC2_METADATA_DISABLED="true",
    )
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="module")
def seeded(emulator_credentials: Any) -> Any:
    """Seed this run's own fixtures, then remove them.

    Names are suffixed with a uuid so a re-run against a long-lived container
    cannot pass on the *previous* run's leftovers — the emulator restarts
    empty, but nothing here should depend on that.
    """
    import boto3

    tag = uuid.uuid4().hex[:8]
    names = {
        "secret": f"functualize-test/{tag}/db-password",
        "plain": f"/functualize-test/{tag}/api-url",
        "secure": f"/functualize-test/{tag}/api-token",
    }
    values = {
        "secret": "s3cret-from-secrets-manager",  # gitleaks:allow
        "plain": "https://api.internal",
        "secure": "tok-abc123",  # gitleaks:allow
    }

    sm = boto3.client("secretsmanager")
    ssm = boto3.client("ssm")
    sm.create_secret(Name=names["secret"], SecretString=values["secret"])
    ssm.put_parameter(Name=names["plain"], Value=values["plain"], Type="String")
    ssm.put_parameter(Name=names["secure"], Value=values["secure"], Type="SecureString")

    yield names, values

    sm.delete_secret(SecretId=names["secret"], ForceDeleteWithoutRecovery=True)
    ssm.delete_parameter(Name=names["plain"])
    ssm.delete_parameter(Name=names["secure"])


class TestAgainstTheRealApi:
    def test_a_secrets_manager_secret_resolves(self, seeded: Any) -> None:
        names, values = seeded
        assert SecretsManagerProvider().fetch(names["secret"]) == values["secret"]

    def test_an_ssm_string_resolves(self, seeded: Any) -> None:
        names, values = seeded
        assert ParameterStoreProvider().fetch(names["plain"]) == values["plain"]

    def test_an_ssm_securestring_is_readable(self, seeded: Any) -> None:
        """A `SecureString` reaches the job as its plaintext.

        **Floci does not actually encrypt.** Measured: `WithDecryption=False`
        returns the identical string, so against this emulator the assertion
        below cannot distinguish a decrypted read from an undecrypted one. It
        proves the parameter type is readable at all; the flag itself is
        pinned by `test_decryption_is_always_requested`, which asserts the
        call, not the result.

        Stated rather than glossed, because a green integration test that
        silently checks less than its name claims is worse than no test —
        that is precisely how this feature's original defect survived.
        """
        names, values = seeded
        assert ParameterStoreProvider().fetch(names["secure"]) == values["secure"]

    def test_decryption_is_proven_wherever_the_endpoint_encrypts(
        self, seeded: Any
    ) -> None:
        """Strengthens itself on an endpoint that really encrypts.

        Skips against Floci, passes meaningfully against real AWS or any
        emulator that implements KMS — so pointing `AWS_ENDPOINT_URL` at a
        stronger backend upgrades the suite without editing it.
        """
        import boto3

        names, values = seeded
        ssm = boto3.client("ssm")
        undecrypted = ssm.get_parameter(Name=names["secure"], WithDecryption=False)[
            "Parameter"
        ]["Value"]
        if undecrypted == values["secure"]:
            pytest.skip(
                "This endpoint does not encrypt SecureString "
                "(WithDecryption=False returns plaintext), so it cannot "
                "distinguish a decrypted read."
            )
        assert ParameterStoreProvider().fetch(names["secure"]) == values["secure"]
        assert ParameterStoreProvider().fetch(names["secure"]) != undecrypted

    def test_the_region_override_reaches_the_client(self, seeded: Any) -> None:
        names, values = seeded
        reference = f"{names['plain']}?region=us-east-1"
        assert ParameterStoreProvider().fetch(reference) == values["plain"]

    def test_a_missing_secret_raises_not_found(self, seeded: Any) -> None:
        with pytest.raises(SecretNotFoundError):
            SecretsManagerProvider().fetch("functualize-test/definitely-absent")

    def test_a_missing_parameter_raises_not_found(self, seeded: Any) -> None:
        with pytest.raises(SecretNotFoundError):
            ParameterStoreProvider().fetch("/functualize-test/definitely-absent")

    def test_is_ready_is_true_against_the_emulator(self, seeded: Any) -> None:
        assert SecretsManagerProvider().is_ready() is True


class TestTheFallbackChain:
    """A9: a chain resolves through to the entry that answers.

    Assembled here rather than asserted through the resolution chain, because
    what needs proving against the real API is that a *failed* provider raises
    something the chain can recognise as "try the next one" — a fake decides
    that by construction.
    """

    def test_a_chain_falls_through_to_the_entry_that_answers(self, seeded: Any) -> None:
        from functualize._config.manifest import parse_annotation

        names, values = seeded
        chain = f"aws-sm://functualize-test/absent | aws-ssm://{names['plain']}"
        providers = {
            "aws-sm": SecretsManagerProvider(),
            "aws-ssm": ParameterStoreProvider(),
        }

        resolved = None
        attempted = []
        for annotation in parse_annotation(chain) or []:
            attempted.append(annotation.provider)
            try:
                resolved = providers[annotation.provider].fetch(annotation.reference)
                break
            except SecretNotFoundError:
                continue

        assert attempted == ["aws-sm", "aws-ssm"], "the first entry was not tried"
        assert resolved == values["plain"]

    def test_per_entry_overrides_survive_the_chain(self, seeded: Any) -> None:
        """Core splits a chain on ` | ` and hands each reference over whole,
        query string included."""
        from functualize._config.manifest import parse_annotation

        names, _ = seeded
        chain = f"aws-sm://absent?region=eu-west-1 | aws-ssm://{names['plain']}?region=us-east-1"
        parsed = parse_annotation(chain) or []
        assert parsed[0].reference.endswith("?region=eu-west-1")
        assert parsed[1].reference.endswith("?region=us-east-1")
