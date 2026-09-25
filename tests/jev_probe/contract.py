"""Row A — the wire contract — and row G — what an answer cannot say.

The request shape and the three answer shapes are the whole of what a
provider-neutral adapter has to encode, and every one of them is measured here
rather than read from a page: one request carries a question of each type, and
the answer to each is recorded verbatim with the set of fields it carries.

The three answer types do **not** share a field set, which is the trap this row
exists to pin. `noul` carries a probability and no `probabilities`; `score`
carries a `legend` and no `choice`; `choice` carries neither `legend` nor a
score. A single response type that requires any of those fields is a type that
cannot deserialize one of the three.

Row G is the roadmap guard's wire-level basis, and it is a fact about the same
answers rather than a separate experiment: an answer is a probability, a label,
or an expected value over a legend. **None of the three is a boolean**, so no
answer can accept or reject anything on its own — the decision a `noul` feeds
has a threshold, and the threshold is the caller's, not the provider's.
"""

from __future__ import annotations

import json
from typing import Any, Final

from tests.jev_probe.client import (
    CATALOG,
    ENDPOINT,
    MODEL,
    PAID_MODEL,
    answer,
    ask,
    catalog,
    choice,
    load,
    noul,
    require_ok,
    score,
    throttled,
    usage,
)
from tests.jev_probe.conftest import require_endpoint, require_env
from tests.jev_probe.report import measured

require_env(
    "Jev / System One",
    "OPENCODE_API_KEY",
    hint="The reference's Provenance section carries the one-line export.",
)
require_endpoint("Jev / System One", ENDPOINT)

#: The states the probe draws on. The state is the evidence a decision is made
#: on; nothing else in the request carries any. Rows A, B, C, F and G all quote
#: one of these instead of inventing their own, so two rows compared to each
#: other are always compared on the same evidence.
#:
#: Row C's two decisions are `QUIET_STATE` and `STATE`: one ticket with and
#: without how the customer feels about it, which is the entire difference
#: between the decision that holds and the decision that flips.
#:
#: Row G samples `noul` repeatedly at `STATE` rather than at four different
#: states. Sampling across states would measure whether the probability tracks
#: the evidence, which this row does not claim and which was left for the next
#: run: the free tier's budget closed before it could be measured, and a
#: sampling design in the instrument that no run has exercised would put an
#: unmeasured number behind a measured stamp. `CALM_STATE` and `TRANSFER_STATE`
#: went with it, so the reference records the question instead of the code.
QUIET_STATE: Final[str] = (
    "Ticket: my parcel was delivered to the wrong address and I want a refund."
)
STATE: Final[str] = f"{QUIET_STATE} I am furious."


INTENT: Final[dict[str, str]] = {
    "shipping": "the parcel's journey",
    "billing": "money",
    "returns": "the customer wants a refund",
}
ANGER: Final[tuple[str, ...]] = ("Calm", "Frustrated", "Very angry")

CALM: Final[str] = "How likely is it that this customer is calm?"
OWNER: Final[str] = "Which team owns this ticket?"
LEVEL: Final[str] = "How angry is this customer?"

#: The field set each answer type carries, pinned as of this measurement.
NOUL_FIELDS: Final[set[str]] = {"type", "noul"}
CHOICE_FIELDS: Final[set[str]] = {"type", "choice", "confidence", "probabilities"}
SCORE_FIELDS: Final[set[str]] = {
    "type",
    "score",
    "confidence",
    "legend",
    "probabilities",
}


def three_questions() -> dict[str, dict[str, Any]]:
    """One question of each type, so the shapes arrive in a single answer."""
    return {
        "is_calm": noul(CALM),
        "intent": choice(OWNER, INTENT),
        "anger": score(LEVEL, ANGER),
    }


def test_a_one_request_carries_all_three_question_types() -> None:
    """A: the request envelope, the response envelope, and one answer per type."""
    response = ask(three_questions(), state=STATE)
    payload = require_ok(response)

    measured(
        "A",
        "A1",
        "request envelope",
        '{"model", "state", "questions"}',
        detail=(
            "a question object carries {type, instructions} plus criteria — an "
            "object of option → meaning for `choice`, an ordered list for `score` "
            "— and the three question types are accepted in one request"
        ),
    )
    measured(
        "A",
        "A2",
        "response envelope",
        json.dumps(sorted(payload), separators=(", ", ": ")),
        detail=(
            f"one `usage` block covers every question: {json.dumps(usage(payload), sort_keys=True)} "
            f"· model echoed as {payload.get('model')!r}"
        ),
    )
    assert set(payload) == {"model", "answers", "usage"}
    assert set(payload["answers"]) == {"is_calm", "intent", "anger"}
    assert {"input_tokens", "output_tokens"} <= set(usage(payload))

    calm = answer(payload, "is_calm")
    owner = answer(payload, "intent")
    anger = answer(payload, "anger")

    measured(
        "A",
        "A3",
        "`noul` answer",
        json.dumps(calm, sort_keys=True),
        detail=f"field set {sorted(calm)} — no `choice`, no `confidence`, no `probabilities`",
    )
    measured(
        "A",
        "A4",
        "`choice` answer",
        json.dumps(owner, sort_keys=True),
        detail=(
            f"field set {sorted(owner)} — `choice` is one of the criteria keys, "
            f"`probabilities` is keyed by all of them"
        ),
    )
    measured(
        "A",
        "A5",
        "`score` answer",
        json.dumps(anger, sort_keys=True),
        detail=(
            f"field set {sorted(anger)} — `legend` maps index → criterion, the "
            f"same strings the request sent, and `probabilities` is keyed by it"
        ),
    )
    measured(
        "A",
        "A6",
        "field sets per type",
        "noul ≠ choice ≠ score",
        detail=(
            "the three answer types share only `type`; a response model requiring "
            "a field from another type cannot deserialize every answer"
        ),
    )

    assert set(calm) == NOUL_FIELDS
    assert set(owner) == CHOICE_FIELDS
    assert set(anger) == SCORE_FIELDS
    assert owner["choice"] in INTENT
    assert set(owner["probabilities"]) == set(INTENT)
    assert set(anger["legend"]) == set(anger["probabilities"])
    assert [anger["legend"][str(index)] for index in range(len(ANGER))] == list(ANGER)


def test_g_no_answer_type_carries_a_verdict() -> None:
    """G: `noul` is a probability in [0, 1], and nothing answers a boolean."""
    samples = [
        answer(require_ok(ask({"is_calm": noul(CALM)}, state=STATE)), "is_calm")
        for _ in range(4)
    ]
    values = [sample["noul"] for sample in samples]
    measured(
        "G",
        "G1",
        "`noul` value range",
        f"{min(values):.4g} – {max(values):.4g} over {len(values)} samples",
        detail=(
            f"values {values} · field set {sorted(samples[0])} — a probability, "
            "with no threshold, no boolean and no field naming an outcome · four "
            "identical requests at one state, so this is the range of the answer "
            "rather than of the evidence"
        ),
    )
    assert all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in values
    )
    assert all(0.0 <= float(value) <= 1.0 for value in values)

    observed = {
        **three_questions_answers(),
        **{f"noul[{index}]": sample for index, sample in enumerate(samples)},
    }
    booleans = {
        question: sorted(
            key for key, value in answer_.items() if isinstance(value, bool)
        )
        for question, answer_ in observed.items()
    }
    measured(
        "G",
        "G2",
        "boolean fields in any answer",
        f"{sum(len(fields) for fields in booleans.values())}",
        detail=(
            f"the union of every answer field measured in this row is "
            f"{sorted({key for a in observed.values() for key in a})}; the only "
            "verdict-shaped value is a probability or a label, so the provider "
            "cannot by itself accept or reject a decision"
        ),
    )
    assert not any(fields for fields in booleans.values()), booleans


def three_questions_answers() -> dict[str, dict[str, Any]]:
    """The three answers of the shared request — measured again for row G."""
    payload = require_ok(ask(three_questions(), state=STATE))
    return {key: answer(payload, key) for key in ("is_calm", "intent", "anger")}


def test_f_the_service_answers_and_lists_the_models_it_serves() -> None:
    """F: reachability, the catalog, and whether the model is listed at all."""
    response = catalog()
    payload = require_ok(response)
    listed = [
        item["id"]
        for item in payload.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    measured(
        "F",
        "F1",
        "catalog reachability",
        f"HTTP {response.status} in {response.seconds:.3f} s · {len(listed)} models",
        detail=(
            f"GET {CATALOG} · envelope keys {sorted(payload)} · one entry carries "
            f"{sorted(next(item for item in payload['data'] if isinstance(item, dict)))} "
            "— the catalog is what a client would use to discover a model name "
            "rather than hard-code one"
        ),
    )
    measured(
        "F",
        "F2",
        "the measured model is listed",
        f"{MODEL} {'listed' if MODEL in listed else 'NOT listed'} "
        f"(paid sibling {PAID_MODEL} {'listed' if PAID_MODEL in listed else 'NOT listed'})",
        detail=(
            f"the two `jev` entries in the catalog are "
            f"{sorted(name for name in listed if name.startswith('jev'))} · both "
            "are listed, and the free one answers while the paid one is refused "
            "for funds (row E10) — the catalog says a model exists, not that the "
            "account may call it"
        ),
    )
    decision = ask({"is_calm": noul(CALM)}, state=STATE)
    require_ok(decision)
    measured(
        "F",
        "F3",
        "decision endpoint reachability",
        f"HTTP {decision.status} in {decision.seconds:.3f} s",
        detail=(
            f"POST {ENDPOINT} with the probe's own `User-Agent` · reachability was "
            "established by a TCP connect before this module's first request, so a "
            "skip here means the service was absent and a failure means it is "
            "unhappy about the request — never the same thing"
        ),
    )
    assert response.status == 200
    assert MODEL in listed


def test_f4_the_run_says_what_load_it_met() -> None:
    """F4: what the run met for load — its own cell, taken without a model call.

    This fact is recorded by a test of its own rather than at the end of the
    one above: it describes the load the run met, so it is exactly the cell a
    reader wants when the model calls themselves were refused for load. Folded
    into the test above it would be skipped along with them, and the run would
    report nothing about the refusals it did meet.
    """
    refusals = throttled()
    if refusals:
        first = refusals[0]
        measured(
            "F",
            "F4",
            "load refusals met by the run",
            f"{len(refusals)} × HTTP {first.status} over {load()} round trips",
            detail=(
                f"first body: {first.body} · the service asked to wait "
                f"{[refusal.seconds_waited for refusal in refusals]} s, so no "
                "request was retried and every model-backed cell of this run "
                "skipped instead of failing · this is the account's burst budget, "
                "not the contract, and an adapter calling the model per decision "
                "needs the same bound rather than an exception"
            ),
        )
    else:
        measured(
            "F",
            "F4",
            "load refusals met by the run",
            f"none over {load()} round trips",
            detail=(
                "the free model answered every request of a run this size without "
                "a `429` · the client still retries `429`/`503` with backoff, "
                "because a refusal for load is the account's burst budget rather "
                "than the contract, and what it meets is recorded here rather "
                "than swallowed"
            ),
        )
