"""Remote vault sharing — the vendored FuncCloud Vault client (EnvelopeV1).

``func vault share`` and ``func vault redeem`` are this module's two users,
but the behavior lives here rather than in the CLI, per the ``app/vault.py``
pattern: an embedding application can hand a working environment to another
machine with the same calls and no CLI present.

Provenance, and the one rule that follows from it
-------------------------------------------------
The crypto half is vendored from the FuncCloud reference implementation
(``packages/vault-crypto/py/envelope.py`` in the funccloud repo) and must
stay behavior-faithful to it. The cross-language vector file
``tests/vault_remote/vectors.json`` is copied **verbatim** from there and is
the contract between this port, the reference Python and the TypeScript
implementation. A change to sealing, AAD, canonical JSON or key strings here
is a protocol break even when every local test stays green — the frozen
contracts (funccloud ``.spec/features/vault-redeem-journey/contracts.md``,
v1, 2026-09-25) re-open before such a change can land.

No new dependencies follow the port in: AES-GCM / P-256 / HKDF are native to
``cryptography>=42``, which is already core (ADR-016), and the transport is
stdlib ``urllib``. This module imports nothing else internal, so no edge is
added to the layer graph.

Fragment discipline
-------------------
The key fragment (``#k1.…``) is parsed from the link, held in memory, and
never appears in any request, header, or log this module produces — only the
share path is ever sent. Tests assert this against the transport recording,
not the code's good intentions.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

__all__ = [
    "AuthenticationFailed",
    "DEFAULT_ORIGIN",
    "RedeemedBundle",
    "ShareMeta",
    "ShareReport",
    "VaultRedeemError",
    "canonical",
    "create_share",
    "decode_fragment_key",
    "decode_master_key",
    "ec_key_from_jwk",
    "ec_scalar_to_pub_point",
    "encode_fragment_key",
    "encode_master_key",
    "fetch_share_meta",
    "new_key",
    "open_envelope",
    "parse_expiry",
    "parse_link",
    "redeem_link",
    "resolve_origin",
    "seal_envelope",
    "share",
    "unwrap_cek",
    "wrap_cek_for",
]

#: The public FuncCloud vault. Any host implementing contracts v1 is a valid
#: origin; this is only the default the CLI falls back to.
DEFAULT_ORIGIN = "https://funccloud-vault.raicing-ai.workers.dev"

#: Wire caps frozen in contracts v1. Enforced here so a doomed request never
#: leaves the machine — same reasons as validating a vault path before
#: prompting for the value.
_MAX_REDEMPTIONS = 10
_MAX_EXPIRY_HOURS = 168
_MAX_LABELS = 8
_MAX_LABEL_CHARS = 64
_MAX_ENVELOPE_BYTES = 256 * 1024

_LINK_RE = re.compile(
    r"^(https?://[^/?#]+)/s/([0-9a-f]{32})(?:#(k[12]\.[A-Za-z0-9_-]+))?$"
)


class AuthenticationFailed(Exception):  # noqa: N818 — the reference
    # implementations (funccloud py + ts) raise exactly this name; the
    # vectors suite and the frozen contracts treat it as public surface.
    """Single crypto failure class — no format-vs-key oracles.

    Every tamper/expiry/label/name/kind/mode/version/wrong-key/wrong-
    recipient outcome raises this, and nothing distinguishes them. The
    message is for humans reading tests; callers must not branch on it.
    """


class VaultRedeemError(RuntimeError):
    """One client error, with a stable ``reason`` a surface can classify.

    Carries the wire's own error codes (``gone``, ``not_found``,
    ``rate_limited``, …) when the server answered, ``unreachable`` when it
    did not, and client-side refusal codes (``bad_link``, ``bad_origin``,
    ``no_items`` …) when the request was stopped before leaving. The message
    is safe to print: it names ids and reasons, never values or key
    material.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# ── canonical JSON ────────────────────────────────────────────────────────


def canonical(value: Any) -> str:
    """The AAD serialization: sorted keys, no whitespace, no floats/nulls.

    Object keys are format-defined ASCII in every envelope this ships, so
    the JS/Python sort-order divergence over non-BMP keys cannot arise; a
    ``canonical`` that accepted a float or ``None`` would change the AAD
    bytes, so those raise instead.
    """
    if value is None:
        raise ValueError("canonical: nulls are forbidden")
    if isinstance(value, bool):  # before the int check
        return "true" if value else "false"
    if isinstance(value, int):
        return json.dumps(value)
    if isinstance(value, float):
        raise ValueError("canonical: non-integer numbers are forbidden")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise ValueError("canonical: object keys must be strings")
        keys = sorted(value.keys())
        return (
            "{"
            + ",".join(
                json.dumps(k, ensure_ascii=False) + ":" + canonical(value[k])
                for k in keys
            )
            + "}"
        )
    raise ValueError(f"canonical: unsupported type {type(value)!r}")


# ── AEAD ──────────────────────────────────────────────────────────────────


def _aead_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: str) -> bytes:
    return AESGCM(key).encrypt(nonce, plaintext, aad.encode("utf-8"))


def _aead_decrypt(key: bytes, nonce: bytes, ct_and_tag: bytes, aad: str) -> bytes:
    if len(ct_and_tag) < 16:
        raise AuthenticationFailed("truncated")
    try:
        return AESGCM(key).decrypt(nonce, ct_and_tag, aad.encode("utf-8"))
    except Exception:
        raise AuthenticationFailed("aad-or-key mismatch") from None


def _item_aad(header: dict[str, Any], item: dict[str, Any]) -> str:
    return canonical(
        {"envelope": header, "item": {"name": item["name"], "kind": item["kind"]}}
    )


# ── envelope ──────────────────────────────────────────────────────────────


def seal_envelope(
    mode: str,
    metadata: dict[str, Any],
    items: list[dict[str, Any]],
    key: bytes,
    nonces: list[bytes] | None = None,
) -> dict[str, Any]:
    """Encrypt each item under AES-256-GCM with its name/kind in the AAD."""
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    header = {"v": 1, "mode": mode, "metadata": metadata}
    out_items = []
    for i, item in enumerate(items):
        nonce = nonces[i] if nonces else os.urandom(12)
        ct = _aead_encrypt(
            key, nonce, item["value"].encode("utf-8"), _item_aad(header, item)
        )
        out_items.append(
            {
                "name": item["name"],
                "kind": item["kind"],
                "nonce": base64.b64encode(nonce).decode(),
                "ct": base64.b64encode(ct).decode(),
            }
        )
    return {"v": 1, "mode": mode, "metadata": metadata, "items": out_items}


def open_envelope(envelope: dict[str, Any], key: bytes) -> list[dict[str, str]]:
    """Decrypt, or raise :class:`AuthenticationFailed` — nothing between."""
    if envelope.get("v") != 1:
        raise AuthenticationFailed("unsupported envelope version")
    header = {
        "v": envelope["v"],
        "mode": envelope["mode"],
        "metadata": envelope["metadata"],
    }
    out = []
    for item in envelope["items"]:
        value = _aead_decrypt(
            key,
            base64.b64decode(item["nonce"]),
            base64.b64decode(item["ct"]),
            _item_aad(header, item),
        )
        out.append(
            {"name": item["name"], "kind": item["kind"], "value": value.decode()}
        )
    return out


# ── recipient wrapping (vectored; used by later slices, not this flow) ────

_HKDF_INFO = b"funccloud-vault/recipient/v1"


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _point_to_pub(point_b64: str) -> ec.EllipticCurvePublicKey:
    return ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), base64.b64decode(point_b64)
    )


def _pub_to_point(pub: ec.EllipticCurvePublicKey) -> str:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return _b64e(pub.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))


def _derive_kek(
    priv: ec.EllipticCurvePrivateKey, peer_point_b64: str, salt: bytes
) -> bytes:
    shared = priv.exchange(ec.ECDH(), _point_to_pub(peer_point_b64))
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=salt, info=_HKDF_INFO
    ).derive(shared)


def wrap_cek_for(
    cek: bytes,
    recipient_pub_b64: str,
    recipient_kid: str,
    salt: bytes | None = None,
    nonce: bytes | None = None,
) -> dict[str, str]:
    """Wrap the CEK for one recipient via ECDH P-256 + HKDF-SHA256."""
    if len(cek) != 32:
        raise ValueError("cek must be 32 bytes")
    epk = ec.generate_private_key(ec.SECP256R1())
    salt = salt if salt is not None else os.urandom(32)
    nonce = nonce if nonce is not None else os.urandom(12)
    kek = _derive_kek(epk, recipient_pub_b64, salt)
    ct = _aead_encrypt(kek, nonce, cek, canonical({"recipient_kid": recipient_kid}))
    return {
        "recipient_kid": recipient_kid,
        "epk": _pub_to_point(epk.public_key()),
        "salt": _b64e(salt),
        "nonce": _b64e(nonce),
        "ct": _b64e(ct),
    }


def unwrap_cek(
    wrap: dict[str, Any], recipient_priv: ec.EllipticCurvePrivateKey
) -> bytes:
    kek = _derive_kek(recipient_priv, wrap["epk"], base64.b64decode(wrap["salt"]))
    cek = _aead_decrypt(
        kek,
        base64.b64decode(wrap["nonce"]),
        base64.b64decode(wrap["ct"]),
        canonical({"recipient_kid": wrap["recipient_kid"]}),
    )
    if len(cek) != 32:
        raise AuthenticationFailed("bad cek length")
    return cek


def ec_key_from_jwk(jwk: dict[str, str]) -> ec.EllipticCurvePrivateKey:
    """Import the vectors' ``{kty, crv, d, x, y}`` form (base64url ``d``)."""
    d = base64.urlsafe_b64decode(jwk["d"] + "==")
    return ec.derive_private_key(int.from_bytes(d, "big"), ec.SECP256R1())


def ec_scalar_to_pub_point(scalar: int) -> str:
    """A private scalar's public point, uncompressed-base64 (test surface)."""
    return _pub_to_point(ec.derive_private_key(scalar, ec.SECP256R1()).public_key())


# ── key strings ───────────────────────────────────────────────────────────


def encode_fragment_key(key: bytes) -> str:
    return "k1." + base64.urlsafe_b64encode(key).rstrip(b"=").decode()


def decode_fragment_key(s: str) -> bytes:
    if not s.startswith("k1."):
        raise ValueError("bad fragment prefix")
    b = base64.urlsafe_b64decode(s[3:] + "==")
    if len(b) != 32:
        raise ValueError("bad fragment length")
    return b


def encode_master_key(key: bytes) -> str:
    return "m1." + base64.urlsafe_b64encode(key).rstrip(b"=").decode()


def decode_master_key(s: str) -> bytes:
    if not s.startswith("m1."):
        raise ValueError("bad master prefix")
    b = base64.urlsafe_b64decode(s[3:] + "==")
    if len(b) != 32:
        raise ValueError("bad master length")
    return b


def new_key() -> bytes:
    return os.urandom(32)


# ── http half ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RedeemedBundle:
    """What a redeem produced, on the receiver's machine.

    This is the one type here that *does* carry values — that is the point
    of redeeming; the sender-side reports never do. The generated repr
    excludes ``items`` (``field(repr=False)``), so logging or rendering a
    bundle names what it holds without leaking a single value.
    """

    items: list[dict[str, str]] = field(repr=False)
    """``[{name, kind, value}]`` as decrypted locally — never in a repr."""

    labels: list[str]
    expires_at: str
    share_id: str


@dataclass(frozen=True)
class ShareMeta:
    """A preview. Fetched from ``meta``, which never decrements anything."""

    labels: list[str]
    redemptions_left: int
    redemptions_total: int
    expires_at: str
    created_at: str


def _user_agent() -> str:
    # Cloudflare's edge 403s bare ``python-urllib`` user agents (measured,
    # live) — this header is an obligation of contracts v1, not a nicety.
    from functualize import __version__

    return f"functualize/{__version__}"


def _validate_origin(origin: str) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise VaultRedeemError(
            "bad_origin",
            f"{origin!r} is not a vault origin. Expected https://<host>.",
        )
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise VaultRedeemError(
            "bad_origin",
            f"{origin!r} is not a vault origin. It must be a bare origin — "
            f"no path, query, or fragment.",
        )
    return f"{parts.scheme}://{parts.netloc}"


def _request(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """One JSON request → parsed body, or one :class:`VaultRedeemError`.

    Never sees the fragment: callers build ``url`` from the share path only.
    """
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("content-type", "application/json")
    req.add_header("user-agent", _user_agent())
    if token:
        req.add_header("authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
            code = payload.get("error", {}).get("code") or f"http_{exc.code}"
        except Exception:
            code = f"http_{exc.code}"
        raise VaultRedeemError(
            code, f"{method} {url} failed: {exc.code} ({code})."
        ) from None
    except urllib.error.URLError as exc:
        raise VaultRedeemError(
            "unreachable", f"{method} {url} did not answer: {exc.reason}."
        ) from None
    try:
        answered = json.loads(raw)
    except ValueError as exc:
        raise VaultRedeemError(
            "bad_response", f"{method} {url} answered a body that is not JSON."
        ) from exc
    if not isinstance(answered, dict):
        raise VaultRedeemError(
            "bad_response",
            f"{method} {url} answered a body that is not a JSON object.",
        )
    return answered


def parse_link(link: str) -> tuple[str, str, bytes]:
    """Split ``<origin>/s/<id>#k1.…`` into origin, id, and key bytes.

    The fragment becomes key *bytes* here and is never re-serialized into a
    request. A link without a fragment is refused — there is nothing to
    decrypt with, so pretending otherwise would only delay the failure.
    """
    match = _LINK_RE.match(link.strip())
    if not match:
        raise VaultRedeemError(
            "bad_link",
            "not a vault share link. Expected https://<origin>/s/<id>#k1.<key>.",
        )
    origin, share_id, fragment = match.groups()
    if not fragment:
        raise VaultRedeemError(
            "bad_link",
            "the link is missing its key fragment (#k1.…), so its bundle "
            "cannot be decrypted. Ask the sender for the complete link.",
        )
    try:
        key = decode_fragment_key(fragment)
    except ValueError as exc:
        raise VaultRedeemError(
            "bad_link", f"the link's key fragment is unusable: {exc}"
        ) from exc
    return _validate_origin(origin), share_id, key


def _iso_now(offset_hours: int = 0) -> str:
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset_hours * 3600)
    )


def create_share(
    origin: str,
    items: list[dict[str, str]],
    *,
    labels: list[str] | None = None,
    redemptions_allowed: int = 1,
    expires_in_hours: int = 24,
    timeout: float = 30.0,
) -> str:
    """Encrypt locally, upload the envelope, return the complete link.

    The share id is generated *here* because the AAD binds it — the server
    assigning its own would change the AAD and make the bundle unopenable.
    The server validates, stores its own expiry gate, and echoes the id,
    which is checked: a server that answers with a different id than the
    one sealed into the envelope is returning a bundle nobody can open.

    Raises :class:`VaultRedeemError` with the wire's own codes; nothing
    about the items or the key appears in the error.
    """
    origin = _validate_origin(origin)
    labels = list(labels or [])
    if not items:
        raise VaultRedeemError("no_items", "nothing to share — no items were given.")
    if not 1 <= redemptions_allowed <= _MAX_REDEMPTIONS:
        raise VaultRedeemError(
            "bad_redemptions",
            f"redemptions must be 1..{_MAX_REDEMPTIONS}, got {redemptions_allowed}.",
        )
    if not 1 <= expires_in_hours <= _MAX_EXPIRY_HOURS:
        raise VaultRedeemError(
            "bad_expiry",
            f"expiry must be 1..{_MAX_EXPIRY_HOURS} hours, got {expires_in_hours}.",
        )
    if len(labels) > _MAX_LABELS or any(len(x) > _MAX_LABEL_CHARS for x in labels):
        raise VaultRedeemError(
            "bad_labels",
            f"at most {_MAX_LABELS} labels of {_MAX_LABEL_CHARS} characters.",
        )

    key = new_key()
    share_id = secrets.token_hex(16)
    metadata = {
        "labels": labels,
        "created_at": _iso_now(),
        # Client-side advisory copy; the server stores its own expiry gate.
        "expires_at": _iso_now(expires_in_hours),
        "share_id": share_id,
    }
    envelope = seal_envelope("fragment", metadata, items, key)
    envelope_json = json.dumps(envelope)
    if len(envelope_json.encode()) > _MAX_ENVELOPE_BYTES:
        raise VaultRedeemError(
            "envelope_too_large",
            "the sealed envelope exceeds the 256 KiB wire cap; share fewer "
            "or smaller items.",
        )

    response = _request(
        "POST",
        origin + "/api/shares",
        {
            "envelope": envelope_json,
            "labels": labels,
            "redemptions_allowed": redemptions_allowed,
            "expires_in_hours": expires_in_hours,
            "share_id": share_id,
        },
        timeout=timeout,
    )
    if response.get("share_id") != share_id:
        raise VaultRedeemError(
            "server_mismatch",
            "the server answered with a different share id than the one "
            "sealed into the envelope; the bundle could not be opened by "
            "this link.",
        )
    return f"{origin}/s/{share_id}#{encode_fragment_key(key)}"


def fetch_share_meta(origin: str, share_id: str, *, timeout: float = 30.0) -> ShareMeta:
    """Preview a share. ``meta`` never burns a redemption (contracts v1)."""
    origin = _validate_origin(origin)
    response = _request("GET", f"{origin}/api/shares/{share_id}/meta", timeout=timeout)
    try:
        labels = list(response["labels"])
        redemptions_left = int(response["redemptions_left"])
        redemptions_total = int(response["redemptions_total"])
        expires_at = str(response["expires_at"])
        created_at = str(response["created_at"])
    except (KeyError, TypeError, ValueError, AttributeError):
        raise VaultRedeemError(
            "bad_response",
            "the server's meta answer did not contain the expected fields.",
        ) from None
    return ShareMeta(
        labels=labels,
        redemptions_left=redemptions_left,
        redemptions_total=redemptions_total,
        expires_at=expires_at,
        created_at=created_at,
    )


def redeem_link(link: str, *, timeout: float = 30.0) -> RedeemedBundle:
    """Claim one redemption server-side (atomic) and decrypt locally.

    Every failure — unreachable, unknown, gone, wrong link, tampered or
    unopenable envelope — is one :class:`VaultRedeemError`. The crypto
    layer's own indistinguishable class is preserved underneath: an
    ``open_failed`` never says whether the key, the ciphertext, or a
    metadata field was what failed.
    """
    origin, share_id, key = parse_link(link)
    response = _request(
        "POST", f"{origin}/api/shares/{share_id}/redeem", timeout=timeout
    )
    try:
        envelope = json.loads(response["envelope"])
        if not isinstance(envelope, dict):
            raise TypeError("the envelope is not a JSON object")
        metadata = envelope.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError("the envelope's metadata is not a JSON object")
        if metadata.get("share_id") != share_id:
            raise VaultRedeemError(
                "server_mismatch",
                "the envelope's share_id does not match the link — the server "
                "returned the wrong bundle, and it was discarded unopened.",
            )
        try:
            items = open_envelope(envelope, key)
        except (
            AuthenticationFailed,
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
        ):
            raise VaultRedeemError(
                "open_failed",
                "the bundle did not authenticate against this link's key. "
                "Either the link is wrong, the envelope was altered in "
                "transit, or its metadata changed — nothing was decrypted.",
            ) from None
        labels = list(metadata.get("labels", []))
        expires_at = str(metadata.get("expires_at", ""))
    except VaultRedeemError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError):
        raise VaultRedeemError(
            "bad_response",
            "the server's redeem answer did not contain a parsable envelope.",
        ) from None
    return RedeemedBundle(
        items=items,
        labels=labels,
        expires_at=expires_at,
        share_id=share_id,
    )


# ── origin and expiry; the one-call share ─────────────────────────────────
#
# Everything above is the wire client and everything here is still wire-level:
# origin resolution, the expiry grammar, and `share` (seal + create in one
# call). What a share *contains* and what a redeemed bundle *becomes* is local
# policy, and lives in `functualize.app.vault_handoff` — this module never
# touches the local store.


def resolve_origin(explicit: str | None = None) -> str:
    """``--origin`` > ``$FUNC_VAULT_ORIGIN`` > the public FuncCloud vault.

    A config-file link (``vault.remote_origin``) belongs in this chain once
    the config surface grows a non-job section to put it in; inventing a
    key nothing reads would be structure, not configuration.
    """
    if explicit:
        return _validate_origin(explicit)
    from_env = os.environ.get("FUNC_VAULT_ORIGIN")
    if from_env:
        return _validate_origin(from_env)
    return DEFAULT_ORIGIN


_EXPIRY_RE = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"": 3600, "h": 3600, "m": 60, "s": 1, "d": 86400}


def parse_expiry(text: str) -> int:
    """``1h`` / ``90m`` / ``2d`` → whole hours within the frozen 1..168 cap.

    Sub-hour windows round *down* to zero and are refused — a share that
    expires before its link can be delivered is a footgun, not a feature.
    """
    match = _EXPIRY_RE.match(text)
    if not match:
        raise VaultRedeemError(
            "bad_expiry",
            f"{text!r} is not an expiry. Expected e.g. '1h', '90m', '2d'.",
        )
    amount, unit = match.groups()
    hours = int(amount) * _UNIT_SECONDS[unit.lower()] // 3600
    if not 1 <= hours <= _MAX_EXPIRY_HOURS:
        raise VaultRedeemError(
            "bad_expiry",
            f"{text!r} is outside the 1..{_MAX_EXPIRY_HOURS} hour window.",
        )
    return hours


@dataclass(frozen=True)
class ShareReport:
    """What ``share`` produced. Metadata only — the link is the deliverable,
    and it is the *only* place the fragment ever exists outside memory."""

    link: str
    share_id: str
    origin: str
    labels: list[str]
    redemptions_allowed: int
    expires_at: str


def share(
    items: list[dict[str, str]],
    *,
    labels: list[str] | None = None,
    redemptions: int = 1,
    expires_in_hours: int = 24,
    origin: str | None = None,
    timeout: float = 30.0,
) -> ShareReport:
    """Seal, upload, and report — the sender's whole half of the journey."""
    resolved = resolve_origin(origin)
    link = create_share(
        resolved,
        items,
        labels=labels,
        redemptions_allowed=redemptions,
        expires_in_hours=expires_in_hours,
        timeout=timeout,
    )
    _, share_id, _ = parse_link(link)
    return ShareReport(
        link=link,
        share_id=share_id,
        origin=resolved,
        labels=list(labels or []),
        redemptions_allowed=redemptions,
        expires_at=_iso_now(expires_in_hours),
    )
