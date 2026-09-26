"""Row C — stability: two decisions, twenty identical requests each.

This is the row the roadmap's "confidence alone must not authorize a side
effect" rule is built on, and it is measured twice on purpose:

- a **stable** decision — one team owns the ticket and the criteria are not
  close, so the argmax has no reason to move;
- a **near-tied** decision — the same ticket with one clause added, which makes
  two criteria fit it about equally well, so the argmax has a reason to move.

The second is the interesting one: a decision the model flips on across
identical requests. Nothing about the *request* changed between samples — only
the service's own sampling.

Both sweeps send one question per request, so a latency is one request's
latency rather than a batch's, and both are cached per session so the three
tests below cost forty requests rather than eighty.
"""

from __future__ import annotations

from functools import cache
from typing import Any, Final

from tests.jev_probe.client import (
    ENDPOINT,
    answer,
    ask_one,
    choice,
    require_ok,
)
from tests.jev_probe.conftest import require_endpoint, require_env
from tests.jev_probe.contract import INTENT, OWNER, QUIET_STATE, STATE
from tests.jev_probe.report import measured

require_env(
    "Jev / System One",
    "OPENCODE_API_KEY",
    hint="The reference's Provenance section carries the one-line export.",
)
require_endpoint("Jev / System One", ENDPOINT)

#: N ≥ 20 identical requests per decision, as the matrix asks.
SAMPLES: Final[int] = 20

#: The stable decision and the near-tied one: the same ticket with and without
#: how the customer feels about it. Both states are defined in `contract.py` so
#: that every row quoting a state quotes the same text; one clause is the whole
#: difference between the two sweeps, and it is what moves `returns` and
#: `shipping` onto each other.
STABLE_STATE: Final[str] = QUIET_STATE
NEAR_TIED_STATE: Final[str] = STATE


@cache
def stable_sweep() -> tuple[tuple[dict[str, Any], ...], tuple[float, ...]]:
    """Twenty identical requests to the decision the evidence settles."""
    return sweep(STABLE_STATE)


@cache
def near_tied_sweep() -> tuple[tuple[dict[str, Any], ...], tuple[float, ...]]:
    """Twenty identical requests to the decision the evidence splits."""
    return sweep(NEAR_TIED_STATE)


def sweep(
    state: str, *, count: int = SAMPLES
) -> tuple[tuple[dict[str, Any], ...], tuple[float, ...]]:
    """`count` identical requests to one decision, and each one's latency."""
    responses = [ask_one(choice(OWNER, INTENT), state=state) for _ in range(count)]
    return (
        tuple(answer(require_ok(response), "q") for response in responses),
        tuple(response.seconds for response in responses),
    )


def test_c1_a_stable_decision() -> None:
    """C1: the argmax, the spread and the latency of twenty identical calls."""
    answers, latencies = stable_sweep()
    _record("C1", "stable decision", answers, latencies)
    assert len(answers) == SAMPLES


def test_c2_a_near_tied_decision_flips_across_identical_requests() -> None:
    """C2: the same ticket plus one clause — the decision boundary itself."""
    answers, latencies = near_tied_sweep()
    flips = _record("C2", "near-tied decision", answers, latencies)
    assert flips > 0, [sample["probabilities"] for sample in answers]


def test_c3_one_clause_is_the_difference_between_the_two_sweeps() -> None:
    """C3: the sweeps differ in the state and in nothing else."""
    stable, _ = stable_sweep()
    near_tied, _ = near_tied_sweep()
    stable_flips = _flips(stable)
    near_tied_flips = _flips(near_tied)
    measured(
        "C",
        "C3",
        "argmax flips, stable vs near-tied",
        f"{stable_flips}/{len(stable)} vs {near_tied_flips}/{len(near_tied)}",
        detail=(
            f"the two states differ by the sentence {'I am furious.'!r} and the "
            f"request is otherwise identical · same criteria {sorted(INTENT)} · "
            f"the stable sweep's top-two gap stays "
            f"{_top_two_gap(stable, minimum=True):.2f}–{_top_two_gap(stable):.2f} "
            f"while the near-tied sweep's falls to "
            f"{_top_two_gap(near_tied, minimum=True):.2f}–{_top_two_gap(near_tied):.2f}"
        ),
    )
    assert near_tied_flips > stable_flips


def _record(
    fact_id: str,
    label: str,
    answers: tuple[dict[str, Any], ...],
    latencies: tuple[float, ...],
) -> int:
    """Write one sweep's row and return how many argmaxes moved."""
    flips = _flips(answers)
    spread = " · ".join(
        f"{option} {min(values):.2f}–{max(values):.2f}"
        for option, values in _per_option(answers).items()
    )
    confidences = [sample["confidence"] for sample in answers]
    measured(
        "C",
        fact_id,
        f"{label} over {len(answers)} identical requests",
        f"argmax flips {flips}/{len(answers)}",
        detail=(
            f"probability range per option: {spread} · confidence "
            f"{min(confidences):.2f}–{max(confidences):.2f} · latency "
            f"{min(latencies):.3f}/{sum(latencies) / len(latencies):.3f}/"
            f"{max(latencies):.3f} s (min/mean/max) · latencies "
            f"{[round(value, 3) for value in latencies]}"
        ),
    )
    return flips


def _per_option(answers: tuple[dict[str, Any], ...]) -> dict[str, list[float]]:
    return {
        option: [sample["probabilities"][option] for sample in answers]
        for option in INTENT
    }


def _argmaxes(answers: tuple[dict[str, Any], ...]) -> list[str]:
    return [
        max(sample["probabilities"], key=lambda option: sample["probabilities"][option])
        for sample in answers
    ]


def _flips(answers: tuple[dict[str, Any], ...]) -> int:
    """How many samples disagree with the first sample's argmax."""
    argmaxes = _argmaxes(answers)
    return sum(1 for argmax in argmaxes if argmax != argmaxes[0])


def _top_two_gap(
    answers: tuple[dict[str, Any], ...], *, minimum: bool = False
) -> float:
    """The runner-up's distance, over the sweep — the tightest one by default."""
    gaps = []
    for sample in answers:
        ranked = sorted(sample["probabilities"].values(), reverse=True)
        gaps.append(round(ranked[0] - ranked[1], 4))
    return min(gaps) if minimum else max(gaps)
