"""The client against the mock origin: journeys, burn semantics, hygiene.

Everything here exercises ``functualize.app.vault_remote`` end to end over
real HTTP against the in-process contracts-v1 server — no monkeypatching
inside the client, because the guarantees under test (fragment never sent,
UA obligation, burn semantics) live at the transport boundary. Where a
hostile or buggy server must be simulated, the request function is wrapped
so the real request — and its burn — still happens and only the answer the
client reads back is reshaped.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest

from functualize import __version__
from functualize.app import vault_remote
from functualize.app.vault_remote import (
    DEFAULT_ORIGIN,
    RedeemedBundle,
    VaultRedeemError,
    create_share,
    fetch_share_meta,
    parse_link,
    redeem_link,
)

if TYPE_CHECKING:
    from tests.vault_remote.mock_vault import MockVault

_SECRET = "correct-horse-battery-staple-9f3a"  # gitleaks:allow
_ITEMS = [
    {"name": "SLACK_BOT_TOKEN", "kind": "secret", "value": _SECRET},
    {"name": "region", "kind": "config", "value": "eu-west-1"},
]

_LINK_RE = re.compile(r"^https?://[^/]+/s/[0-9a-f]{32}#k1\.[A-Za-z0-9_-]{43}$")


def _share(
    mock_origin: MockVault,
    items: list[dict[str, str]] | None = None,
    **kwargs: Any,
) -> str:
    return create_share(mock_origin.origin, items or _ITEMS, labels=["demo"], **kwargs)


class TestShare:
    def test_returns_a_well_formed_link(self, mock_origin: MockVault) -> None:
        assert _LINK_RE.match(_share(mock_origin))

    def test_client_side_refusals_leave_the_machine(
        self, mock_origin: MockVault
    ) -> None:
        """Caps are frozen in the contract; enforcing them locally means a
        doomed request never carries the envelope anywhere."""
        with pytest.raises(VaultRedeemError) as exc:
            create_share(mock_origin.origin, _ITEMS, redemptions_allowed=0)
        assert exc.value.reason == "bad_redemptions"
        with pytest.raises(VaultRedeemError) as exc:
            create_share(mock_origin.origin, _ITEMS, expires_in_hours=169)
        assert exc.value.reason == "bad_expiry"
        with pytest.raises(VaultRedeemError) as exc:
            create_share(mock_origin.origin, _ITEMS, labels=["x" * 65])
        assert exc.value.reason == "bad_labels"
        with pytest.raises(VaultRedeemError) as exc:
            create_share(mock_origin.origin, [])
        assert exc.value.reason == "no_items"
        assert mock_origin.requests == []

    def test_a_bad_origin_is_refused(self) -> None:
        with pytest.raises(VaultRedeemError) as exc:
            create_share("ftp://vault.example", _ITEMS)
        assert exc.value.reason == "bad_origin"


class TestPreviewNeverBurns:
    def test_meta_keeps_the_counter_constant(self, mock_origin: MockVault) -> None:
        link = _share(mock_origin)
        origin, share_id, _ = parse_link(link)
        seen = [fetch_share_meta(origin, share_id) for _ in range(3)]
        assert {m.redemptions_left for m in seen} == {1}
        assert {m.redemptions_total for m in seen} == {1}
        assert seen[0].labels == ["demo"]

    def test_unknown_share_is_not_found(self, mock_origin: MockVault) -> None:
        with pytest.raises(VaultRedeemError) as exc:
            fetch_share_meta(mock_origin.origin, "0" * 32)
        assert exc.value.reason == "not_found"


class TestRedeem:
    def test_round_trip_returns_the_original_items(
        self, mock_origin: MockVault
    ) -> None:
        link = _share(mock_origin)
        bundle = redeem_link(link)
        assert bundle.items == _ITEMS
        assert bundle.labels == ["demo"]
        assert bundle.share_id == parse_link(link)[1]

    def test_a_bundle_repr_never_carries_a_value(self, mock_origin: MockVault) -> None:
        sentinel = "SENTINEL-$(touch pwned)-do-not-print"
        link = _share(
            mock_origin,
            [{"name": "SLACK_BOT_TOKEN", "kind": "secret", "value": sentinel}],
        )
        bundle = redeem_link(link)

        assert bundle.items[0]["value"] == sentinel  # it did round-trip
        assert sentinel not in repr(bundle)
        assert sentinel not in str(bundle)

    def test_spent_share_is_gone_exactly(self, mock_origin: MockVault) -> None:
        link = _share(mock_origin)
        redeem_link(link)
        with pytest.raises(VaultRedeemError) as exc:
            redeem_link(link)
        assert exc.value.reason == "gone"

    def test_expired_share_is_gone(self, mock_origin: MockVault) -> None:
        link = _share(mock_origin, expires_in_hours=1)
        share_id = parse_link(link)[1]
        expires_at = float(mock_origin.shares[share_id]["expires_at"])
        mock_origin.now = lambda: expires_at + 3600
        with pytest.raises(VaultRedeemError) as exc:
            redeem_link(link)
        assert exc.value.reason == "gone"

    def test_exactly_n_winners_for_n_redemptions(self, mock_origin: MockVault) -> None:
        """The wire's atomicity guarantee, asserted through the client: 8
        concurrent claims on a 3-redemption share yield exactly 3 winners,
        with the other 5 refused as `gone` — never a 4th decryption."""
        import concurrent.futures

        link = _share(mock_origin, redemptions_allowed=3)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(redeem_link, link) for _ in range(8)]
            outcomes = [
                f.result() if f.exception() is None else f.exception() for f in futures
            ]
        winners = [o for o in outcomes if isinstance(o, RedeemedBundle)]
        refusals = [o for o in outcomes if isinstance(o, VaultRedeemError)]
        assert len(winners) == 3
        assert len(refusals) == 5
        assert {e.reason for e in refusals} == {"gone"}


def _reshape_answers(monkeypatch: pytest.MonkeyPatch, reshape: Any) -> None:
    """Let the real request happen — and its burn — then reshape the
    answer the client reads back: exactly a hostile or buggy server."""
    real = vault_remote._request

    def mutator(
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        response = real(method, url, body=body, token=token, timeout=timeout)
        reshape(method, response)
        return response

    monkeypatch.setattr(vault_remote, "_request", mutator)


class TestFailClosedClient:
    def test_wrong_key_link_fails_as_one_class(self, mock_origin: MockVault) -> None:
        link = _share(mock_origin)
        wrong = link[: link.rindex("#")] + "#" + _other_fragment_key()
        with pytest.raises(VaultRedeemError) as exc:
            redeem_link(wrong)
        assert exc.value.reason == "open_failed"
        assert _SECRET not in str(exc.value)

    def test_tampered_envelope_fails_closed(self, mock_origin: MockVault) -> None:
        link = _share(mock_origin)
        mock_origin.corrupt_next_envelope = True
        with pytest.raises(VaultRedeemError) as exc:
            redeem_link(link)
        assert exc.value.reason == "open_failed"

    def test_unknown_share_is_not_found(self, mock_origin: MockVault) -> None:
        with pytest.raises(VaultRedeemError) as exc:
            redeem_link(f"{mock_origin.origin}/s/{'0' * 32}#{_other_fragment_key()}")
        assert exc.value.reason == "not_found"

    @pytest.mark.parametrize(
        "shape",
        [
            "envelope_not_json",
            "envelope_not_object",
            "metadata_not_object",
            "items_not_list",
            "item_not_dict",
            "nonce_missing",
        ],
    )
    def test_a_malformed_redeem_answer_fails_closed_after_the_burn(
        self, mock_origin: MockVault, monkeypatch: pytest.MonkeyPatch, shape: str
    ) -> None:
        """A redeem answer that does not parse into the expected shape is
        one closed failure, never a raw traceback — and it comes after the
        claim, so the link is spent either way. What the local opener
        touches fails as one class: the tampered bundle's message."""

        # Reference first — the tampered bundle's class and message, before
        # the reshaper below is installed (it fires on every POST redeem).
        ref_link = _share(mock_origin)
        mock_origin.corrupt_next_envelope = True
        with pytest.raises(VaultRedeemError) as ref_exc:
            redeem_link(ref_link)
        reference = ref_exc.value

        def reshape(method: str, response: dict[str, Any]) -> None:
            if method != "POST" or not response.get("envelope"):
                return
            if shape == "envelope_not_json":
                response["envelope"] = "{oops"
                return
            envelope = json.loads(response["envelope"])
            if shape == "envelope_not_object":
                envelope = []
            elif shape == "metadata_not_object":
                envelope["metadata"] = 5
            elif shape == "items_not_list":
                envelope["items"] = 5
            elif shape == "item_not_dict":
                envelope["items"] = ["x"]
            elif shape == "nonce_missing":
                del envelope["items"][0]["nonce"]
            response["envelope"] = json.dumps(envelope)

        _reshape_answers(monkeypatch, reshape)
        link = _share(mock_origin)

        with pytest.raises(VaultRedeemError) as exc:
            redeem_link(link)
        if shape in {"items_not_list", "item_not_dict", "nonce_missing"}:
            # In-envelope shape: one indistinguishable class — identical
            # type and message to the tampered bundle's failure.
            assert type(exc.value) is type(reference)
            assert str(exc.value) == str(reference)
            assert exc.value.reason == "open_failed"
        else:
            assert exc.value.reason == "bad_response"
        with pytest.raises(VaultRedeemError) as gone:
            redeem_link(link)
        assert gone.value.reason == "gone"

    def test_a_malformed_meta_answer_is_one_bad_response(
        self, mock_origin: MockVault, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def reshape(method: str, response: dict[str, Any]) -> None:
            if method == "GET":
                response.pop("labels")

        _reshape_answers(monkeypatch, reshape)
        origin, share_id, _ = parse_link(_share(mock_origin))

        with pytest.raises(VaultRedeemError) as exc:
            fetch_share_meta(origin, share_id)
        assert exc.value.reason == "bad_response"

    @pytest.mark.parametrize("payload", [b"<html>gateway</html>", b"[1, 2]"])
    def test_a_body_that_is_not_a_json_object_is_one_bad_response(
        self, mock_origin: MockVault, monkeypatch: pytest.MonkeyPatch, payload: bytes
    ) -> None:
        class _Answered:
            def read(self) -> bytes:
                return payload

            def __enter__(self) -> _Answered:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        link = _share(mock_origin)
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout: _Answered(),  # noqa: ARG005
        )
        with pytest.raises(VaultRedeemError) as exc:
            redeem_link(link)
        assert exc.value.reason == "bad_response"

    @pytest.mark.parametrize(
        "link",
        [
            "not a link",
            "https://vault.example/s/abc#k1.AAAA",
            "https://vault.example/s/" + "0" * 32,  # no fragment
        ],
    )
    def test_malformed_links_are_refused(self, link: str) -> None:
        with pytest.raises(VaultRedeemError) as exc:
            redeem_link(link)
        assert exc.value.reason == "bad_link"


def _other_fragment_key() -> str:
    return "k1." + base64.urlsafe_b64encode(b"\x02" * 32).rstrip(b"=").decode()


class TestFragmentHygiene:
    def test_the_fragment_never_reaches_the_server(
        self, mock_origin: MockVault
    ) -> None:
        link = _share(mock_origin)
        redeem_link(link)
        fragment = link[link.index("#") + 1 :]
        key_b64 = base64.b64encode(parse_link(link)[2]).decode()
        for exchange in mock_origin.requests:
            haystacks = [
                exchange["path"],
                json.dumps(exchange["headers"]),
                json.dumps(exchange["body"], default=str) if exchange["body"] else "",
            ]
            for hay in haystacks:
                assert fragment not in hay, exchange["path"]
                assert key_b64 not in hay, exchange["path"]

    def test_the_user_agent_obligation_is_honored(self, mock_origin: MockVault) -> None:
        link = _share(mock_origin)
        redeem_link(link)
        agents = {e["headers"].get("user-agent") for e in mock_origin.requests}
        assert agents == {f"functualize/{__version__}"}


class TestMockConformance:
    """The double is load-bearing for every test above; hold it to v1."""

    def _post(self, origin: str, body: dict[str, Any]) -> tuple[int, dict]:
        req = urllib.request.Request(
            origin + "/api/shares",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "user-agent": "conformance-check/1",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_labels_must_mirror_the_envelope(self, mock_origin: MockVault) -> None:
        link = _share(mock_origin)
        share_id = parse_link(link)[1]
        envelope = mock_origin.shares[share_id]["envelope"]
        status, payload = self._post(
            mock_origin.origin,
            {
                "envelope": envelope,
                "labels": ["other"],
                "share_id": "a" * 32,
            },
        )
        assert status == 400
        assert payload == {"error": {"code": "labels_mismatch"}}

    def test_share_id_collisions_are_a_conflict(self, mock_origin: MockVault) -> None:
        link = _share(mock_origin)
        share_id = parse_link(link)[1]
        envelope = mock_origin.shares[share_id]["envelope"]
        status, payload = self._post(
            mock_origin.origin,
            {
                "envelope": envelope,
                "labels": ["demo"],
                "share_id": share_id,
            },
        )
        assert status == 409
        assert payload == {"error": {"code": "share_id_conflict"}}

    def test_the_default_origin_is_the_public_vault(self) -> None:
        assert DEFAULT_ORIGIN == ("https://funccloud-vault.raicing-ai.workers.dev")
