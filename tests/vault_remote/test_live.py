"""The live tier — one real origin, opt-in, never in CI.

Skipped silently unless ``FUNC_VAULT_LIVE=1`` and ``FUNC_VAULT_ORIGIN`` (or
the default public vault) are deliberately set, per A7: functualize's own
suite stays cloud-free; the product-level claim ("any user, accountlessly,
through the live vault") is witnessed by the funccloud-side eval that pins
this submodule. This tier exists for the one recorded manual run (C1) and
for a self-hoster pointing ``FUNC_VAULT_ORIGIN`` at their own vault.
"""

from __future__ import annotations

import os
import re
import secrets

import pytest

from functualize.app.vault_remote import (
    DEFAULT_ORIGIN,
    VaultRedeemError,
    fetch_share_meta,
    redeem_link,
    resolve_origin,
    share,
)

_LIVE = os.environ.get("FUNC_VAULT_LIVE") == "1"
_ORIGIN = resolve_origin() if _LIVE else DEFAULT_ORIGIN

pytestmark = pytest.mark.skipif(
    not _LIVE,
    reason="live vault tier: set FUNC_VAULT_LIVE=1 (and FUNC_VAULT_ORIGIN "
    "for a non-default origin) to run against a real vault",
)

_LINK_RE = re.compile(r"^https?://\S+/s/[0-9a-f]{32}#k1\.[A-Za-z0-9_-]{43}$")


def test_health_and_journey_round_trip() -> None:
    """Share → preview → redeem → spent, against the configured live vault."""
    value = "func-live-" + secrets.token_hex(8)
    report = share(
        [{"name": "FUNC_LIVE_PROBE", "kind": "secret", "value": value}],
        labels=["functualize-live-probe"],
        redemptions=1,
        expires_in_hours=1,
    )
    assert _LINK_RE.match(report.link)

    origin, share_id, _ = (
        report.link.split("/s/")[0],
        report.link.split("/s/")[1].split("#")[0],
        None,
    )
    assert origin == _ORIGIN
    meta = fetch_share_meta(origin, share_id)
    assert meta.redemptions_left == 1

    bundle = redeem_link(report.link)
    assert bundle.items[0]["value"] == value
    assert bundle.labels == ["functualize-live-probe"]

    with pytest.raises(VaultRedeemError) as exc:
        redeem_link(report.link)
    assert exc.value.reason == "gone"
