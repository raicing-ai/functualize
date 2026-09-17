"""The provider, against a fake SDK (remote-source-activation/5.2).

The single most important thing here: **the Bitwarden SDK does not raise on
failure.** Every call returns `ResponseFor…(success=False, data=None,
error_message=...)`. Reaching for `.data.value` without checking puts a `None`
into the vault, and a job then reads nothing where it expected a secret — with
no error anywhere. `unwrap` is the one place that turns the wrapper into a
value or an exception, and most of these tests exist to keep it there.
"""

from __future__ import annotations

from typing import Any

import pytest
from functualize_bitwarden import (
    ACCESS_TOKEN_VAR,
    AmbiguousKeyError,
    BitwardenAuthError,
    BitwardenRequestError,
    InvalidReferenceError,
    MissingOrganizationError,
    SecretNotFoundError,
    SecretsManagerProvider,
)
from functualize_bitwarden import _client as client_mod

from tests.conftest import (
    ORG,
    OTHER_ID,
    PROJECT_A,
    PROJECT_B,
    SECRET_ID,
    FakeAuthClient,
    FakeIdentifier,
    FakeResponse,
    FakeSecret,
    FakeSecretsClient,
)

#: Long and distinctive: a short value can satisfy a leak assertion by
#: coincidence. If this reaches an error message, something rendered a secret.
_SECRET = "PLAINTEXT-6d02af31-must-never-be-rendered"  # gitleaks:allow


def _secrets(**overrides: Any) -> FakeSecretsClient:
    return FakeSecretsClient(
        secrets={SECRET_ID: FakeSecret(value=_SECRET)}, **overrides
    )


class TestFetchingById:
    def test_a_uuid_resolves_in_one_call(self, bitwarden: Any) -> None:
        client = bitwarden(secrets=_secrets())
        assert SecretsManagerProvider().fetch(SECRET_ID) == _SECRET
        assert client.secrets().get_calls == [SECRET_ID]

    def test_it_never_lists(self, bitwarden: Any) -> None:
        """The whole point of the id form: no organization, no listing."""
        client = bitwarden(secrets=_secrets())
        SecretsManagerProvider().fetch(SECRET_ID)
        assert client.secrets().list_calls == []

    def test_a_missing_secret_raises(self, bitwarden: Any) -> None:
        bitwarden(secrets=_secrets())
        with pytest.raises(BitwardenRequestError, match="404"):
            SecretsManagerProvider().fetch(OTHER_ID)

    def test_no_organization_is_needed(self, bitwarden: Any) -> None:
        bitwarden(secrets=_secrets(), organization=None)
        assert SecretsManagerProvider().fetch(SECRET_ID) == _SECRET


class TestFetchingByKey:
    def _by_key(self, **kwargs: Any) -> FakeSecretsClient:
        return FakeSecretsClient(
            secrets={SECRET_ID: FakeSecret(value=_SECRET)},
            identifiers=[
                FakeIdentifier(id=SECRET_ID, key="DB_PASSWORD", project_ids=[PROJECT_A])
            ],
            **kwargs,
        )

    def test_a_key_name_resolves_through_the_listing(self, bitwarden: Any) -> None:
        client = bitwarden(secrets=self._by_key(), organization=ORG)
        assert SecretsManagerProvider().fetch("DB_PASSWORD") == _SECRET
        assert client.secrets().list_calls == [ORG]
        assert client.secrets().get_calls == [SECRET_ID]

    def test_an_unknown_key_raises_not_found(self, bitwarden: Any) -> None:
        bitwarden(secrets=self._by_key(), organization=ORG)
        with pytest.raises(SecretNotFoundError, match="NOPE"):
            SecretsManagerProvider().fetch("NOPE")

    def test_a_key_with_no_organization_says_what_to_do(self, bitwarden: Any) -> None:
        bitwarden(secrets=self._by_key(), organization=None)
        with pytest.raises(MissingOrganizationError) as exc:
            SecretsManagerProvider().fetch("DB_PASSWORD")
        message = str(exc.value)
        assert "BWS_ORGANIZATION_ID" in message
        assert "?organization=" in message
        assert "uuid" in message

    def test_the_annotation_overrides_the_environment(self, bitwarden: Any) -> None:
        other = "cccccccc-1111-2222-3333-444444444444"
        client = bitwarden(secrets=self._by_key(), organization=ORG)
        SecretsManagerProvider().fetch(f"DB_PASSWORD?organization={other}")
        assert client.secrets().list_calls == [other]


class TestAmbiguity:
    def _duplicated(self) -> FakeSecretsClient:
        return FakeSecretsClient(
            secrets={
                SECRET_ID: FakeSecret(value=_SECRET),
                OTHER_ID: FakeSecret(id=OTHER_ID, value="other"),
            },
            identifiers=[
                FakeIdentifier(
                    id=SECRET_ID, key="DB_PASSWORD", project_ids=[PROJECT_A]
                ),
                FakeIdentifier(id=OTHER_ID, key="DB_PASSWORD", project_ids=[PROJECT_B]),
            ],
        )

    def test_two_matches_raise_rather_than_picking(self, bitwarden: Any) -> None:
        """A wrong pick is a *working* run with the wrong credential — the
        quietest possible failure."""
        bitwarden(secrets=self._duplicated(), organization=ORG)
        with pytest.raises(AmbiguousKeyError):
            SecretsManagerProvider().fetch("DB_PASSWORD")

    def test_the_error_names_every_candidate(self, bitwarden: Any) -> None:
        bitwarden(secrets=self._duplicated(), organization=ORG)
        with pytest.raises(AmbiguousKeyError) as exc:
            SecretsManagerProvider().fetch("DB_PASSWORD")
        assert SECRET_ID in str(exc.value)
        assert OTHER_ID in str(exc.value)

    def test_the_error_says_how_to_disambiguate(self, bitwarden: Any) -> None:
        bitwarden(secrets=self._duplicated(), organization=ORG)
        with pytest.raises(AmbiguousKeyError, match=r"\?project=<uuid>"):
            SecretsManagerProvider().fetch("DB_PASSWORD")

    def test_a_project_narrows_it(self, bitwarden: Any) -> None:
        bitwarden(secrets=self._duplicated(), organization=ORG)
        assert (
            SecretsManagerProvider().fetch(f"DB_PASSWORD?project={PROJECT_A}")
            == _SECRET
        )

    def test_a_project_matching_nothing_raises_not_found(self, bitwarden: Any) -> None:
        empty = "dddddddd-1111-2222-3333-444444444444"
        bitwarden(secrets=self._duplicated(), organization=ORG)
        with pytest.raises(SecretNotFoundError, match=empty):
            SecretsManagerProvider().fetch(f"DB_PASSWORD?project={empty}")

    def test_project_ids_is_a_membership_test_not_equality(
        self, bitwarden: Any
    ) -> None:
        """`SecretIdentifierResponse.project_ids` is plural: a secret may sit
        in more than one project."""
        secrets = FakeSecretsClient(
            secrets={SECRET_ID: FakeSecret(value=_SECRET)},
            identifiers=[
                FakeIdentifier(
                    id=SECRET_ID, key="SHARED", project_ids=[PROJECT_A, PROJECT_B]
                )
            ],
        )
        bitwarden(secrets=secrets, organization=ORG)
        for project in (PROJECT_A, PROJECT_B):
            assert (
                SecretsManagerProvider().fetch(f"SHARED?project={project}") == _SECRET
            )


class TestTheResponseWrapperIsAlwaysChecked:
    """The SDK reports failure in the return value. Missing one check writes a
    None into the vault."""

    def test_a_failed_get_raises_with_the_sdk_message(self, bitwarden: Any) -> None:
        bitwarden(secrets=_secrets(get_failure="403 Forbidden"))
        with pytest.raises(BitwardenRequestError, match="403 Forbidden"):
            SecretsManagerProvider().fetch(SECRET_ID)

    def test_a_failed_list_raises_with_the_sdk_message(self, bitwarden: Any) -> None:
        bitwarden(secrets=_secrets(list_failure="401 Unauthorized"), organization=ORG)
        with pytest.raises(BitwardenRequestError, match="401 Unauthorized"):
            SecretsManagerProvider().fetch("DB_PASSWORD")

    def test_success_with_no_payload_raises(self) -> None:
        """Should not happen. If it does, the alternative to raising is a
        `None` in the vault."""
        with pytest.raises(BitwardenRequestError, match="returned nothing"):
            client_mod.unwrap(FakeResponse(success=True, data=None), "a secret")

    def test_a_failure_with_no_message_still_raises(self) -> None:
        with pytest.raises(BitwardenRequestError, match="no reason given"):
            client_mod.unwrap(FakeResponse(success=False), "a secret")

    def test_a_secret_with_a_null_value_raises(self, bitwarden: Any) -> None:
        secrets = FakeSecretsClient(secrets={SECRET_ID: FakeSecret(value=None)})
        bitwarden(secrets=secrets)
        with pytest.raises(SecretNotFoundError, match="no value"):
            SecretsManagerProvider().fetch(SECRET_ID)


class TestAuthentication:
    def test_no_token_raises_naming_the_variable(self, bitwarden: Any) -> None:
        bitwarden(secrets=_secrets(), token=None)
        with pytest.raises(BitwardenAuthError, match=ACCESS_TOKEN_VAR):
            SecretsManagerProvider().fetch(SECRET_ID)

    def test_a_rejected_token_raises_with_the_reason(self, bitwarden: Any) -> None:
        bitwarden(
            secrets=_secrets(), auth=FakeAuthClient(failure="invalid access token")
        )
        with pytest.raises(BitwardenAuthError, match="invalid access token"):
            SecretsManagerProvider().fetch(SECRET_ID)

    def test_the_state_file_is_never_written(self, bitwarden: Any) -> None:
        """An auth-state file on disk is a credential at rest. Same reasoning
        as the AWS provider's in-memory STS cache."""
        auth = FakeAuthClient()
        bitwarden(secrets=_secrets(), auth=auth)
        SecretsManagerProvider().fetch(SECRET_ID)
        assert auth.logins == [("0.abc.def:ghi", None)]

    def test_login_happens_once_per_process(self, bitwarden: Any) -> None:
        """A sync fetching thirty secrets authenticates once."""
        auth = FakeAuthClient()
        bitwarden(secrets=_secrets(), auth=auth)
        provider = SecretsManagerProvider()
        provider.fetch(SECRET_ID)
        provider.fetch(SECRET_ID)
        assert len(auth.logins) == 1

    def test_clearing_the_cache_forces_a_new_login(self, bitwarden: Any) -> None:
        auth = FakeAuthClient()
        bitwarden(secrets=_secrets(), auth=auth)
        SecretsManagerProvider().fetch(SECRET_ID)
        client_mod.clear_client_cache()
        SecretsManagerProvider().fetch(SECRET_ID)
        assert len(auth.logins) == 2


class TestConfiguration:
    def test_the_endpoints_default_to_bitwarden_cloud(self) -> None:
        settings = client_mod._settings()
        assert settings["apiUrl"] == "https://api.bitwarden.com"
        assert settings["identityUrl"] == "https://identity.bitwarden.com"

    def test_the_endpoints_are_overridable(self, monkeypatch: Any) -> None:
        """For a self-hosted *Bitwarden* server. Not Vaultwarden, which does
        not implement Secrets Manager at all."""
        monkeypatch.setenv("BWS_API_URL", "https://bw.internal/api")
        monkeypatch.setenv("BWS_IDENTITY_URL", "https://bw.internal/identity")
        settings = client_mod._settings()
        assert settings["apiUrl"] == "https://bw.internal/api"
        assert settings["identityUrl"] == "https://bw.internal/identity"


class TestNothingRendersTheValue:
    def test_an_ambiguity_error_names_ids_only(self, bitwarden: Any) -> None:
        secrets = FakeSecretsClient(
            secrets={
                SECRET_ID: FakeSecret(value=_SECRET),
                OTHER_ID: FakeSecret(id=OTHER_ID, value=_SECRET),
            },
            identifiers=[
                FakeIdentifier(id=SECRET_ID, key="K"),
                FakeIdentifier(id=OTHER_ID, key="K"),
            ],
        )
        bitwarden(secrets=secrets, organization=ORG)
        with pytest.raises(AmbiguousKeyError) as exc:
            SecretsManagerProvider().fetch("K")
        assert _SECRET not in str(exc.value)

    def test_a_request_error_carries_no_value(self, bitwarden: Any) -> None:
        bitwarden(secrets=_secrets(get_failure=f"failed reading {_SECRET}"[:20]))
        with pytest.raises(BitwardenRequestError) as exc:
            SecretsManagerProvider().fetch(SECRET_ID)
        assert _SECRET not in str(exc.value)

    def test_the_provider_holds_no_fetched_state(self, bitwarden: Any) -> None:
        bitwarden(secrets=_secrets())
        provider = SecretsManagerProvider()
        provider.fetch(SECRET_ID)
        assert _SECRET not in repr(vars(provider))


class TestTheEntryPointContract:
    def test_the_identifier_matches_the_annotation_scheme(self) -> None:
        assert SecretsManagerProvider().identifier() == "bws"

    def test_it_satisfies_the_protocol(self) -> None:
        from functualize._config.protocols import RemoteProvider

        assert isinstance(SecretsManagerProvider(), RemoteProvider)

    def test_is_ready_is_false_with_no_token(self) -> None:
        assert SecretsManagerProvider().is_ready() is False

    def test_is_ready_is_true_with_a_token(self, monkeypatch: Any) -> None:
        monkeypatch.setenv(ACCESS_TOKEN_VAR, "0.abc.def:ghi")
        assert SecretsManagerProvider().is_ready() is True

    def test_is_ready_makes_no_network_call(self, bitwarden: Any) -> None:
        """Readiness is asked per value; a round-trip each time is a fetch,
        not a check."""
        auth = FakeAuthClient()
        bitwarden(secrets=_secrets(), auth=auth)
        SecretsManagerProvider().is_ready()
        assert auth.logins == []

    def test_a_bad_reference_fails_before_authenticating(self, bitwarden: Any) -> None:
        auth = FakeAuthClient()
        bitwarden(secrets=_secrets(), auth=auth)
        with pytest.raises(InvalidReferenceError):
            SecretsManagerProvider().fetch("K?porject=x")
        assert auth.logins == []
