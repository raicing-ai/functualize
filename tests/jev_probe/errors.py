"""Row E — the error taxonomy, verbatim, and what each one means for a caller.

Every case below records the *body the service actually returned*, because an
adapter's failure taxonomy is only as good as its knowledge of which layer
refused it. The cases are grouped by that layer rather than by status code:

- **422** — the request never reached a model: FastAPI/pydantic rejected the
  shape, and `detail` names the exact path (`body, questions, q, choice,
  criteria`) that is wrong. These are the caller's own programming errors and
  a stage-1 adapter should never emit one.
- **400** — the shape was fine; the tagged union's tag was not (`api_usage_error`).
  Also the caller's error.
- **401 / 402 / 400 `server_error`** — auth, funds, and an unavailable model.
  These are operational: a key, a balance, or a model name.
- **403 `error code: 1010`** — the `User-Agent` gate, which is the trap this
  suite exists to record: the standard library's *default* header is refused, so
  a client that never sets one is blocked and reads as a service outage. The
  gate blocks that one string and accepts even the empty string, and it applies
  to the catalog as well as to the decision endpoint — measured on both.

A missing `model` field is worth its own note: it is not a 422. The request
passes validation, reaches the model resolver, and comes back 401 with an
envelope shaped differently from every other error — which is what E17 records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from tests.jev_probe.client import (
    CATALOG,
    ENDPOINT,
    MODEL,
    PAID_MODEL,
    STDLIB_USER_AGENT,
    USER_AGENT,
    Response,
    catalog,
    noul,
    post,
    skip_if_rate_limited,
)
from tests.jev_probe.conftest import require_endpoint, require_env
from tests.jev_probe.report import measured

require_env(
    "Jev / System One",
    "OPENCODE_API_KEY",
    hint="The reference's Provenance section carries the one-line export.",
)
require_endpoint("Jev / System One", ENDPOINT)

CALM: Final[str] = "How likely is it that this customer is calm?"
INTENT: Final[dict[str, str]] = {
    "shipping": "the parcel's journey",
    "billing": "money",
    "returns": "the customer wants a refund",
}
STATE: Final[str] = "Ticket: my parcel is late."

#: The layers a refusal can come from, by status — the taxonomy this row pins.
LAYERS: Final[dict[str, str]] = {
    "400": "tagged union / unavailable model",
    "401": "credential or empty model",
    "402": "funds",
    "403": "`User-Agent` gate",
    "422": "request shape (pydantic, `detail` names the path)",
}

#: The one body every UA-blocked request gets. Plain text, not JSON — an
#: adapter that parses every failure as JSON fails on the failure that matters.
BLOCKED_BODY: Final[str] = "error code: 1010"

#: `None` means "omit the header", which is not the same as "send nothing":
#: `urllib.request` adds its own default and the gate refuses that one.
ABSENT_UA: Final[None] = None


@dataclass(frozen=True, slots=True)
class Case:
    """One refused (or controlled) request and what it must come back with."""

    fact_id: str
    name: str
    expect_status: int
    expect: tuple[str, ...]
    note: str
    payload: dict[str, Any] | None = None
    method: str = "POST"
    token: str | None = None
    user_agent: str | None = USER_AGENT
    endpoint: str = ENDPOINT


VALID: Final[dict[str, Any]] = {
    "model": MODEL,
    "state": STATE,
    "questions": {"q": noul(CALM)},
}

CASES: Final[tuple[Case, ...]] = (
    Case(
        "E0",
        "control: a valid request",
        200,
        ("answers",),
        "every other case is this payload with one thing changed, so a status "
        "below is attributable to that change and not to the probe",
        payload=VALID,
    ),
    Case(
        "E1",
        "`questions` absent",
        422,
        ("Field required", '"questions"'),
        "pydantic rejects it before any model call; `loc` names the body path",
        payload={"model": MODEL, "state": STATE},
    ),
    Case(
        "E2",
        "`questions` empty",
        422,
        ("too_short", "min_length"),
        "at least one question is required; an empty request is a caller bug",
        payload={"model": MODEL, "state": STATE, "questions": {}},
    ),
    Case(
        "E3",
        "question without `type`",
        422,
        ("union_tag_not_found", "discriminator"),
        "the question is a discriminated union; `type` is not optional",
        payload={
            "model": MODEL,
            "state": STATE,
            "questions": {"q": {"instructions": CALM}},
        },
    ),
    Case(
        "E4",
        "unknown `type` tag",
        400,
        ("api_usage_error", "Invalid request."),
        "the tag validated enough to route and was then refused — a different "
        "layer from the 422s, and a different envelope",
        payload={
            "model": MODEL,
            "state": STATE,
            "questions": {"q": {"type": "verdict", "instructions": CALM}},
        },
    ),
    Case(
        "E5",
        "`choice` without `criteria`",
        422,
        ("Field required", "criteria"),
        "the option list is required for `choice`; `loc` carries the tag too",
        payload={
            "model": MODEL,
            "state": STATE,
            "questions": {"q": {"type": "choice", "instructions": CALM}},
        },
    ),
    Case(
        "E6",
        "`choice` with `criteria` as a string",
        422,
        ("dict_type",),
        "`choice.criteria` is an object (option → meaning), not a list or string",
        payload={
            "model": MODEL,
            "state": STATE,
            "questions": {
                "q": {"type": "choice", "instructions": CALM, "criteria": "shipping"}
            },
        },
    ),
    Case(
        "E7",
        "`score` with `criteria` as an object",
        422,
        ("list_type",),
        "`score.criteria` is an ordered list (the legend), not an object — the "
        "two types take the same field name with different shapes",
        payload={
            "model": MODEL,
            "state": STATE,
            "questions": {
                "q": {"type": "score", "instructions": CALM, "criteria": INTENT}
            },
        },
    ),
    Case(
        "E8",
        "`model` absent",
        401,
        ("ModelError", "is not supported"),
        "not a 422 — the request validates and the resolver refuses an empty "
        "model name, in the `type`/`error` envelope rather than `detail`",
        payload={"state": STATE, "questions": {"q": noul(CALM)}},
    ),
    Case(
        "E9",
        "unknown `model`",
        400,
        ("server_error", "Model is unavailable."),
        "operational, not a caller shape error; the envelope is `error` with no "
        "`type` key, unlike E8",
        payload={
            "model": "jev-does-not-exist",
            "state": STATE,
            "questions": {"q": noul(CALM)},
        },
    ),
    Case(
        "E10",
        "paid model",
        402,
        ("server_error", "Insufficient account funds"),
        "the paid model is refused for funds, not for permission — a probe that "
        "used it would spend money rather than get an answer",
        payload={"model": PAID_MODEL, "state": STATE, "questions": {"q": noul(CALM)}},
    ),
    Case(
        "E11",
        "invalid credential",
        401,
        ("AuthError", "Invalid API key."),
        "`type`/`error` envelope; the key is never echoed back",
        payload=VALID,
        token="not-a-real-key",
    ),
    Case(
        "E12",
        "stdlib default `User-Agent` on the decision endpoint",
        403,
        (BLOCKED_BODY,),
        "the header the standard library sends when a caller sets none; plain "
        "text with a blank line, not JSON",
        payload=VALID,
        user_agent=STDLIB_USER_AGENT,
    ),
    Case(
        "E13",
        "`User-Agent` header omitted on the decision endpoint",
        403,
        (BLOCKED_BODY,),
        "identical to E12, which is the point: omitting the header is not "
        "neutral, the transport substitutes its own default and the gate refuses "
        "that one",
        payload=VALID,
        user_agent=ABSENT_UA,
    ),
    Case(
        "E14",
        "empty `User-Agent` on the decision endpoint",
        200,
        ("answers",),
        "the gate blocks a specific string, not the absence of one — which is "
        "why the probe sends its own name instead of relying on the default",
        payload=VALID,
        user_agent="",
    ),
    Case(
        "E15",
        "stdlib default `User-Agent` on the catalog",
        403,
        (BLOCKED_BODY,),
        "the same gate guards `GET /zen/v1/models`, so a client that sets no "
        "header cannot even list the models it might call",
        method="GET",
        endpoint=CATALOG,
        user_agent=STDLIB_USER_AGENT,
    ),
)


def test_e_every_refusal_is_recorded_verbatim() -> None:
    """E: one request per case, and the body the service returned."""
    refused: list[str] = []
    bodies: dict[str, str] = {}
    for case in CASES:
        response = _send(case)
        bodies[case.fact_id] = response.text
        status = f"{case.expect_status}"
        measured(
            "E",
            case.fact_id,
            case.name,
            f"HTTP {response.status} · {_clip(response.text)}",
            detail=case.note,
        )
        assert response.status == case.expect_status, (
            f"{case.fact_id} {case.name}: expected HTTP {case.expect_status}, "
            f"got {response.summary()}"
        )
        for expected in case.expect:
            assert expected in response.text, f"{case.fact_id}: {expected!r} missing"
        if response.status != 200:
            refused.append(f"{case.fact_id} {status}")

    assert bodies["E13"] == bodies["E12"], "an omitted header is the stdlib default"

    envelopes = {
        fact_id: sorted(_parsed(bodies[fact_id]))
        for fact_id in ("E1", "E4", "E8", "E9", "E11")
    }
    measured(
        "E",
        "E16",
        "error envelopes are not uniform",
        f"{len(set(map(tuple, envelopes.values())))} shapes over 5 non-422 refusals",
        detail=(
            f"{envelopes} · validation refusals carry `detail` (a list of paths), "
            "the model resolver carries `type` + `error`, and the upstream proxy "
            "carries `error` alone · an adapter that deserializes every failure "
            "into one shape misreads at least half of these"
        ),
    )
    assert len({tuple(shape) for shape in envelopes.values()}) > 1

    observed_layers = {status.split()[1] for status in refused}
    measured(
        "E",
        "E17",
        "refusal layers exercised",
        f"{len(refused)} of {len(CASES)} cases refused, by "
        f"{len(observed_layers)} statuses: {' · '.join(sorted(observed_layers))}",
        detail=(
            "· ".join(
                f"{status} {LAYERS[status]}" for status in sorted(observed_layers)
            )
            + " · the probe must never emit a 4xx against a healthy service, so "
            "every one of these is a caller bug or an operational fact, never a "
            "decision"
        ),
    )
    assert observed_layers == set(LAYERS), sorted(observed_layers)


def _send(case: Case) -> Response:
    """One case's request, with a load refusal turned into a skip.

    Every case below asserts the status it expects, so a `429` — the one
    refusal that is nobody's bug — would read as the case failing when the
    service merely declined to be measured right now.
    """
    if case.method == "GET":
        response = catalog(user_agent=case.user_agent, endpoint=case.endpoint)
    else:
        response = post(
            case.payload or {},
            token=case.token,
            user_agent=case.user_agent,
            endpoint=case.endpoint,
        )
    skip_if_rate_limited(response, f"E {case.fact_id} ({case.name})")
    return response


def _parsed(body: str) -> dict[str, Any]:
    parsed = json.loads(body)
    return parsed if isinstance(parsed, dict) else {}


def _clip(text: str, limit: int = 260) -> str:
    """`text` with nothing but its surrounding whitespace removed.

    Interior whitespace is preserved: rows in this file are read as *the body
    the service returned*, and a body with a doubled space in its message is a
    body worth seeing — collapsing it would quietly edit the evidence. Only the
    blank line the `403` answers end with is trimmed.
    """
    body = text.strip()
    return body if len(body) <= limit else f"{body[:limit]}…"
