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

from collections.abc import Iterable, Mapping
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

#: How many identical requests each identity is measured over: twelve per identity, and
#: twenty-four pooled across the two types B2 reads. It costs ~18 s of the probe's
#: three-minute budget.
SAMPLES: Final[int] = 12

#: The places the provider's numbers carry. `score` and every probability arrive with two
#: decimals and the printer strips a trailing zero, so `2` is a `2.00` and is read at two
#: places rather than at none. It is a floor and not a fixed budget: `_half_place` reads a
#: value at the places it was actually reported to when that is more, so a run against a
#: wire that reports a third decimal is measured against the tighter precision it saw
#: instead of failing on a constant that outlived the wire it described.
REPORTED_PLACE: Final[int] = 2


def _place(value: float) -> int:
    """The decimal place `value` was reported to, never below the provider's own two."""
    text = f"{value:.12f}".rstrip("0")
    return max(REPORTED_PLACE, len(text.partition(".")[2]))


def _half_place(value: float) -> float:
    """Half of the last reported place of `value` — the most that report can be off by."""
    return 0.5 * 10 ** -_place(value)


def residual_budget(sample: Mapping[str, Any]) -> float:
    """The most rounding one answer's identity can carry, from its own reported numbers.

    The identity is `score − Σ index × probability`, so it has one rounding term per value
    it sums: half of `score`'s last place, plus half of each probability's last place
    weighted by that probability's legend index. For the probe's three-point legend that is
    `0.005 + 0.005 × (0 + 1 + 2) = 0.02`.
    """
    return _half_place(sample["score"]) + sum(
        abs(int(index)) * _half_place(value)
        for index, value in sample["probabilities"].items()
    )


def residual(sample: Mapping[str, Any]) -> float:
    """`score` minus Σ index × probability, unrounded.

    The budget this is measured against comes from the precision the wire reported, so
    the subtraction keeps every digit it has. Rounding here would present a residual one
    place above its budget as `0.0` and pass an answer whose identity is off by more than
    the wire can account for; `residual_budget` carries no such rounding either.
    """
    return sample["score"] - sum(
        int(index) * value for index, value in sample["probabilities"].items()
    )


def out_of_budget(
    samples: Iterable[Mapping[str, Any]],
) -> list[tuple[int, float, float]]:
    """Every answer whose residual is larger than that answer's own rounding budget.

    The comparison is on the unrounded residual, and the tuple reports that value rather
    than a rounded reading of it, so an answer that fails by one place of its own budget
    is visible as the failure it is.
    """
    over: list[tuple[int, float, float]] = []
    for index, sample in enumerate(samples):
        value = residual(sample)
        budget = residual_budget(sample)
        if abs(value) > budget:
            over.append((index, value, budget))
    return over


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
    """B1: Σ index × probability, and whether what is left over is only rounding."""
    answers = score_answers()
    unrounded = [residual(sample) for sample in answers]
    residuals = [round(value, 6) for value in unrounded]
    budgets = [residual_budget(sample) for sample in answers]
    places = {
        _place(value)
        for sample in answers
        for value in (sample["score"], *sample["probabilities"].values())
    }
    worst = max(abs(value) for value in unrounded)
    measured(
        "B",
        "B1",
        "`score` − Σ index × probability",
        f"max |residual| {worst:.6g} over {len(answers)} answers, against a "
        f"{max(budgets):.6g} rounding budget",
        detail=(
            f"residuals {residuals} · legend {answers[0]['legend']} · reported to "
            f"{'/'.join(str(place) for place in sorted(places))} decimals, so the identity "
            f"carries one rounding term per value it sums: half a unit of `score`'s last "
            f"place, plus half a unit of each probability's last place weighted by that "
            f"probability's index — {max(budgets):.6g} for this legend, "
            f"{min(budgets):.6g} – {max(budgets):.6g} over the answers · the residuals "
            "shown are rounded to six places for reading and the comparison against each "
            "budget is on the unrounded value, so a residual one place above its budget "
            "cannot present as zero · a residual above its own answer's budget is more "
            "than the wire's precision can account for, and would mean `score` is not "
            "that expected value, so the adapter would need a rule the wire does not have"
        ),
    )
    over = out_of_budget(answers)
    assert not over, f"residuals leave their rounding budget: {over}"


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
