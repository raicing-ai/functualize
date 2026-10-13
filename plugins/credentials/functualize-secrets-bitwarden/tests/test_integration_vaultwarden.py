"""Against a real ``bw`` CLI — the Vaultwarden option (spec A4).

The fakes in ``test_pm_provider.py`` prove this plugin's own logic. They
cannot prove that ``bw status`` really distinguishes "not logged in" from
"locked" on today's CLI, that ``bw get item --raw`` really emits the JSON
shape the extraction reads, or that the listed shapes hold against
**Vaultwarden** and against bitwarden.com — every one of those is an
assertion about `bw` and the server, and a fake restates the assumption
instead of testing it.

The setup mirrors the AWS suite's emulator module, with one difference that
matters: the AWS emulator is a throwaway container this suite points at with
an env var, while a working ``bw`` session here is the operator's *real*
vault. So this module runs only when all three hold:

1. a ``bw`` executable on ``PATH``;
2. ``bw status`` reporting ``unlocked``;
3. an explicit opt-in — ``FUNCTUALIZE_BWPM_INTEGRATION=1`` — because the
   default must never be "write a test item into whatever vault the shell
   finds".

Vaultwarden in Docker is the expected backend (it implements exactly this
API, which is the reason the provider exists):

    docker run -d --name vaultwarden -p 8222:80 vaultwarden/server:latest
    bw config server http://localhost:8222
    bw login            # human: credentials and 2FA belong to you
    export BW_SESSION=$(bw unlock --raw)
    FUNCTUALIZE_BWPM_INTEGRATION=1 \
        uv run pytest plugins/credentials/functualize-secrets-bitwarden

Without all three the module skips. It does not fall back to a fake: a green
run that silently tested nothing is worse than a skip that says so.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from typing import Any

import pytest
from functualize_secrets_bitwarden import PasswordManagerProvider

pytestmark = pytest.mark.integration

_OPT_IN = os.environ.get("FUNCTUALIZE_BWPM_INTEGRATION") == "1"
_TAG = uuid.uuid4().hex[:8]
_ITEM_NAME = f"functualize-integration-{_TAG}"  # gitleaks:allow


def _unlocked() -> bool:
    from shutil import which

    if which("bw") is None:
        return False
    probe = subprocess.run(
        ["bw", "--nointeraction", "status", "--raw"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if probe.returncode != 0:
        return False
    try:
        return json.loads(probe.stdout).get("status") == "unlocked"
    except json.JSONDecodeError:
        return False


if not (_OPT_IN and _unlocked()):
    pytest.skip(
        "No opted-in unlocked `bw` session. Set FUNCTUALIZE_BWPM_INTEGRATION=1 "
        "with `bw` on PATH, signed in and unlocked (BW_SESSION exported); a "
        "locked vault skips rather than prompts.",
        allow_module_level=True,
    )


def _bw(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bw", "--nointeraction", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.fixture(scope="module")
def seeded() -> Any:
    """Create this run's own item through ``bw`` itself, then remove it.

    The name carries a uuid tag so a re-run against a long-lived vault
    cannot pass on a previous run's leftovers.
    """
    template = _bw("get", "template", "item", "--raw")
    if template.returncode != 0:
        pytest.fail(f"`bw get template item` failed: {template.stderr}")
    item = json.loads(template.stdout)
    item["name"] = _ITEM_NAME
    item["login"] = {
        "username": "integration-user",
        "password": "bwpm-integration-password",  # gitleaks:allow
        "totp": "otpauth://totp/integration:fixture?secret=JBSWY3DPEHPK3PXP",
        "uris": [{"uri": "https://integration.example.com"}],
    }
    item["notes"] = "created by the functualize integration suite"
    item["fields"] = [
        {"name": "api-key", "value": "integration-field-value", "type": 1}
    ]

    encoded = _bw("encode", stdin=json.dumps(item))
    if encoded.returncode != 0:
        pytest.fail("`bw encode` failed while preparing the integration item")
    created = _bw("create", "item", encoded.stdout.strip(), "--raw")
    if created.returncode != 0:
        pytest.fail("`bw create item` failed while seeding the integration item")
    item_id = str(json.loads(created.stdout)["id"])

    try:
        yield item_id
    finally:
        _bw("delete", "item", item_id, "--permanent")


class TestAgainstTheRealCli:
    def test_the_stored_seed_comes_back_for_totp(self, seeded: Any) -> None:
        value = PasswordManagerProvider().fetch(f"{seeded}/totp")
        assert value.startswith("otpauth://")

    def test_the_password_resolves(self, seeded: Any) -> None:
        assert (
            PasswordManagerProvider().fetch(f"{seeded}/password")
            == "bwpm-integration-password"
        )

    def test_the_username_uri_notes_and_custom_field_resolve(self, seeded: Any) -> None:
        provider = PasswordManagerProvider()
        assert provider.fetch(f"{seeded}/username") == "integration-user"
        assert provider.fetch(f"{seeded}/uri") == "https://integration.example.com"
        assert (
            provider.fetch(f"{seeded}/notes")
            == "created by the functualize integration suite"
        )
        assert provider.fetch(f"{seeded}/field:api-key") == "integration-field-value"

    def test_a_name_resolves_to_the_seeded_item(self, seeded: Any) -> None:
        """The listed shape matches the fetched shape for the same item."""
        assert (
            PasswordManagerProvider().fetch(f"{_ITEM_NAME}/password")
            == "bwpm-integration-password"
        )

    def test_an_unknown_field_refuses(self, seeded: Any) -> None:
        from functualize_secrets_bitwarden import InvalidReferenceError

        with pytest.raises(InvalidReferenceError, match="Unknown field"):
            PasswordManagerProvider().fetch(f"{seeded}/bogus")

    def test_is_ready_is_true_under_an_unlocked_session(self, seeded: Any) -> None:
        assert PasswordManagerProvider().is_ready() is True
