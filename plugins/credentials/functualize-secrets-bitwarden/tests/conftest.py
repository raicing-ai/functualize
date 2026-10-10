"""Fixtures for the Bitwarden provider tests.

Per the task: tested against a fake, not a live account. Bitwarden Secrets
Manager has no self-hostable open-source implementation to point at —
Vaultwarden implements the *password manager* API, a different product — so
there is no equivalent of the AWS suite's Floci container. The fakes here
model the SDK's response shapes exactly, including the part that matters most:
**the SDK signals failure in its return value rather than by raising.**
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import pytest
from functualize_secrets_bitwarden import clear_cli_state_cache, clear_client_cache

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


# --- The `bwpm` side: a fake `bw` executable on PATH ------------------------
#
# The Password Manager provider has no SDK to fake — its transport *is* a
# subprocess — so the fake is an executable. It models the shapes the real
# `bw` CLI is documented to emit, and it logs every invocation so tests can
# assert about the subprocess surface itself: that `status` is probed once,
# that a grammar typo spawns nothing, and that no `--session` argument ever
# appears on a command line.

#: Distinctive and long: a short value could satisfy a leak assertion by
#: coincidence. If this string reaches an error message, a log or a command
#: line, something rendered the session key.
SESSION_KEY = "BWPM-FIXTURE-SESSION-9f2e41d7-must-never-be-rendered"  # gitleaks:allow

ITEM_ID = "3f2b9c81-5d4e-4a77-8b21-9c0d2e4f6a88"
OTHER_ITEM_ID = "7c1d3e95-2a48-4b66-9d03-8e1f4a5c7b90"

#: Long and distinctive: if it reaches an error message, something rendered
#: a value.
PASSWORD_VALUE = "PM-FIXTURE-6d02af31-password-not-real"  # gitleaks:allow

_SHIM_SOURCE = """\
#!/usr/bin/env python
import json
import os
import sys

state_dir = os.environ["BWPM_SHIM_DIR"]
argv = sys.argv[1:]
with open(os.path.join(state_dir, "invocations.jsonl"), "a", encoding="utf-8") as log:
    log.write(
        json.dumps({"argv": argv, "session_env": bool(os.environ.get("BW_SESSION"))})
        + "\\n"
    )


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


status = json.load(
    open(os.path.join(state_dir, "status.json"), encoding="utf-8")
)
items = json.load(open(os.path.join(state_dir, "items.json"), encoding="utf-8"))

if argv[:3] == ["--nointeraction", "status", "--raw"]:
    if status.get("status_stderr") is not None:
        fail(status["status_stderr"])
    print(json.dumps({"serverUrl": "https://shim.invalid", "status": status["state"]}))
elif argv[:3] == ["--nointeraction", "get", "item"] and argv[-1] == "--raw":
    if status.get("get_stderr") is not None:
        fail(status["get_stderr"])
    found = items["by_id"].get(argv[3])
    if found is None:
        fail("Not found. " + argv[3])
    print(json.dumps(found))
elif argv[:3] == ["--nointeraction", "list", "items"] and argv[-1] == "--raw":
    if status.get("list_stderr") is not None:
        fail(status["list_stderr"])
    print(json.dumps(items["list"]))
else:
    fail("shim: unexpected invocation " + repr(argv))
"""


class BwShim:
    """Handle over the installed fake: its state files and invocation log."""

    def __init__(self, bin_dir: Any, state_dir: Any) -> None:
        self.bin_dir = bin_dir
        self.state_dir = state_dir

    @property
    def invocations(self) -> list[dict[str, Any]]:
        """Every invocation so far, oldest first: ``argv`` and
        ``session_env`` (whether the child saw a session, never its value)."""
        log = self.state_dir / "invocations.jsonl"
        if not log.exists():
            return []
        return [
            json.loads(line)
            for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def set_state(self, state: str) -> None:
        """Rewrite the probe answer — the child re-reads the file each run."""
        status = json.loads((self.state_dir / "status.json").read_text("utf-8"))
        status["state"] = state
        (self.state_dir / "status.json").write_text(json.dumps(status), "utf-8")


@pytest.fixture
def bw_shim(monkeypatch: Any, tmp_path: Any) -> Any:
    """Install a fake ``bw`` executable on PATH and return a handle to it.

    ``items`` is a list of item dicts (each with ``id`` and ``name``); the
    shim serves ``get item <id>`` from the same dicts it lists, exactly as
    the real CLI serves one item store. A ``session`` sets ``$BW_SESSION``
    for the child to inherit — the one way this provider may ever receive
    one.
    """

    def install(
        *,
        state: str = "unlocked",
        items: list[dict[str, Any]] | None = None,
        status_stderr: str | None = None,
        get_stderr: str | None = None,
        list_stderr: str | None = None,
        session: str | None = None,
    ) -> BwShim:
        entries = items or []
        by_id = {entry["id"]: entry for entry in entries}
        if len(by_id) != len(entries):
            raise ValueError("fixture items carry duplicate ids")

        bin_dir = tmp_path / "bin"
        state_dir = tmp_path / "bw-state"
        bin_dir.mkdir(exist_ok=True)
        state_dir.mkdir(exist_ok=True)
        # A test may install twice (e.g. one shim, then a state change); each
        # install starts from an empty invocation log so assertions stay
        # about *this* shim.
        log = state_dir / "invocations.jsonl"
        if log.exists():
            log.unlink()
        executable = bin_dir / "bw"
        executable.write_text(_SHIM_SOURCE, encoding="utf-8")
        executable.chmod(0o755)
        (state_dir / "status.json").write_text(
            json.dumps(
                {
                    "state": state,
                    "status_stderr": status_stderr,
                    "get_stderr": get_stderr,
                    "list_stderr": list_stderr,
                }
            ),
            encoding="utf-8",
        )
        (state_dir / "items.json").write_text(
            json.dumps({"by_id": by_id, "list": entries}), encoding="utf-8"
        )

        monkeypatch.setenv("PATH", str(bin_dir), prepend=os.pathsep)
        monkeypatch.setenv("BWPM_SHIM_DIR", str(state_dir))
        if session is not None:
            monkeypatch.setenv("BW_SESSION", session)
        return BwShim(bin_dir, state_dir)

    return install


def pm_item(**overrides: Any) -> dict[str, Any]:
    """One login item shaped the way the real CLI's JSON is read here."""
    item: dict[str, Any] = {
        "id": ITEM_ID,
        "name": "deploy-token",
        "notes": "fixture notes line",
        "login": {
            "username": "fixture-user",
            "password": PASSWORD_VALUE,
            "totp": "otpauth://totp/example:fixture?secret=JBSWY3DPEHPK3PXP",
            "uris": [{"uri": "https://fixture.example.com"}],
        },
        "fields": [
            {"name": "api-key", "value": "PM-FIXTURE-api-key-value", "type": 1},
            {"name": "region", "value": "eu-west-1", "type": 0},
        ],
    }
    item.update(overrides)
    return item


@pytest.fixture(autouse=True)
def clean_cli_state() -> Any:
    """The probed session state is module-global; never let it cross a test."""
    clear_cli_state_cache()
    yield
    clear_cli_state_cache()


@pytest.fixture(autouse=True)
def no_ambient_session(monkeypatch: Any) -> None:
    """No session unless a test says so — same rule as ``no_ambient_bitwarden``.

    A developer running this suite inside a terminal with ``$BW_SESSION``
    exported must not run a different suite from CI.
    """
    monkeypatch.delenv("BW_SESSION", raising=False)
