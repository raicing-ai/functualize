"""Row D — what one decision costs, and what makes it cost more.

The roadmap's cost rule ("a per-decision budget") needs two numbers: the size
of one request, and what each additional thing in it adds. The service reports
one `usage` block per request covering every question in it, so the cost is the
request's, not the question's — and stage 2's budget is therefore per
`DecisionRequest`, not per question.

Seven points, each one request, chosen so the three things a caller controls
separate cleanly: the length of the state, the number of questions, and the
number of criteria.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from tests.jev_probe.client import (
    ENDPOINT,
    MODEL,
    ask,
    choice,
    noul,
    require_ok,
    score,
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

CALM: Final[str] = "How likely is it that this customer is calm?"
OWNER: Final[str] = "Which team owns this ticket?"
INTENT: Final[dict[str, str]] = {
    "shipping": "the parcel's journey",
    "billing": "money",
    "returns": "the customer wants a refund",
}
ANGER: Final[tuple[str, ...]] = ("Calm", "Frustrated", "Very angry")

#: A short state, and the same state padded with a fixed, repeating sentence —
#: so the only thing that changed between two points is the number of
#: characters the state carries.
SHORT_STATE: Final[str] = "Ticket: my parcel is late."
FILLER: Final[str] = (
    "The customer has written three times and asked for the tracking number. "
)
LONG_STATE: Final[str] = SHORT_STATE + FILLER * 4

#: The token keys a `usage` block carries; anything else would need a rule.
USAGE_KEYS: Final[set[str]] = {"input_tokens", "output_tokens"}


@dataclass(frozen=True, slots=True)
class Point:
    """One measured request: what it varies, and nothing else."""

    label: str
    state: str
    questions: dict[str, dict[str, Any]]


POINTS: Final[tuple[Point, ...]] = (
    Point("noul ×1", SHORT_STATE, {"q": noul(CALM)}),
    Point("noul ×2", SHORT_STATE, {"q1": noul(CALM), "q2": noul(CALM)}),
    Point(
        "noul ×3",
        SHORT_STATE,
        {"q1": noul(CALM), "q2": noul(CALM), "q3": noul(CALM)},
    ),
    Point("noul ×1, long state", LONG_STATE, {"q": noul(CALM)}),
    Point("choice, 3 criteria", SHORT_STATE, {"q": choice(OWNER, INTENT)}),
    Point(
        "choice, 6 criteria",
        SHORT_STATE,
        {
            "q": choice(
                OWNER,
                {
                    **INTENT,
                    "damage": "the parcel arrived damaged",
                    "late": "the parcel is late",
                    "other": "none of these",
                },
            )
        },
    ),
    Point("score, 3 criteria", SHORT_STATE, {"q": score(OWNER, ANGER)}),
)


def test_d_one_request_costs_one_usage_block() -> None:
    """D: the token cost of each point, and what moves it."""
    tokens: dict[str, dict[str, int]] = {}
    for point in POINTS:
        response = ask(point.questions, state=point.state)
        block = usage(require_ok(response))
        tokens[point.label] = {
            "input_tokens": int(block["input_tokens"]),
            "output_tokens": int(block["output_tokens"]),
        }
        assert set(block) == USAGE_KEYS, block

    table = " · ".join(
        f"{label} {counts['input_tokens']}/{counts['output_tokens']}"
        for label, counts in tokens.items()
    )
    measured(
        "D",
        "D1",
        "input/output tokens per request",
        f"{len(POINTS)} points, one `usage` block each",
        detail=(
            f"{table} · every point answered with `{{{', '.join(sorted(USAGE_KEYS))}}}` "
            "and nothing else; one block covers every question in the request, so "
            "the unit of cost is the request rather than the question · model "
            f"{MODEL}"
        ),
    )

    one, two, three = (
        tokens["noul ×1"],
        tokens["noul ×2"],
        tokens["noul ×3"],
    )
    measured(
        "D",
        "D2",
        "cost of another question in the same request",
        f"+{two['input_tokens'] - one['input_tokens']} input, "
        f"+{two['output_tokens'] - one['output_tokens']} output tokens",
        detail=(
            f"three identical questions in one request: "
            f"{one['input_tokens']}/{one['output_tokens']} → "
            f"{two['input_tokens']}/{two['output_tokens']} → "
            f"{three['input_tokens']}/{three['output_tokens']} "
            "(input/output) · the second and third question add the same "
            "increments, which is what makes batching questions into one "
            "`DecisionRequest` cheaper than batching requests"
        ),
    )
    assert two["input_tokens"] > one["input_tokens"]
    assert three["input_tokens"] > two["input_tokens"]
    assert three["output_tokens"] > two["output_tokens"] > one["output_tokens"]

    short, long = tokens["noul ×1"], tokens["noul ×1, long state"]
    measured(
        "D",
        "D3",
        "cost of the state",
        f"{len(SHORT_STATE)} → {len(LONG_STATE)} characters cost "
        f"+{long['input_tokens'] - short['input_tokens']} input tokens",
        detail=(
            f"{short['input_tokens']} → {long['input_tokens']} input and "
            f"{short['output_tokens']} → {long['output_tokens']} output tokens for "
            f"{len(LONG_STATE) - len(SHORT_STATE)} more characters "
            f"(≈ {(len(LONG_STATE) - len(SHORT_STATE)) / max(long['input_tokens'] - short['input_tokens'], 1):.1f} "
            "characters per token) · a longer state buys no more output, so a "
            "caller pays for the evidence it sends, not for the answer it gets"
        ),
    )
    assert long["input_tokens"] > short["input_tokens"]

    criteria = tokens["choice, 3 criteria"], tokens["choice, 6 criteria"]
    measured(
        "D",
        "D4",
        "cost of another criterion",
        f"+{criteria[1]['input_tokens'] - criteria[0]['input_tokens']} input, "
        f"+{criteria[1]['output_tokens'] - criteria[0]['output_tokens']} output tokens",
        detail=(
            f"`choice` with 3 criteria {criteria[0]['input_tokens']}/{criteria[0]['output_tokens']} "
            f"→ 6 criteria {criteria[1]['input_tokens']}/{criteria[1]['output_tokens']} "
            "(input/output) · criteria cost on both sides, because they are both "
            "part of the question and the answer's `probabilities`"
        ),
    )
    assert criteria[1]["input_tokens"] > criteria[0]["input_tokens"]

    noul_one, choice_three = tokens["noul ×1"], tokens["choice, 3 criteria"]
    measured(
        "D",
        "D5",
        "cost by question type",
        f"noul {noul_one['input_tokens']}/{noul_one['output_tokens']} · "
        f"score {tokens['score, 3 criteria']['input_tokens']}/"
        f"{tokens['score, 3 criteria']['output_tokens']} · "
        f"choice {choice_three['input_tokens']}/{choice_three['output_tokens']}",
        detail=(
            "the same state, one question of each type · the three types are the "
            "same order of magnitude, so a per-type budget would be a fiction; a "
            "`choice` costs more than a `noul` because its answer carries a "
            "probability per criterion while `noul` carries one number"
        ),
    )
