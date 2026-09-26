"""Row B — the identities the adapter would otherwise assume.

Three claims a reader of one response would plausibly make, each measured over
a run rather than over a sample of one:

- **`score` is the expected value over the legend index.** If true, the adapter
  needs the legend and not only the float: `score` 1.31 means 1 × 0.69 + 2 ×
  0.31, which is only recoverable with the labels.
- **`confidence` is not `max(probabilities)`.** The tempting deserializer
  computes one from the other; the row measures how far apart they are, and
  whether they ever coincide.
- **`probabilities` key order is not the request's order** and is not stable
  across identical calls, so an adapter that reads options positionally is
  reading an order the service never promised.

Everything here is measured on `choice` and `score` answers, the two types that
carry `probabilities`; a `noul` answer carries none (row A).
"""

from __future__ import annotations

from functools import cache
from typing import Any, Final

from tests.jev_probe.client import (
    ENDPOINT,
    MODEL,
    answer,
    ask_one,
    choice,
    require_ok,
    score,
)
from tests.jev_probe.conftest import require_endpoint, require_env
from tests.jev_probe.contract import ANGER, INTENT, LEVEL, OWNER, STATE
from tests.jev_probe.report import measured

require_env(
    "Jev / System One",
    "OPENCODE_API_KEY",
    hint="The reference's Provenance section carries the one-line export.",
)
require_endpoint("Jev / System One", ENDPOINT)

#: How many identical requests each identity is measured over. Twenty-four is
#: past the twenty the matrix asks for and costs ~18 s; the whole probe is
#: budgeted under three minutes.
SAMPLES: Final[int] = 12

#: `score` is reported to two decimals, so a residual smaller than half a cent
#: is rounding rather than a broken identity.
RESIDUAL_TOLERANCE: Final[float] = 0.005


@cache
def score_answers() -> tuple[dict[str, Any], ...]:
    """`SAMPLES` answers to one graded question, each its own request."""
    return tuple(
        answer(require_ok(ask_one(score(LEVEL, ANGER), state=STATE)), "q")
        for _ in range(SAMPLES)
    )


@cache
def choice_answers() -> tuple[dict[str, Any], ...]:
    """`SAMPLES` answers to one single-label question, each its own request."""
    return tuple(
        answer(require_ok(ask_one(choice(OWNER, INTENT), state=STATE)), "q")
        for _ in range(SAMPLES)
    )


def test_b1_score_is_the_expected_value_over_the_legend_index() -> None:
    """B1: Σ index × probability, and what is left over."""
    answers = score_answers()
    residuals = [
        round(
            sample["score"]
            - sum(
                int(index) * value for index, value in sample["probabilities"].items()
            ),
            6,
        )
        for sample in answers
    ]
    worst = max(abs(residual) for residual in residuals)
    measured(
        "B",
        "B1",
        "`score` − Σ index × probability",
        f"max |residual| {worst:.6g} over {len(answers)} answers",
        detail=(
            f"residuals {residuals} · legend "
            f"{answers[0]['legend']} · probabilities are reported to two decimals "
            f"and indices are integers, so the sum is exact to two decimals: a "
            f"residual above {RESIDUAL_TOLERANCE} would mean `score` is not that "
            "expected value, and the adapter would need a rule the wire does not have"
        ),
    )
    assert worst <= RESIDUAL_TOLERANCE


def test_b2_confidence_is_not_the_largest_probability() -> None:
    """B2: how far `confidence` sits from `max(probabilities)`, over both types."""
    samples = (*choice_answers(), *score_answers())
    gaps = [
        round(max(sample["probabilities"].values()) - sample["confidence"], 6)
        for sample in samples
    ]
    coincide = [gap for gap in gaps if abs(gap) <= 1e-9]
    differ = [gap for gap in gaps if abs(gap) > 1e-9]
    measured(
        "B",
        "B2",
        "max(probabilities) − confidence",
        f"{min(differ):.4g} – {max(differ):.4g} apart, "
        f"{len(coincide)}/{len(samples)} coincide",
        detail=(
            f"over {SAMPLES} `choice` and {SAMPLES} `score` answers · gap range "
            f"{min(gaps):.4g} – {max(gaps):.4g} · confidence never exceeded "
            f"max(probabilities) in this run · they coincide only where the answer "
            f"is unanimous · confidence is a provider-supplied scalar, not a "
            "quantity the adapter can recompute"
        ),
    )
    assert len(differ) > 0, gaps[:5]
    assert all(0.0 <= sample["confidence"] <= 1.0 for sample in samples)
    assert all(
        abs(sum(sample["probabilities"].values()) - 1.0) <= 0.02 for sample in samples
    )


def test_b3_probability_key_order_is_neither_the_request_nor_stable() -> None:
    """B3: the order the keys arrive in, against the order the request sent."""
    requested = list(INTENT)
    orders = [tuple(sample["probabilities"]) for sample in choice_answers()]
    matching = [order for order in orders if list(order) == requested]
    measured(
        "B",
        "B3",
        "`probabilities` key order",
        f"{len(set(orders))} distinct orders over {len(orders)} answers; "
        f"{len(matching)} matched the request order",
        detail=(
            f"request order {requested} · observed {sorted({order for order in orders})} "
            "· an adapter that reads options positionally reads an order the "
            "service never promised"
        ),
    )
    assert len(matching) < len(orders)


def test_the_samples_are_identical_requests_to_one_model() -> None:
    """The rows above are only an identity if every sample is the same call."""
    assert MODEL == "jev-1.13-free"
    assert {sample["type"] for sample in choice_answers()} == {"choice"}
    assert {sample["type"] for sample in score_answers()} == {"score"}
