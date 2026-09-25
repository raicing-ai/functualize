"""The wire, through the standard library and nothing else.

No new dependency, no cassette, no recorded fixture: every number this
directory records came from a request made while the run was happening, and a
run with no credential skips rather than replaying a file.

The `User-Agent` default is explicit and is **the** trap this module exists for.
The service answers `HTTP 403 error code: 1010` to the string the standard
library sends by default (`Python-urllib/3.x`), on both the decision endpoint
and the catalog — measured, row E. A probe that left the header unset would
measure the block rather than the model.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

import pytest

#: The decision endpoint and the catalog beside it.
ENDPOINT: Final[str] = "https://opencode.ai/zen/v1/systemone"
CATALOG: Final[str] = "https://opencode.ai/zen/v1/models"

#: The model this probe measures. The paid sibling is refused (row E, 402).
MODEL: Final[str] = "jev-1.13-free"
PAID_MODEL: Final[str] = "jev-1.13"

#: Any string except the standard library's default will do; this one says who
#: is asking. `STDLIB_USER_AGENT` is the default that gets refused.
USER_AGENT: Final[str] = "functualize-jev-probe/0.1"
STDLIB_USER_AGENT: Final[str] = "Python-urllib/3"

#: A decision took 0.60–0.98 s in the measurements behind the reference; this is
#: a ceiling for a stalled connection, not a budget.
TIMEOUT: Final[float] = 30.0

#: The free model answers a burst of requests with `429`, so the client waits it
#: out: this run measures a contract, and an account's burst budget is neither
#: the contract nor something the probe may raise by spending money. What it met
#: is recorded (`throttled()`, row F) rather than swallowed.
RETRY_STATUSES: Final[frozenset[int]] = frozenset({429, 503})
RETRY_ATTEMPTS: Final[int] = 4
RETRY_BACKOFF: Final[float] = 5.0
RETRY_CAP: Final[float] = 20.0

#: Round trips made, and every load refusal met, in order — the load row F
#: reports. A list rather than a global because `global` in a module this small
#: buys nothing but a rebinding hazard.
_LOAD: Final[list[int]] = [0]
_THROTTLES: Final[list[Throttle]] = []


@dataclass(frozen=True, slots=True)
class Throttle:
    """A refusal for load: the status, the body, and what happened next.

    `retried` is False when the service asked for longer than this run may
    wait, which is the normal case for a budget that has run out for the day:
    the refusal is then recorded and the run moves on rather than sleeping.
    """

    status: int
    body: str
    seconds_waited: float
    retried: bool


def load() -> int:
    """How many round trips this run has made, retries included."""
    return _LOAD[0]


def throttled() -> tuple[Throttle, ...]:
    """Every load refusal the run met, oldest first."""
    return tuple(_THROTTLES)


@dataclass(frozen=True, slots=True)
class Response:
    """One round trip: what came back, and how long it took to come back.

    `headers` is here for one value: the `Retry-After` the free tier sends with
    a `429`, which is what a rate-limited item's skip reason quotes.
    """

    status: int
    text: str
    seconds: float
    payload: dict[str, Any] | None
    headers: Mapping[str, str]

    @property
    def ok(self) -> bool:
        return self.status == 200

    def summary(self, *, limit: int = 300) -> str:
        """`status + body`, for a matrix cell and for a failure message."""
        body = self.text if len(self.text) <= limit else f"{self.text[:limit]}…"
        return f"HTTP {self.status} · {body}"


def credential() -> str:
    """The API key, from the environment only, never printed and never logged."""
    return os.environ["OPENCODE_API_KEY"]


def post(
    payload: Mapping[str, Any],
    *,
    token: str | None = None,
    user_agent: str | None = USER_AGENT,
    endpoint: str = ENDPOINT,
) -> Response:
    """`payload` as JSON to the decision endpoint. Never raises on a status."""
    return _round_trip(
        endpoint,
        method="POST",
        body=json.dumps(payload).encode(),
        token=credential() if token is None else token,
        user_agent=user_agent,
    )


def catalog(
    *, user_agent: str | None = USER_AGENT, endpoint: str = CATALOG
) -> Response:
    """The model catalog, whose User-Agent gate is the same one (row E)."""
    return _round_trip(endpoint, method="GET", user_agent=user_agent, token=None)


def noul(instructions: str) -> dict[str, Any]:
    """A probability question: one number in [0, 1], and no verdict (row G)."""
    return {"type": "noul", "instructions": instructions}


def choice(instructions: str, criteria: Mapping[str, str]) -> dict[str, Any]:
    """A single-label question: `criteria` maps option → what it means."""
    return {"type": "choice", "instructions": instructions, "criteria": dict(criteria)}


def score(instructions: str, criteria: Sequence[str]) -> dict[str, Any]:
    """A graded question: `criteria` is the legend, index → meaning."""
    return {"type": "score", "instructions": instructions, "criteria": list(criteria)}


def ask(
    questions: Mapping[str, Mapping[str, Any]],
    *,
    state: str,
    model: str = MODEL,
    token: str | None = None,
    user_agent: str | None = USER_AGENT,
) -> Response:
    """One request carrying every question, in the shape the service accepts."""
    return post(
        {
            "model": model,
            "state": state,
            "questions": {k: dict(v) for k, v in questions.items()},
        },
        token=token,
        user_agent=user_agent,
    )


def ask_one(
    question: Mapping[str, Any],
    *,
    state: str,
    question_id: str = "q",
    model: str = MODEL,
) -> Response:
    """One request, one question — the shape the stability rows are measured in."""
    return ask({question_id: question}, state=state, model=model)


def skip_if_rate_limited(response: Response, cell: str) -> None:
    """Skip `cell` when the free tier refused this request for load.

    A third reason beside the two the brief fixes, added because a run met it:
    the model's free tier answers a burst with `429` and a `Retry-After` that can
    be hours. That budget belongs to the account and not to the contract, so it
    is neither a measurement nor the caller's bug — the item skips, naming the
    wait the service asked for. Measured and recorded as row F.
    """
    if response.status != 429:
        return
    wait = response.headers.get("retry-after")
    pytest.skip(
        f"{cell}: NOT MEASURED (rate limited) — {response.summary()}"
        f" · the service asked to wait {wait or 'an unspecified number of'} s "
        f"before the next request, after {load()} round "
        f"trip{'' if load() == 1 else 's'} in this run; the free tier's budget "
        "is the account's, so re-run once it clears rather than reading a refusal "
        "as a decision"
    )


def require_ok(response: Response, cell: str = "Jev / System One") -> dict[str, Any]:
    """The parsed body, or an assertion carrying the request's own answer."""
    skip_if_rate_limited(response, cell)
    if not response.ok or response.payload is None:
        raise AssertionError(
            f"expected HTTP 200 with a JSON body; got {response.summary()}"
        )
    return response.payload


def answers(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The `answers` map, keyed by question id."""
    found = payload.get("answers")
    if not isinstance(found, dict) or not found:
        raise AssertionError(f"no `answers` object in {_compact(payload)}")
    return cast("dict[str, dict[str, Any]]", found)


def answer(payload: Mapping[str, Any], question_id: str) -> dict[str, Any]:
    """The single answer for `question_id`, or an assertion naming what came back."""
    found = answers(payload).get(question_id)
    if not isinstance(found, dict):
        raise AssertionError(
            f"no answer for {question_id!r} in {_compact(answers(payload))}"
        )
    return found


def usage(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The one `usage` block that covers every question in the request."""
    found = payload.get("usage")
    if not isinstance(found, dict):
        raise AssertionError(f"no `usage` block in {_compact(payload)}")
    return found


def _compact(value: Any, *, limit: int = 400) -> str:
    """`value` as JSON on one line, clipped — for an assertion message."""
    rendered = json.dumps(value, sort_keys=True)
    return rendered if len(rendered) <= limit else f"{rendered[:limit]}…"


def _round_trip(
    url: str,
    *,
    method: str,
    token: str | None,
    user_agent: str | None,
    body: bytes | None = None,
) -> Response:
    headers: dict[str, str] = {}
    if user_agent is not None:
        headers["User-Agent"] = user_agent
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    started = time.monotonic()
    headers_out: Mapping[str, str] = {}
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        _LOAD[0] += 1
        status, text, retry_after, headers_out = _once(request, url)
        if status not in RETRY_STATUSES or attempt == RETRY_ATTEMPTS:
            break
        waited = (
            retry_after
            if retry_after is not None
            else min(RETRY_BACKOFF * 2 ** (attempt - 1), RETRY_CAP)
        )
        # The service asking for longer than this run may wait means its budget
        # has run out for hours, not for a moment (`Retry-After: 19014` was a
        # real answer). Waiting it out is not a measurement and would leave the
        # run asleep instead of reporting: the refusal is recorded, unretried,
        # and `skip_if_rate_limited` states the wait it asked for.
        retry = waited <= RETRY_CAP
        _THROTTLES.append(
            Throttle(
                status=status,
                body=text.strip(),
                seconds_waited=waited,
                retried=retry,
            )
        )
        if not retry:
            break
        time.sleep(waited)
    return Response(
        status=status,
        text=text,
        seconds=round(time.monotonic() - started, 3),
        payload=_json(text),
        headers=dict(headers_out),
    )


def _once(
    request: urllib.request.Request, url: str
) -> tuple[int, str, float | None, Mapping[str, str]]:
    """One attempt: status, body, `Retry-After`, and the headers behind them."""
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return (
                response.status,
                _decode(response.read()),
                _retry_after(response),
                {key.lower(): value for key, value in response.headers.items()},
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            _decode(error.read()),
            _retry_after(error),
            {key.lower(): value for key, value in (error.headers or {}).items()},
            # lowered once, here and below: `Retry-After` arrives in whatever
            # case the service felt like, and one place to normalise it beats
            # every reader remembering.
        )
    except urllib.error.URLError as error:
        raise AssertionError(f"{url} did not answer: {error.reason}") from error


def _retry_after(response: Any) -> float | None:
    """The service's own waiting time, when it sends a usable one."""
    raw = {key.lower(): value for key, value in response.headers.items()}.get(
        "retry-after"
    )
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def _json(text: str) -> dict[str, Any] | None:
    """The body as an object, or None — a blocked request answers plain text."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
