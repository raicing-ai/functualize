"""A contracts-v1 vault origin, in-process, for tests.

Implements exactly the frozen wire API (funccloud
``.spec/features/vault-redeem-journey/contracts.md``, v1): create / meta /
redeem / ciphertext / health, the error-body shape, the caps, the
client-generated 32-hex share ids, atomic redemption, and 410 semantics.
Every CLI and client test in this tree runs against this server rather than
the network — the live origin is a separate, opt-in tier
(``test_live.py``).

It is a *double*, not a mirror of the Worker's implementation: state is a
dict guarded by one lock, expiry is ``now()`` vs a stored epoch, and
``now``/``corrupt_next_envelope`` exist as seams for the tests that need to
travel in time or receive a tampered bundle. Its conformance to the
contract is itself tested (``TestMockConformance`` in ``test_client.py``),
because every other test in the chain trusts it.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_SHARE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_MAX_ENVELOPE_BYTES = 256 * 1024


class MockVault:
    """The server plus its in-memory store and a request tape.

    ``requests`` records every exchange as
    ``{"method", "path", "headers", "body"}`` — the tape the fragment-
    hygiene assertions read. Nothing is ever logged elsewhere.
    """

    def __init__(self) -> None:
        self.shares: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, str] = {}  # sha256(token) -> share_id
        self.requests: list[dict[str, Any]] = []
        self.now: Callable[[], float] = time.time
        self.corrupt_next_envelope = False
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ── lifecycle ────────────────────────────────────────────────────────

    @classmethod
    def start(cls) -> MockVault:
        vault = cls()
        vault._server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(vault))
        vault._thread = threading.Thread(
            target=vault._server.serve_forever, daemon=True
        )
        vault._thread.start()
        return vault

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread = None
            self._server = None

    @property
    def origin(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    # ── endpoints ────────────────────────────────────────────────────────

    def _create(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        share_id = body.get("share_id")
        if not isinstance(share_id, str) or not _SHARE_ID_RE.match(share_id):
            return 400, {"error": {"code": "bad_share_id"}}
        envelope = body.get("envelope")
        if not isinstance(envelope, str):
            return 400, {"error": {"code": "bad_envelope"}}
        if len(envelope.encode()) > _MAX_ENVELOPE_BYTES:
            return 400, {"error": {"code": "bad_envelope"}}
        try:
            parsed = json.loads(envelope)
        except json.JSONDecodeError:
            return 400, {"error": {"code": "bad_envelope"}}
        if (
            parsed.get("v") != 1
            or not isinstance(parsed.get("metadata"), dict)
            or not isinstance(parsed.get("items"), list)
        ):
            return 400, {"error": {"code": "bad_envelope"}}

        labels = body.get("labels")
        if (
            not isinstance(labels, list)
            or len(labels) > 8
            or any(not isinstance(x, str) or len(x) > 64 for x in labels)
        ):
            return 400, {"error": {"code": "bad_labels"}}
        if parsed["metadata"].get("labels") != labels:
            return 400, {"error": {"code": "labels_mismatch"}}

        allowed = body.get("redemptions_allowed", 1)
        if not isinstance(allowed, int) or not 1 <= allowed <= 10:
            return 400, {"error": {"code": "bad_redemptions"}}
        hours = body.get("expires_in_hours", 24)
        if not isinstance(hours, int) or not 1 <= hours <= 168:
            return 400, {"error": {"code": "bad_expiry"}}

        with self._lock:
            if share_id in self.shares:
                return 409, {"error": {"code": "share_id_conflict"}}
            self.shares[share_id] = {
                "envelope": envelope,
                "labels": list(labels),
                "redemptions_allowed": allowed,
                "redemptions_left": allowed,
                "created_at": int(self.now()),
                "expires_at": int(self.now() + hours * 3600),
            }
        return 201, {
            "share_id": share_id,
            "expires_at": self.shares[share_id]["expires_at"],
            "redemptions_allowed": allowed,
        }

    def _state(self, share_id: str) -> dict[str, Any] | None | str:
        """The share row, ``None`` when unknown, ``"gone"`` when spent/expired."""
        with self._lock:
            row = self.shares.get(share_id)
            if row is None:
                return None
            if row["redemptions_left"] <= 0 or row["expires_at"] <= self.now():
                return "gone"
            return row

    def _meta(self, share_id: str) -> tuple[int, dict[str, Any]]:
        state = self._state(share_id)
        if state is None:
            return 404, {"error": {"code": "not_found"}}
        if state == "gone":
            return 410, {"error": {"code": "gone"}}
        return 200, {
            "labels": list(state["labels"]),
            "redemptions_left": state["redemptions_left"],
            "redemptions_total": state["redemptions_allowed"],
            "expires_at": state["expires_at"],
            "created_at": state["created_at"],
        }

    def _redeem(self, share_id: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            row = self.shares.get(share_id)
            if row is None:
                return 404, {"error": {"code": "not_found"}}
            if row["redemptions_left"] <= 0 or row["expires_at"] <= self.now():
                return 410, {"error": {"code": "gone"}}
            # The atomic claim: exactly N winners for N allowed redemptions,
            # under any concurrency (the live server does this with a CAS
            # UPDATE; a lock is the same guarantee here).
            row["redemptions_left"] -= 1
            envelope = row["envelope"]
            if self.corrupt_next_envelope:
                self.corrupt_next_envelope = False
                parsed = json.loads(envelope)
                parsed["items"][0]["ct"] = parsed["items"][0]["ct"][:-4] + "AAAA"
                envelope = json.dumps(parsed)
            token = secrets.token_hex(32)
            self.tokens[hashlib.sha256(token.encode()).hexdigest()] = share_id
        return 200, {"redemption_token": token, "envelope": envelope}

    def _ciphertext(
        self, share_id: str, auth: str | None
    ) -> tuple[int, dict[str, Any]]:
        token = auth[7:] if auth and auth.startswith("Bearer ") else None
        digest = hashlib.sha256(token.encode()).hexdigest() if token else None
        with self._lock:
            row = self.shares.get(share_id)
            if row is None:
                return 404, {"error": {"code": "not_found"}}
            if digest is None or self.tokens.get(digest) != share_id:
                return 401, {"error": {"code": "unauthorized"}}
            return 200, {"envelope": row["envelope"], "expires_at": row["expires_at"]}


def _make_handler(vault: MockVault) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass  # the tape below is the only log a test may read

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _tape(self, body: Any) -> None:
            vault.requests.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                }
            )

        def _read_body(self) -> Any:
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                return json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return {"__unparsable__": True}

        def do_POST(self) -> None:  # noqa: N802
            body = self._read_body()
            self._tape(body)
            if self.path == "/api/shares":
                if not isinstance(body, dict):
                    status, payload = 400, {"error": {"code": "bad_json"}}
                else:
                    status, payload = vault._create(body)
                self._send(status, payload)
                return
            match = re.match(r"^/api/shares/([0-9a-f]{32})/redeem$", self.path)
            if match:
                status, payload = vault._redeem(match.group(1))
                self._send(status, payload)
                return
            self._send(404, {"error": {"code": "not_found"}})

        def do_GET(self) -> None:  # noqa: N802
            self._tape(None)
            if self.path == "/health":
                self._send(200, {"ok": True, "service": "funccloud-vault"})
                return
            match = re.match(
                r"^/api/shares/([0-9a-f]{32})/(meta|ciphertext)$", self.path
            )
            if match:
                share_id, verb = match.groups()
                if verb == "meta":
                    status, payload = vault._meta(share_id)
                else:
                    status, payload = vault._ciphertext(
                        share_id, self.headers.get("authorization")
                    )
                self._send(status, payload)
                return
            # The static shell is deliberately not served: only the JSON API
            # is contractual, and no client of this module fetches markup.
            self._send(404, {"error": {"code": "not_found"}})

        def do_PUT(self) -> None:  # noqa: N802
            self._tape(self._read_body())
            self._send(405, {"error": {"code": "method_not_allowed"}})

    return Handler
