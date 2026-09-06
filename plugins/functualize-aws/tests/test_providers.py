"""The two providers, and the credential rules the grammar only declares.

`test_reference.py` proves an override *parses*. These prove it *acts* — that
`profile` reaches the session, `role` is assumed from it rather than instead of
it, `account` is checked after any assumption, and that nothing here ever
renders a secret.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from functualize_aws import (
    AccountMismatchError,
    InvalidReferenceError,
    ParameterStoreProvider,
    SecretNotFoundError,
    SecretsManagerProvider,
    clear_credential_cache,
    parse_reference,
)
from functualize_aws import _session as session_mod

from tests.conftest import FakeClient

#: Long and distinctive on purpose: a short value can satisfy a leak assertion
#: by coincidence. If this appears in an error or a repr, something rendered a
#: secret.
_SECRET = "PLAINTEXT-4b91c7e2-must-never-be-rendered"  # gitleaks:allow

_ROLE = "arn:aws:iam::123456789012:role/Deploy"


def _sm_client(value: str = _SECRET) -> FakeClient:
    return FakeClient(
        responses={"get_secret_value": {"SecretString": value}},
        exception_names=("ResourceNotFoundException",),
    )


def _ssm_client(value: str = _SECRET) -> FakeClient:
    return FakeClient(
        responses={"get_parameter": {"Parameter": {"Value": value}}},
        exception_names=("ParameterNotFound", "ParameterVersionNotFound"),
    )


@pytest.fixture
def patched_client(monkeypatch: Any) -> Any:
    """Replace `client_for`, recording the reference and service it was handed."""
    seen: dict[str, Any] = {}

    def install(client: FakeClient) -> dict[str, Any]:
        def fake_client_for(ref: Any, service: str) -> FakeClient:
            seen["ref"] = ref
            seen["service"] = service
            return client

        monkeypatch.setattr("functualize_aws.client_for", fake_client_for)
        return seen

    return install


class TestSecretsManager:
    def test_it_fetches_by_name(self, patched_client: Any) -> None:
        client = _sm_client()
        seen = patched_client(client)
        assert SecretsManagerProvider().fetch("prod/db") == _SECRET
        assert client.calls == [("get_secret_value", {"SecretId": "prod/db"})]
        assert seen["service"] == "secretsmanager"

    def test_a_missing_secret_raises_not_found(self, patched_client: Any) -> None:
        client = _sm_client()
        client.raises = "ResourceNotFoundException"
        patched_client(client)
        with pytest.raises(SecretNotFoundError, match="prod/absent"):
            SecretsManagerProvider().fetch("prod/absent")

    def test_a_binary_secret_is_refused_not_guessed(self, patched_client: Any) -> None:
        """Guessing an encoding hands a job silently-wrong bytes."""
        client = FakeClient(
            responses={"get_secret_value": {"SecretBinary": b"\x00\x01"}},
            exception_names=("ResourceNotFoundException",),
        )
        patched_client(client)
        with pytest.raises(InvalidReferenceError, match="binary"):
            SecretsManagerProvider().fetch("prod/blob")


class TestParameterStore:
    def test_it_fetches_by_name(self, patched_client: Any) -> None:
        client = _ssm_client()
        patched_client(client)
        assert ParameterStoreProvider().fetch("/prod/api-url") == _SECRET

    def test_decryption_is_always_requested(self, patched_client: Any) -> None:
        """A SecureString read without it returns ciphertext, which would
        round-trip into the vault and reach a job looking exactly like a secret
        while being useless. It is ignored for String/StringList, so there is
        no knob here to get wrong.
        """
        client = _ssm_client()
        patched_client(client)
        ParameterStoreProvider().fetch("/prod/api-token")
        assert client.calls[0][1]["WithDecryption"] is True

    def test_a_missing_parameter_raises_not_found(self, patched_client: Any) -> None:
        client = _ssm_client()
        client.raises = "ParameterNotFound"
        patched_client(client)
        with pytest.raises(SecretNotFoundError, match="/prod/absent"):
            ParameterStoreProvider().fetch("/prod/absent")


class TestTheOverridesReachTheSession:
    def test_the_parsed_reference_is_what_builds_the_client(
        self, patched_client: Any
    ) -> None:
        seen = patched_client(_sm_client())
        SecretsManagerProvider().fetch("prod/db?profile=admin&region=eu-west-1")
        assert seen["ref"].profile == "admin"
        assert seen["ref"].region == "eu-west-1"

    def test_the_name_reaches_aws_without_the_override_block(
        self, patched_client: Any
    ) -> None:
        """The query string is this plugin's grammar, not AWS's."""
        client = _sm_client()
        patched_client(client)
        SecretsManagerProvider().fetch("prod/db?profile=admin")
        assert client.calls[0][1]["SecretId"] == "prod/db"

    def test_a_bad_override_fails_before_any_aws_call(
        self, patched_client: Any
    ) -> None:
        client = _sm_client()
        patched_client(client)
        with pytest.raises(InvalidReferenceError):
            SecretsManagerProvider().fetch("prod/db?porfile=admin")
        assert client.calls == []


class _FakeSts:
    def __init__(self, account: str, *, arn: str = "arn:aws:iam::x:user/u") -> None:
        self._account = account
        self._arn = arn
        self.assume_calls: list[dict[str, Any]] = []
        self.identity_calls = 0

    def get_caller_identity(self) -> dict[str, str]:
        self.identity_calls += 1
        return {"Account": self._account, "Arn": self._arn}

    def assume_role(self, **kwargs: Any) -> dict[str, Any]:
        self.assume_calls.append(kwargs)
        return {
            "Credentials": {
                "AccessKeyId": "AKIAFAKE",
                "SecretAccessKey": "fake-secret",  # gitleaks:allow
                "SessionToken": "fake-token",
                "Expiration": datetime.now(UTC) + timedelta(hours=1),
            }
        }


class _FakeSession:
    """Records how it was constructed, so precedence is observable."""

    made: list[dict[str, Any]] = []
    sts: _FakeSts

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.region_name = kwargs.get("region_name")
        type(self).made.append(kwargs)

    def client(self, service: str) -> Any:
        return type(self).sts if service == "sts" else FakeClient()


@pytest.fixture
def fake_sessions(monkeypatch: Any) -> Any:
    _FakeSession.made = []

    def install(sts: _FakeSts) -> type[_FakeSession]:
        _FakeSession.sts = sts
        monkeypatch.setattr(session_mod.boto3, "Session", _FakeSession)
        return _FakeSession

    return install


class TestCredentialPrecedence:
    def test_profile_selects_the_source_identity(self, fake_sessions: Any) -> None:
        fake_sessions(_FakeSts("111111111111"))
        session_mod.resolve_session(parse_reference("n?profile=admin"))
        assert _FakeSession.made[0]["profile_name"] == "admin"

    def test_no_profile_leaves_the_ambient_chain_alone(
        self, fake_sessions: Any
    ) -> None:
        fake_sessions(_FakeSts("111111111111"))
        session_mod.resolve_session(parse_reference("n"))
        assert "profile_name" not in _FakeSession.made[0]

    def test_role_is_assumed_from_the_profile_not_instead_of_it(
        self, fake_sessions: Any
    ) -> None:
        """The composition rule. If `role` replaced `profile`, the assumption
        would be attempted from the ambient identity — a different, and usually
        unauthorised, source.
        """
        sts = _FakeSts("111111111111")
        fake_sessions(sts)
        session_mod.resolve_session(parse_reference(f"n?profile=admin&role={_ROLE}"))
        assert _FakeSession.made[0]["profile_name"] == "admin"
        assert sts.assume_calls[0]["RoleArn"] == _ROLE

    def test_the_assumed_credentials_build_the_final_session(
        self, fake_sessions: Any
    ) -> None:
        fake_sessions(_FakeSts("111111111111"))
        session_mod.resolve_session(parse_reference(f"n?role={_ROLE}"))
        assert _FakeSession.made[-1]["aws_session_token"] == "fake-token"

    def test_region_reaches_the_session(self, fake_sessions: Any) -> None:
        fake_sessions(_FakeSts("111111111111"))
        session_mod.resolve_session(parse_reference("n?region=eu-west-1"))
        assert _FakeSession.made[0]["region_name"] == "eu-west-1"

    def test_region_survives_the_role_assumption(self, fake_sessions: Any) -> None:
        """The final session is built from scratch; the region must be carried
        onto it or a role'd fetch silently lands in the default region."""
        fake_sessions(_FakeSts("111111111111"))
        session_mod.resolve_session(parse_reference(f"n?region=eu-west-1&role={_ROLE}"))
        assert _FakeSession.made[-1]["region_name"] == "eu-west-1"


class TestTheAccountAssertion:
    def test_a_match_passes(self, fake_sessions: Any) -> None:
        fake_sessions(_FakeSts("123456789012"))
        session_mod.resolve_session(parse_reference("n?account=123456789012"))

    def test_a_mismatch_raises(self, fake_sessions: Any) -> None:
        """The whole reason `account` is checked rather than ignored: reading
        another account's secret while the config names the right one."""
        fake_sessions(_FakeSts("999999999999"))
        with pytest.raises(AccountMismatchError):
            session_mod.resolve_session(parse_reference("n?account=123456789012"))

    def test_the_error_names_both_accounts(self, fake_sessions: Any) -> None:
        fake_sessions(_FakeSts("999999999999"))
        with pytest.raises(AccountMismatchError) as exc:
            session_mod.resolve_session(parse_reference("n?account=123456789012"))
        assert "123456789012" in str(exc.value)
        assert "999999999999" in str(exc.value)

    def test_it_is_checked_after_the_role_is_assumed(self, fake_sessions: Any) -> None:
        """Checking the source identity would assert the wrong thing: the point
        of assuming a role is usually to cross into another account.
        """
        sts = _FakeSts("123456789012")
        fake_sessions(sts)
        session_mod.resolve_session(
            parse_reference(f"n?role={_ROLE}&account=123456789012")
        )
        assert sts.assume_calls, "the role was never assumed"
        assert sts.identity_calls == 1

    def test_no_account_means_no_identity_call(self, fake_sessions: Any) -> None:
        """An assertion nobody asked for should not cost a round-trip per value."""
        sts = _FakeSts("123456789012")
        fake_sessions(sts)
        session_mod.resolve_session(parse_reference("n?profile=admin"))
        assert sts.identity_calls == 0


class TestTemporaryCredentialsStayInMemory:
    def test_a_second_fetch_under_one_role_reuses_the_assumption(
        self, fake_sessions: Any
    ) -> None:
        sts = _FakeSts("111111111111")
        fake_sessions(sts)
        session_mod.resolve_session(parse_reference(f"a?role={_ROLE}"))
        session_mod.resolve_session(parse_reference(f"b?role={_ROLE}"))
        assert len(sts.assume_calls) == 1

    def test_a_different_role_assumes_again(self, fake_sessions: Any) -> None:
        sts = _FakeSts("111111111111")
        fake_sessions(sts)
        session_mod.resolve_session(
            parse_reference("a?role=arn:aws:iam::123456789012:role/One")
        )
        session_mod.resolve_session(
            parse_reference("a?role=arn:aws:iam::123456789012:role/Two")
        )
        assert len(sts.assume_calls) == 2

    def test_expiring_credentials_are_re_assumed(self, fake_sessions: Any) -> None:
        """The margin exists so a long sync cannot begin a fetch with
        credentials that die mid-call."""
        sts = _FakeSts("111111111111")
        fake_sessions(sts)
        session_mod.resolve_session(parse_reference(f"a?role={_ROLE}"))
        key = parse_reference(f"a?role={_ROLE}").identity_key
        session_mod._ASSUMED[key] = session_mod._Assumed(
            credentials=session_mod._ASSUMED[key].credentials,
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        session_mod.resolve_session(parse_reference(f"a?role={_ROLE}"))
        assert len(sts.assume_calls) == 2

    def test_nothing_is_written_to_disk(
        self, fake_sessions: Any, tmp_path: Any, monkeypatch: Any
    ) -> None:
        """The vault holds resolved values, not credentials. That is structural
        — only what `fetch()` returns is persisted — but a wrong future change
        should fail here first."""
        monkeypatch.chdir(tmp_path)
        fake_sessions(_FakeSts("111111111111"))
        session_mod.resolve_session(parse_reference(f"a?role={_ROLE}"))
        assert list(tmp_path.rglob("*")) == []

    def test_the_cache_can_be_cleared(self, fake_sessions: Any) -> None:
        sts = _FakeSts("111111111111")
        fake_sessions(sts)
        session_mod.resolve_session(parse_reference(f"a?role={_ROLE}"))
        clear_credential_cache()
        session_mod.resolve_session(parse_reference(f"a?role={_ROLE}"))
        assert len(sts.assume_calls) == 2


class TestNothingRendersTheValue:
    def test_a_not_found_error_names_the_reference_only(
        self, patched_client: Any
    ) -> None:
        client = _sm_client()
        client.raises = "ResourceNotFoundException"
        patched_client(client)
        with pytest.raises(SecretNotFoundError) as exc:
            SecretsManagerProvider().fetch("prod/absent")
        assert _SECRET not in str(exc.value)

    def test_the_provider_holds_no_fetched_state(self, patched_client: Any) -> None:
        provider = SecretsManagerProvider()
        patched_client(_sm_client())
        provider.fetch("prod/db")
        assert _SECRET not in repr(provider)
        assert _SECRET not in repr(vars(provider))


class TestTheEntryPointContract:
    def test_the_identifiers_match_the_annotation_schemes(self) -> None:
        assert SecretsManagerProvider().identifier() == "aws-sm"
        assert ParameterStoreProvider().identifier() == "aws-ssm"

    def test_both_satisfy_the_protocol(self) -> None:
        from functualize._config.protocols import RemoteProvider

        assert isinstance(SecretsManagerProvider(), RemoteProvider)
        assert isinstance(ParameterStoreProvider(), RemoteProvider)

    def test_is_ready_is_false_with_no_credentials_anywhere(self) -> None:
        """`no_ambient_aws` has cut every path boto3 uses. A provider claiming
        readiness here would fail at the first fetch instead."""
        assert SecretsManagerProvider().is_ready() is False

    def test_is_ready_is_cached(self, monkeypatch: Any) -> None:
        provider = SecretsManagerProvider()
        assert provider.is_ready() is False
        monkeypatch.setattr(provider, "_ready", True)
        assert provider.is_ready() is True
