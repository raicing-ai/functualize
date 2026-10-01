"""The Jev provider and its transport, driven through a recording fake.

Everything above the socket runs against ``FakeTransport``, which records each
request it is handed and answers with a canned ``WireResponse``, so the tests
can say exactly what the provider *sent* — headers, body, how many times —
and not only what it returned. ``UrllibTransport`` is tested with
``urllib.request.urlopen`` replaced, so no test here opens a connection.
"""

from __future__ import annotations

import email.message
import http.client
import io
import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from functualize_decision_jev._provider import (
    JevConfig,
    JevDecisionProvider,
    JevTransport,
    UrllibTransport,
    WireResponse,
)

from functualize.plugin import (
    ChoiceRequest,
    DecisionFailure,
    DecisionProvider,
    DecisionUnavailableError,
)

#: A credential no real account has, so a leak is a string search away.
_SENTINEL = "sk-sentinel-3f9a1c7e-never-print-me"

_REQUEST = ChoiceRequest(
    state="Where is my parcel? It was due on Monday.",
    instructions="Route the ticket to the team that owns it.",
    options={
        "billing": "money",
        "returns": "the customer wants a refund",
        "shipping": "the parcel's journey",
    },
)

#: Row A2's envelope around row A4's field set; the values are illustrative.
_CHOICE_BODY = json.dumps(
    {
        "answers": {
            "decision": {
                "choice": "shipping",
                "confidence": 0.83,
                "probabilities": {"billing": 0.05, "returns": 0.07, "shipping": 0.88},
                "type": "choice",
            }
        },
        "model": "jev-1.13-free",
        "usage": {"input_tokens": 332, "output_tokens": 38},
    }
)


@dataclass
class Sent:
    url: str
    body: bytes
    headers: dict[str, str]
    timeout: float


@dataclass
class FakeTransport:
    """A ``JevTransport`` that records what it was sent and answers one way."""

    response: WireResponse = field(
        default_factory=lambda: WireResponse(status=200, body=_CHOICE_BODY, headers={})
    )
    sent: list[Sent] = field(default_factory=list)

    def post(
        self, url: str, body: bytes, headers: Mapping[str, str], timeout: float
    ) -> WireResponse:
        self.sent.append(Sent(url, body, dict(headers), timeout))
        return self.response


def _provider(
    transport: FakeTransport, key: str | None = _SENTINEL, **config: Any
) -> JevDecisionProvider:
    return JevDecisionProvider(
        JevConfig(**config), transport=transport, credential=lambda: key
    )


@pytest.fixture(autouse=True)
def _never_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-5: no path through the provider waits."""

    def refuse(seconds: float) -> None:
        raise AssertionError(f"the provider slept for {seconds} s")

    monkeypatch.setattr(time, "sleep", refuse)


class TestChoose:
    def test_a_200_becomes_the_proposed_result(self) -> None:
        transport = FakeTransport()

        result = _provider(transport).choose(_REQUEST)

        assert result.value == "shipping"
        assert result.provider == "jev"
        assert result.provenance.requested_model == "jev-1.13-free"
        assert result.provenance.latency_seconds >= 0.0
        assert len(transport.sent) == 1

    def test_it_sends_one_post_to_the_endpoint_with_the_built_body(self) -> None:
        transport = FakeTransport()

        _provider(transport).choose(_REQUEST)

        (sent,) = transport.sent
        assert sent.url == "https://opencode.ai/zen/v1/systemone"
        assert sent.timeout == 30.0
        assert json.loads(sent.body) == {
            "model": "jev-1.13-free",
            "state": _REQUEST.state,
            "questions": {
                "decision": {
                    "type": "choice",
                    "instructions": _REQUEST.instructions,
                    "criteria": dict(_REQUEST.options),
                }
            },
        }

    def test_configuration_reaches_the_request(self) -> None:
        transport = FakeTransport()

        _provider(
            transport,
            model="jev-9",
            endpoint="https://example.invalid/v1",
            timeout_seconds=4.5,
        ).choose(_REQUEST)

        (sent,) = transport.sent
        assert (sent.url, sent.timeout) == ("https://example.invalid/v1", 4.5)
        assert json.loads(sent.body)["model"] == "jev-9"

    def test_a_model_named_on_the_request_is_sent_and_recorded(self) -> None:
        transport = FakeTransport()
        request = ChoiceRequest(
            state="s", instructions="i", options=_REQUEST.options, model="jev-1.13"
        )

        result = _provider(transport).choose(request)

        assert json.loads(transport.sent[0].body)["model"] == "jev-1.13"
        assert result.provenance.requested_model == "jev-1.13"

    def test_the_headers_it_sends(self) -> None:
        """AC-3: a real User-Agent, never empty and never the library default."""
        transport = FakeTransport()

        _provider(transport).choose(_REQUEST)

        headers = transport.sent[0].headers
        agent = headers["User-Agent"]
        assert agent
        assert not agent.startswith("Python-")
        assert agent.startswith("functualize-decision-jev/")
        assert len(agent) > len("functualize-decision-jev/")
        assert headers["Authorization"] == f"Bearer {_SENTINEL}"
        assert headers["Content-Type"] == "application/json"

    def test_one_post_per_choose(self) -> None:
        transport = FakeTransport()
        provider = _provider(transport)

        provider.choose(_REQUEST)
        provider.choose(_REQUEST)

        assert len(transport.sent) == 2

    def test_a_429_is_rate_limited_at_once(self) -> None:
        """AC-5: a rate limit is reported with its wait, not waited out."""
        transport = FakeTransport(
            WireResponse(
                status=429,
                body='{"type":"error","error":{"type":"FreeUsageLimitError",'
                '"message":"Rate limit exceeded. Please try again later."}}',
                headers={"retry-after": "19014"},
            )
        )
        started = time.monotonic()

        with pytest.raises(DecisionUnavailableError) as raised:
            _provider(transport).choose(_REQUEST)

        assert time.monotonic() - started < 1.0
        assert raised.value.kind is DecisionFailure.RATE_LIMITED
        assert raised.value.retry_after == 19014.0
        assert len(transport.sent) == 1

    def test_a_refusal_is_refused_after_one_request(self) -> None:
        """Row E11's body: a refused credential is not tried again."""
        transport = FakeTransport(
            WireResponse(
                status=401,
                body='{"type":"error","error":{"type":"AuthError","message":"Invalid API key."}}',
                headers={},
            )
        )

        with pytest.raises(DecisionUnavailableError) as raised:
            _provider(transport).choose(_REQUEST)

        assert (raised.value.kind, raised.value.status) == (
            DecisionFailure.REFUSED,
            401,
        )
        assert len(transport.sent) == 1

    def test_a_200_that_is_not_json_is_malformed(self) -> None:
        transport = FakeTransport(
            WireResponse(status=200, body="<html>maintenance</html>", headers={})
        )

        with pytest.raises(DecisionUnavailableError) as raised:
            _provider(transport).choose(_REQUEST)

        assert (raised.value.kind, raised.value.status) == (
            DecisionFailure.MALFORMED,
            200,
        )
        assert "not JSON" in raised.value.detail

    def test_a_transport_failure_propagates_as_it_was_raised(self) -> None:
        unreachable = DecisionUnavailableError(
            kind=DecisionFailure.UNREACHABLE, provider="jev", detail="refused"
        )

        class DeadTransport:
            def post(
                self, url: str, body: bytes, headers: Mapping[str, str], timeout: float
            ) -> WireResponse:
                raise unreachable

        provider = JevDecisionProvider(
            transport=DeadTransport(), credential=lambda: _SENTINEL
        )

        with pytest.raises(DecisionUnavailableError) as raised:
            provider.choose(_REQUEST)

        assert raised.value is unreachable


class TestCredential:
    @pytest.mark.parametrize("key", [None, ""], ids=["unset", "empty"])
    def test_no_credential_is_not_configured_and_sends_nothing(
        self, key: str | None
    ) -> None:
        """AC-6: the request is never sent without a key."""
        transport = FakeTransport()

        with pytest.raises(DecisionUnavailableError) as raised:
            _provider(transport, key=key).choose(_REQUEST)

        assert raised.value.kind is DecisionFailure.NOT_CONFIGURED
        assert str(raised.value) == "jev not_configured: OPENCODE_API_KEY is not set"
        assert transport.sent == []

    def test_the_default_supplier_reads_the_environment_at_call_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        transport = FakeTransport()
        provider = JevDecisionProvider(transport=transport)

        with pytest.raises(DecisionUnavailableError):
            provider.choose(_REQUEST)
        monkeypatch.setenv("OPENCODE_API_KEY", _SENTINEL)
        provider.choose(_REQUEST)

        assert transport.sent[0].headers["Authorization"] == f"Bearer {_SENTINEL}"

    @pytest.mark.parametrize(
        "response",
        [
            pytest.param(WireResponse(429, "Rate limit exceeded", {}), id="429"),
            pytest.param(
                WireResponse(
                    401,
                    '{"type":"error","error":{"type":"AuthError","message":"Invalid API key."}}',
                    {},
                ),
                id="E11-401",
            ),
            pytest.param(WireResponse(403, "error code: 1010", {}), id="E12-403"),
            pytest.param(WireResponse(200, "not json", {}), id="200-not-json"),
            pytest.param(
                WireResponse(200, '{"answers": {}, "model": "m"}', {}),
                id="200-malformed",
            ),
        ],
    )
    def test_the_credential_is_in_no_error_and_not_in_the_provider(
        self, response: WireResponse
    ) -> None:
        """AC-6: the key is sent in a header and shown nowhere else."""
        provider = _provider(FakeTransport(response))

        with pytest.raises(DecisionUnavailableError) as raised:
            provider.choose(_REQUEST)

        assert _SENTINEL not in str(raised.value)
        assert _SENTINEL not in repr(raised.value)
        assert _SENTINEL not in repr(provider)

    def test_the_credential_is_not_read_at_construction(self) -> None:
        reads: list[str] = []

        def supplier() -> str:
            reads.append("read")
            return _SENTINEL

        JevDecisionProvider(transport=FakeTransport(), credential=supplier)

        assert reads == []


class TestShape:
    def test_it_is_a_decision_provider_named_jev(self) -> None:
        provider = JevDecisionProvider(transport=FakeTransport())

        assert isinstance(provider, DecisionProvider)
        assert provider.name == "jev"

    def test_the_fake_and_the_real_transport_are_transports(self) -> None:
        assert isinstance(FakeTransport(), JevTransport)
        assert isinstance(UrllibTransport(), JevTransport)

    def test_the_defaults(self) -> None:
        assert JevConfig() == JevConfig(
            model="jev-1.13-free",
            endpoint="https://opencode.ai/zen/v1/systemone",
            timeout_seconds=30.0,
        )


class _FakeResponse(io.BytesIO):
    def __init__(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        super().__init__(body)
        self.status = status
        self.headers = _message(headers)


def _message(headers: dict[str, str]) -> email.message.Message:
    message = email.message.Message()
    for name, value in headers.items():
        message[name] = value
    return message


class TestUrllibTransport:
    """The production transport, with ``urlopen`` replaced — no connection."""

    def _post(self) -> WireResponse:
        return UrllibTransport().post(
            "https://example.invalid/v1",
            b'{"x": 1}',
            {
                "User-Agent": "functualize-decision-jev/0.1.0",
                "Authorization": "Bearer k",
            },
            12.5,
        )

    def test_it_posts_the_body_headers_and_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def urlopen(request: urllib.request.Request, timeout: float) -> Any:
            seen.update(
                method=request.get_method(),
                url=request.full_url,
                data=request.data,
                agent=request.get_header("User-agent"),
                timeout=timeout,
            )
            return _FakeResponse(
                200, b'{"ok": true}', {"Content-Type": "application/json"}
            )

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)

        response = self._post()

        assert seen == {
            "method": "POST",
            "url": "https://example.invalid/v1",
            "data": b'{"x": 1}',
            "agent": "functualize-decision-jev/0.1.0",
            "timeout": 12.5,
        }
        assert response == WireResponse(
            status=200,
            body='{"ok": true}',
            headers={"content-type": "application/json"},
        )

    def test_an_http_error_is_read_as_a_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def urlopen(request: urllib.request.Request, timeout: float) -> Any:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                _message({"Retry-After": "19014"}),
                io.BytesIO("Rate limit exceeded \xff".encode("latin-1")),
            )

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)

        response = self._post()

        assert response.status == 429
        assert response.headers == {"retry-after": "19014"}
        assert response.body == "Rate limit exceeded �"

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(urllib.error.URLError("Name or service not known"), id="url"),
            pytest.param(TimeoutError("timed out"), id="timeout"),
            pytest.param(ConnectionResetError("reset by peer"), id="os"),
            pytest.param(http.client.IncompleteRead(b"par"), id="incomplete-read"),
        ],
    )
    def test_no_response_is_unreachable(
        self, monkeypatch: pytest.MonkeyPatch, failure: Exception
    ) -> None:
        def urlopen(request: urllib.request.Request, timeout: float) -> Any:
            raise failure

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)

        with pytest.raises(DecisionUnavailableError) as raised:
            self._post()

        assert raised.value.kind is DecisionFailure.UNREACHABLE
        assert raised.value.provider == "jev"
        assert raised.value.status is None
        assert raised.value.detail == str(failure)


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(
            WireResponse(
                401, f'{{"error": "bad header Authorization: Bearer {_SENTINEL}"}}', {}
            ),
            id="401-echo",
        ),
        pytest.param(
            WireResponse(
                429, f"Bearer {_SENTINEL} is rate limited", {"retry-after": "5"}
            ),
            id="429-echo",
        ),
        pytest.param(
            WireResponse(
                200,
                json.dumps(
                    {
                        "answers": {
                            "decision": {"type": "choice", "choice": _SENTINEL}
                        },
                        "model": "m",
                    }
                ),
                {},
            ),
            id="200-echo",
        ),
    ],
)
def test_a_response_echoing_the_credential_never_carries_it_into_an_error(
    response: WireResponse,
) -> None:
    """B-4 / AC-6: a hostile or echoing body cannot put the key into the text a
    failed rung records (the rung's detail is ``str(error)``)."""
    with pytest.raises(DecisionUnavailableError) as raised:
        _provider(FakeTransport(response)).choose(_REQUEST)

    assert _SENTINEL not in str(raised.value)
    assert _SENTINEL not in raised.value.detail
    assert _SENTINEL not in repr(raised.value)
