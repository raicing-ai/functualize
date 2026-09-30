"""The Jev decision provider, and the transport port it sends through.

``JevDecisionProvider.choose`` is one round trip: read the credential, build
the body (``_wire``), send it once through a ``JevTransport``, and map what came
back (``_wire`` again). It never waits and never tries again — a rate limit or
an outage is reported as a ``DecisionUnavailableError`` and the caller decides
what happens next.

The transport is a port so that everything above the socket is tested with a
fake that records what it was sent; ``UrllibTransport`` is the production
implementation, standard library only.

**The credential is read at call time**, through a zero-argument supplier that
defaults to the ``OPENCODE_API_KEY`` environment variable — never at
construction, at import, or from a config file — so nothing this module
constructs holds it, and no ``repr`` can show it.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import Message
from importlib.metadata import version
from typing import Protocol, runtime_checkable

from functualize.plugin import (
    ChoiceRequest,
    DecisionFailure,
    DecisionResult,
    DecisionUnavailableError,
)
from functualize_decision_jev import _wire

__all__ = [
    "JevConfig",
    "JevDecisionProvider",
    "JevTransport",
    "UrllibTransport",
    "WireResponse",
]

_PROVIDER = "jev"
_DISTRIBUTION = "functualize-decision-jev"
_CREDENTIAL_VARIABLE = "OPENCODE_API_KEY"


@runtime_checkable
class JevTransport(Protocol):
    """Sends one request and returns the response, whatever its status.

    Raises only for a transport failure — no response at all — and then only
    ``DecisionUnavailableError`` with ``kind=UNREACHABLE``.
    """

    def post(
        self, url: str, body: bytes, headers: Mapping[str, str], timeout: float
    ) -> WireResponse: ...


@dataclass(frozen=True)
class WireResponse:
    """One HTTP response, decoded."""

    status: int
    body: str
    headers: Mapping[str, str]  # keys lower-cased


class UrllibTransport:
    """The production ``JevTransport``: one ``POST`` through ``urllib.request``.

    A ``4xx``/``5xx`` is a response, not a failure, so ``HTTPError`` is read
    rather than raised: what it means is ``_wire.failure_for``'s decision.
    """

    def post(
        self, url: str, body: bytes, headers: Mapping[str, str], timeout: float
    ) -> WireResponse:
        request = urllib.request.Request(
            url, data=body, headers=dict(headers), method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return _response(response.status, response.read(), response.headers)
        except urllib.error.HTTPError as error:
            return _response(error.code, error.read(), error.headers)
        # URLError and TimeoutError are both OSError; HTTPException is the
        # connection dropping mid-response (IncompleteRead, BadStatusLine),
        # which is equally "no usable response" and would otherwise escape the
        # port as something other than a DecisionUnavailableError.
        except (OSError, http.client.HTTPException) as error:
            raise DecisionUnavailableError(
                kind=DecisionFailure.UNREACHABLE,
                provider=_PROVIDER,
                status=None,
                detail=str(error),
            ) from error


@dataclass(frozen=True)
class JevConfig:
    """The provider's settings, resolved from config section ``[jev]``."""

    model: str = "jev-1.13-free"
    endpoint: str = "https://opencode.ai/zen/v1/systemone"
    timeout_seconds: float = 30.0


class JevDecisionProvider:
    """A ``DecisionProvider`` that proposes a choice through Jev."""

    name: str = _PROVIDER

    def __init__(
        self,
        config: JevConfig = JevConfig(),  # noqa: B008 — frozen, so one shared default is safe
        *,
        transport: JevTransport | None = None,
        credential: Callable[[], str | None] | None = None,
    ) -> None:
        self._config = config
        self._transport = transport if transport is not None else UrllibTransport()
        # A supplier, not a value: it is called inside `choose`, so the key is
        # read at call time and never held by this object.
        self._credential = credential if credential is not None else _from_environment
        self._user_agent = f"{_DISTRIBUTION}/{version(_DISTRIBUTION)}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}(config={self._config!r})"

    def choose(self, request: ChoiceRequest) -> DecisionResult[str]:
        key = self._credential()
        if not key:
            raise DecisionUnavailableError(
                kind=DecisionFailure.NOT_CONFIGURED,
                provider=_PROVIDER,
                detail=f"{_CREDENTIAL_VARIABLE} is not set",
            )
        config = self._config
        model = request.model or config.model
        body = json.dumps(_wire.build_request(request, model=config.model)).encode()
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": self._user_agent,
        }

        started = time.monotonic()
        response = self._transport.post(
            config.endpoint, body, headers, config.timeout_seconds
        )
        elapsed = time.monotonic() - started

        if response.status != 200:
            raise _wire.failure_for(response.status, response.body, response.headers)
        try:
            payload = json.loads(response.body)
        except ValueError as error:
            raise DecisionUnavailableError(
                kind=DecisionFailure.MALFORMED,
                provider=_PROVIDER,
                status=200,
                detail=f"body is not JSON: {error}",
            ) from error
        return _wire.parse_choice(
            payload, request, requested_model=model, latency_seconds=elapsed
        )


def _from_environment() -> str | None:
    return os.environ.get(_CREDENTIAL_VARIABLE)


def _response(
    status: int, raw: bytes, headers: Message | Mapping[str, str] | None
) -> WireResponse:
    return WireResponse(
        status=status,
        body=raw.decode("utf-8", errors="replace"),
        headers={name.lower(): value for name, value in (headers or {}).items()},
    )
