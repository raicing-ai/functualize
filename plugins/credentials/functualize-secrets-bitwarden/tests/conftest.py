"""Fixtures for the Bitwarden provider tests.

Per the task: tested against a fake, not a live account. Bitwarden Secrets
Manager has no self-hostable open-source implementation to point at —
Vaultwarden implements the *password manager* API, a different product — so
there is no equivalent of the AWS suite's Floci container. The fakes here
model the SDK's response shapes exactly, including the part that matters most:
**the SDK signals failure in its return value rather than by raising.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from functualize_bitwarden import clear_client_cache

ORG = "11111111-2222-3333-4444-555555555555"
# A real-looking uuid, not a secret: the grammar tells an id from a key name by
# parsing it, so this must stay a valid v4-shaped uuid. The repeated-digit
# style used for the others is deliberately unrealistic; this one is not, so
# that `test_a_near_uuid_is_treated_as_a_key` has something to mutate.
SECRET_ID = "8a9c2f0e-1b3d-4c5e-9f70-2a1b3c4d5e6f"  # gitleaks:allow
OTHER_ID = "99999999-8888-7777-6666-555555555555"
PROJECT_A = "aaaaaaaa-1111-2222-3333-444444444444"
PROJECT_B = "bbbbbbbb-1111-2222-3333-444444444444"


@pytest.fixture(autouse=True)
def clean_client() -> Any:
    """The authenticated client is module state; never let it cross a test."""
    clear_client_cache()
    yield
    clear_client_cache()


@pytest.fixture(autouse=True)
def no_ambient_bitwarden(monkeypatch: Any) -> None:
    """No token, no organization, no server, unless a test says so.

    Without this, a developer with `BWS_ACCESS_TOKEN` exported runs a
    different suite from CI — and a test that accidentally reached the real
    API would pass on their machine and nowhere else.
    """
    for var in (
        "BWS_ACCESS_TOKEN",
        "BWS_ORGANIZATION_ID",
        "BWS_API_URL",
        "BWS_IDENTITY_URL",
    ):
        monkeypatch.delenv(var, raising=False)


@dataclass
class FakeResponse:
    """The SDK's `ResponseFor…` wrapper. It does not raise; it reports."""

    success: bool = True
    data: Any = None
    error_message: str | None = None


@dataclass
class FakeSecret:
    """`SecretResponse`: what `secrets().get(id)` returns inside the wrapper."""

    id: str = SECRET_ID
    key: str = "DB_PASSWORD"
    value: str = "unset"
    note: str | None = None
    organization_id: str = ORG
    project_id: str | None = None


@dataclass
class FakeIdentifier:
    """`SecretIdentifierResponse`: note `project_ids` is **plural**."""

    id: str
    key: str
    organization_id: str = ORG
    project_ids: list[str] = field(default_factory=list)


class FakeSecretsClient:
    def __init__(
        self,
        *,
        secrets: dict[str, FakeSecret] | None = None,
        identifiers: list[FakeIdentifier] | None = None,
        get_failure: str | None = None,
        list_failure: str | None = None,
    ) -> None:
        self.secrets_by_id = secrets or {}
        self.identifiers = identifiers or []
        self.get_failure = get_failure
        self.list_failure = list_failure
        self.get_calls: list[str] = []
        self.list_calls: list[str] = []

    def get(self, secret_id: str) -> FakeResponse:
        self.get_calls.append(secret_id)
        if self.get_failure is not None:
            return FakeResponse(success=False, error_message=self.get_failure)
        secret = self.secrets_by_id.get(secret_id)
        if secret is None:
            return FakeResponse(
                success=False, error_message=f"404 Not Found: {secret_id}"
            )
        return FakeResponse(data=secret)

    def list(self, organization_id: str) -> FakeResponse:
        self.list_calls.append(organization_id)
        if self.list_failure is not None:
            return FakeResponse(success=False, error_message=self.list_failure)
        return FakeResponse(data=_Identifiers(self.identifiers))


@dataclass
class _Identifiers:
    """`SecretIdentifiersResponse`, whose only field is a nested `data`."""

    data: list[FakeIdentifier]


class FakeAuthClient:
    def __init__(self, *, failure: str | None = None) -> None:
        self.failure = failure
        self.logins: list[tuple[str, Any]] = []

    def login_access_token(self, token: str, state_file: Any = None) -> FakeResponse:
        self.logins.append((token, state_file))
        if self.failure is not None:
            return FakeResponse(success=False, error_message=self.failure)
        return FakeResponse(data=object())


class FakeBitwardenClient:
    def __init__(
        self,
        settings: Any = None,
        *,
        secrets: FakeSecretsClient | None = None,
        auth: FakeAuthClient | None = None,
    ) -> None:
        self.settings = settings
        self._secrets = secrets or FakeSecretsClient()
        self._auth = auth or FakeAuthClient()

    def secrets(self) -> FakeSecretsClient:
        return self._secrets

    def auth(self) -> FakeAuthClient:
        return self._auth


@pytest.fixture
def bitwarden(monkeypatch: Any) -> Any:
    """Install a fake SDK client and export a token so login proceeds.

    Patches `BitwardenClient` where `_client` imports it — inside the
    function — so the real SDK is never constructed and no network call is
    possible from these tests.
    """

    def install(
        *,
        secrets: FakeSecretsClient | None = None,
        auth: FakeAuthClient | None = None,
        token: str | None = "0.abc.def:ghi",
        organization: str | None = None,
    ) -> FakeBitwardenClient:
        if token is not None:
            monkeypatch.setenv("BWS_ACCESS_TOKEN", token)
        if organization is not None:
            monkeypatch.setenv("BWS_ORGANIZATION_ID", organization)
        client = FakeBitwardenClient(secrets=secrets, auth=auth)
        monkeypatch.setattr(
            "bitwarden_sdk.BitwardenClient", lambda settings: client, raising=True
        )
        return client

    return install
