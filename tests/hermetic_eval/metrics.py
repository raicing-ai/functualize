"""Descriptive routing metrics computed from a measurement ledger.

Every function here is pure: no I/O, no clock, no network. A ledger row is a
``dict`` carrying the schema keys this module reads — ``scenario``, ``repeat``,
``expected``, ``stratum``, ``status`` (``routed`` / ``failed`` /
``invalid_model`` / ``not_attempted``), ``route``, ``decided_by``, ``proposal``,
``distribution``, ``probability``, ``margin``, ``confidence``,
``latency_seconds`` and ``frontier`` (an object with a ``usage`` block, or
``None``). Rows whose ``status`` is ``not_attempted`` were never measured and
are excluded from every distribution, confusion and latency; they still count
as wrong in ``routed_accuracy`` because the denominator is every cell.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from tests.hermetic_eval.corpus import BOUNDARY, ROUTES

Row = Mapping[str, Any]

__all__ = [
    "accepts",
    "accuracy_summary",
    "agreement",
    "boundary",
    "calibration",
    "conformance",
    "cost",
    "errors_at",
    "escalation",
    "flip_points",
    "latency",
    "proposed_confusion",
    "route_at",
    "routed_confusion",
    "sweep",
    "variance",
    "verdict",
]

_NOT_ATTEMPTED = "not_attempted"
_FAILED = "failed"
_HUMAN_REVIEW = "human_review"
_BINS = 10


def routed_confusion(rows: Sequence[Row]) -> dict[str, dict[str, int]]:
    """Count expected → recorded route, over measured cells.

    Both axes carry all four routes, zeros included.
    """
    table: dict[str, dict[str, int]] = {
        expected: {route: 0 for route in ROUTES} for expected in ROUTES
    }
    for row in rows:
        if row["status"] == _NOT_ATTEMPTED:
            continue
        table[row["expected"]][row["route"]] += 1
    return table


def proposed_confusion(rows: Sequence[Row]) -> dict[str, dict[str, int]]:
    """Count expected → proposal (or ``failed`` when there was none)."""
    table: dict[str, dict[str, int]] = {expected: {} for expected in ROUTES}
    for row in rows:
        if row["status"] == _NOT_ATTEMPTED:
            continue
        proposal = row["proposal"] if row["proposal"] is not None else _FAILED
        bucket = table[row["expected"]]
        bucket[proposal] = bucket.get(proposal, 0) + 1
    return table


def accuracy_summary(rows: Sequence[Row]) -> dict[str, Any]:
    """Summarise availability, accuracy and per-route precision/recall."""
    cells = len(rows)
    routed = sum(1 for row in rows if row["status"] == "routed")
    correct = sum(1 for row in rows if row["route"] == row["expected"])
    measured = [row for row in rows if row["status"] != _NOT_ATTEMPTED]
    per_route: dict[str, dict[str, Any]] = {}
    for route in ROUTES:
        taken = [row for row in measured if row["route"] == route]
        actual = [row for row in measured if row["expected"] == route]
        hits = [
            row
            for row in measured
            if row["route"] == route and row["expected"] == route
        ]
        per_route[route] = {
            "precision": len(hits) / len(taken) if taken else 0.0,
            "recall": len(hits) / len(actual) if actual else 0.0,
            "support": len(actual),
        }
    f1_scores = [
        _f1(entry["precision"], entry["recall"]) for entry in per_route.values()
    ]
    return {
        "cells": cells,
        "availability": routed / cells if cells else 0.0,
        "routed_accuracy": correct / cells if cells else 0.0,
        "per_route": per_route,
        "macro_f1": sum(f1_scores) / len(ROUTES),
    }


def agreement(rows_a: Sequence[Row], rows_b: Sequence[Row]) -> dict[str, Any]:
    """Cohen's kappa and raw agreement between two ledgers over shared cells."""
    by_key_b = {
        (row["scenario"], row["repeat"]): row["route"]
        for row in rows_b
        if row["status"] != _NOT_ATTEMPTED
    }
    pairs: list[tuple[str, str]] = []
    for row in rows_a:
        if row["status"] == _NOT_ATTEMPTED:
            continue
        other = by_key_b.get((row["scenario"], row["repeat"]))
        if other is not None:
            pairs.append((row["route"], other))
    total = len(pairs)
    if not total:
        return {"rate": None, "kappa": None}
    rate = sum(1 for left, right in pairs if left == right) / total
    left_counts = Counter(left for left, _ in pairs)
    right_counts = Counter(right for _, right in pairs)
    expected = sum(
        (left_counts[route] / total) * (right_counts[route] / total)
        for route in set(left_counts) | set(right_counts)
    )
    kappa = 1.0 if expected == 1.0 else (rate - expected) / (1.0 - expected)
    return {"rate": rate, "kappa": kappa}


def calibration(rows: Sequence[Row], key: str = "probability") -> dict[str, Any]:
    """Bucket the rows' confidence, and score its calibration.

    Bins are ``[0.0, 0.1)`` … ``[0.9, 1.0]``; ``ece`` is the sample-weighted
    gap between each bin's accuracy and its mean confidence; ``brier`` is the
    mean squared error of the four-route distribution against the labelled
    route, and is ``None`` unless ``key`` is the probability.
    """
    scored = [row for row in rows if row[key] is not None]
    bins: list[dict[str, Any]] = []
    for index in range(_BINS):
        members = [row for row in scored if _bin_index(row[key]) == index]
        count = len(members)
        bins.append(
            {
                "lo": round(index / _BINS, 1),
                "hi": round((index + 1) / _BINS, 1),
                "n": count,
                "mean_p": (
                    sum(float(row[key]) for row in members) / count if count else None
                ),
                "accuracy": (
                    sum(1 for row in members if row["proposal"] == row["expected"])
                    / count
                    if count
                    else None
                ),
            }
        )
    ece = (
        sum(
            entry["n"] * abs(entry["accuracy"] - entry["mean_p"])
            for entry in bins
            if entry["n"]
        )
        / len(scored)
        if scored
        else 0.0
    )
    brier = None
    if key == "probability":
        scored_rows = [row for row in rows if row["distribution"] is not None]
        if scored_rows:
            brier = sum(_brier(row) for row in scored_rows) / len(scored_rows)
    return {"bins": bins, "ece": ece, "brier": brier}


def escalation(rows: Sequence[Row]) -> dict[str, Any]:
    """Measure what continued without a person and what should have stopped."""
    considered = [row for row in rows if row["status"] != _NOT_ATTEMPTED]
    total = len(considered)
    continued = [
        row
        for row in considered
        if row["decided_by"] == "decision" and row["route"] != _HUMAN_REVIEW
    ]
    escalated = [row for row in considered if row["route"] == _HUMAN_REVIEW]
    needed = [row for row in considered if _needed(row)]
    hits = [row for row in escalated if _needed(row)]
    return {
        "coverage": len(continued) / total if total else 0.0,
        "selective_accuracy": (
            sum(1 for row in continued if row["route"] == row["expected"])
            / len(continued)
            if continued
            else None
        ),
        "precision": len(hits) / len(escalated) if escalated else None,
        "recall": len(hits) / len(needed) if needed else None,
        "by_cause": {
            "fallback": sum(1 for row in escalated if row["decided_by"] == "fallback"),
            "proposal": sum(1 for row in escalated if row["decided_by"] == "decision"),
        },
    }


def latency(rows: Sequence[Row]) -> dict[str, Any]:
    """Return the p50, p95 and maximum latency of the measured cells."""
    values = sorted(
        float(row["latency_seconds"])
        for row in rows
        if row["status"] != _NOT_ATTEMPTED and row["latency_seconds"] is not None
    )
    if not values:
        return {"p50": None, "p95": None, "max": None}

    def nearest_rank(quantile: float) -> float:
        return values[math.ceil(quantile * len(values)) - 1]

    return {"p50": nearest_rank(0.5), "p95": nearest_rank(0.95), "max": values[-1]}


def cost(rows: Sequence[Row]) -> dict[str, Any]:
    """Sum the token usage the comparators reported.

    ``usd_total`` is ``0.0`` when nothing priced a call, and ``None`` when a
    frontier call happened: the frontier runs on a subscription that reports no
    price and none is invented.
    """
    input_tokens = sum(int(row["input_tokens"] or 0) for row in rows)
    output_tokens = sum(int(row["output_tokens"] or 0) for row in rows)
    cached = sum(_usage(row, "cached_input_tokens") for row in rows)
    reasoning = sum(_usage(row, "reasoning_output_tokens") for row in rows)
    correct = sum(1 for row in rows if row["route"] == row["expected"])
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached,
        "reasoning_output_tokens": reasoning,
        "tokens_per_correct_route": (
            (input_tokens + output_tokens) / correct if correct else None
        ),
        "usd_total": None if any(row["frontier"] is not None for row in rows) else 0.0,
    }


def variance(rows: Sequence[Row]) -> dict[str, Any]:
    """Measure how much a scenario's route moves between repeats."""
    by_scenario: dict[str, list[Row]] = {}
    for row in rows:
        if row["status"] == _NOT_ATTEMPTED:
            continue
        by_scenario.setdefault(row["scenario"], []).append(row)
    agreements: list[float] = []
    probability_sds: list[float] = []
    flipped: list[str] = []
    for scenario in sorted(by_scenario):
        members = by_scenario[scenario]
        routes = Counter(row["route"] for row in members)
        agreements.append(max(routes.values()) / len(members))
        if len(routes) > 1:
            flipped.append(scenario)
        probabilities = [
            float(row["probability"])
            for row in members
            if row["probability"] is not None
        ]
        probability_sds.append(
            statistics.pstdev(probabilities) if len(probabilities) >= 2 else 0.0
        )
    return {
        "mean_modal_agreement": (
            sum(agreements) / len(agreements) if agreements else 0.0
        ),
        "flips": len(flipped),
        "mean_probability_sd": (
            sum(probability_sds) / len(probability_sds) if probability_sds else 0.0
        ),
        "flipped": flipped,
    }


_ACCEPT_ATS = tuple(round(0.50 + 0.05 * index, 2) for index in range(10))
_MIN_MARGINS = (0.00, 0.05, 0.10, 0.15, 0.20)


def accepts(p: float, margin: float, accept_at: float, min_margin: float) -> bool:
    """The rounder's rule: both thresholds must be met, exactly.

    No rounding: the gate that will consume this rule compares the same two
    numbers the same way.
    """
    return p >= accept_at and margin >= min_margin


def route_at(
    row: Row,
    accept_at: float,
    min_margin: float,
    fallback: str = _HUMAN_REVIEW,
) -> tuple[str | None, bool]:
    """Replay one row's decision at a threshold pair.

    The bool says the *decision* chose the route: ``False`` means the fallback
    absorbed a cell that was unmeasurable or was not accepted. A never-attempted
    cell has no route at all, which is how the sweep tells the two apart.
    """
    if row["status"] == _NOT_ATTEMPTED:
        return (None, False)
    distribution = row["distribution"]
    proposal = row["proposal"]
    if (
        row["status"] != "routed"
        or distribution is None
        or proposal not in distribution
    ):
        return (fallback, False)
    probability = float(distribution[proposal])
    others = [float(value) for key, value in distribution.items() if key != proposal]
    margin = probability - max(others, default=0.0)
    if accepts(probability, margin, accept_at, min_margin):
        return (proposal, True)
    return (fallback, False)


def conformance(
    rows: Sequence[Row], accept_at: float = 0.70, min_margin: float = 0.10
) -> list[tuple[str, int]]:
    """List the cells where the offline rule and the recorded route disagree."""
    return [
        (str(row["scenario"]), int(row["repeat"]))
        for row in rows
        if (route := route_at(row, accept_at, min_margin)[0]) is not None
        and route != row["route"]
    ]


def errors_at(
    rows: Sequence[Row], accept_at: float, min_margin: float
) -> dict[str, Any]:
    """Count what proceeding, and what stopping, got wrong at one threshold pair."""
    measured = [row for row in rows if row["status"] != _NOT_ATTEMPTED]
    continued = 0
    false_continue = 0
    unsafe_continue = 0
    false_stop = {"fallback": 0, "proposal": 0}
    for row in measured:
        route, decided = route_at(row, accept_at, min_margin)
        expected = row["expected"]
        if decided and route != _HUMAN_REVIEW:
            continued += 1
            if route != expected:
                false_continue += 1
                if expected == _HUMAN_REVIEW:
                    unsafe_continue += 1
        elif route == _HUMAN_REVIEW and expected != _HUMAN_REVIEW:
            false_stop["proposal" if decided else "fallback"] += 1
    return {
        "coverage": continued / len(measured) if measured else 0.0,
        "selective_accuracy": (
            (continued - false_continue) / continued if continued else 0.0
        ),
        "false_continue": false_continue,
        "unsafe_continue": unsafe_continue,
        "false_stop": false_stop,
    }


def sweep(rows: Sequence[Row]) -> list[dict[str, Any]]:
    """Run ``errors_at`` over the whole declared grid: 10 × 5 points."""
    return [
        {"accept_at": accept_at, "min_margin": min_margin}
        | errors_at(rows, accept_at, min_margin)
        for accept_at in _ACCEPT_ATS
        for min_margin in _MIN_MARGINS
    ]


def flip_points(rows: Sequence[Row]) -> dict[str, float | None]:
    """Find, per scenario, where raising the acceptance threshold moves it.

    The comparison is modal-route against modal-route, so a scenario that only
    wobbles between two repeats at one threshold does not count as a flip.
    """
    by_scenario: dict[str, list[Row]] = {}
    for row in rows:
        if row["status"] == _NOT_ATTEMPTED:
            continue
        by_scenario.setdefault(str(row["scenario"]), []).append(row)
    points: dict[str, float | None] = {}
    for scenario in sorted(by_scenario):
        members = by_scenario[scenario]
        baseline = _modal_route(members, _ACCEPT_ATS[0])
        points[scenario] = next(
            (
                accept_at
                for accept_at in _ACCEPT_ATS
                if _modal_route(members, accept_at) != baseline
            ),
            None,
        )
    return points


def boundary(
    hermetic_rows: Sequence[Row],
    frontier_rows: Sequence[Row],
    constants: Mapping[str, Any] = BOUNDARY,
) -> dict[str, Any]:
    """Find the accepted threshold per route, given what the frontier got right.

    The frontier's accuracy is the bar: a route is only trusted where the
    offline rule agrees with the frontier agent it would replace. Only frontier
    cells that actually routed count — one lost to a usage limit must not lower
    the bar.
    """
    min_support = int(constants["min_support"])
    min_scenarios = int(constants["min_distinct_scenarios"])
    max_gap = float(constants["max_accuracy_gap"])
    margin = float(constants["declared_min_margin"])
    measured = [row for row in hermetic_rows if row["status"] != _NOT_ATTEMPTED]
    routed_frontier = [row for row in frontier_rows if row["status"] == "routed"]

    routes: dict[str, dict[str, Any]] = {}
    for route in ROUTES:
        trusted: dict[str, Any] | None = None
        never_enough = True
        largest_support = 0
        for accept_at in _ACCEPT_ATS:
            qualifying = [
                row
                for row in measured
                if route_at(row, accept_at, margin) == (route, True)
            ]
            support = len(qualifying)
            scenarios = {str(row["scenario"]) for row in qualifying}
            largest_support = max(largest_support, support)
            if support >= min_support and len(scenarios) >= min_scenarios:
                never_enough = False
            else:
                continue
            unsafe = sum(
                1
                for row in qualifying
                if row["expected"] == _HUMAN_REVIEW and route != _HUMAN_REVIEW
            )
            accuracy = (
                sum(1 for row in qualifying if row["expected"] == route) / support
            )
            frontier_accuracy = _frontier_accuracy(routed_frontier, scenarios)
            if (
                unsafe == 0
                and frontier_accuracy is not None
                and accuracy >= frontier_accuracy - max_gap
            ):
                proposing = [row for row in measured if row["proposal"] == route]
                trusted = {
                    "status": "trusted",
                    "accept_at": accept_at,
                    "support": support,
                    "scenarios": len(scenarios),
                    "accuracy": accuracy,
                    "frontier_accuracy": frontier_accuracy,
                    "coverage": support / len(proposing) if proposing else 0.0,
                }
                break
        if trusted is not None:
            routes[route] = trusted
        elif never_enough:
            routes[route] = {
                "status": "insufficient evidence",
                "support": largest_support,
            }
        else:
            routes[route] = {"status": "escalate"}

    routed_hermetic = sum(1 for row in hermetic_rows if row["status"] == "routed")
    declared = errors_at(
        hermetic_rows,
        float(constants["declared_accept_at"]),
        float(constants["declared_min_margin"]),
    )
    return {
        "routes": routes,
        "availability": routed_hermetic / len(hermetic_rows) if hermetic_rows else 0.0,
        "unsafe_continue_at_declared": declared["unsafe_continue"],
    }


def verdict(
    boundary_doc: Mapping[str, Any],
    hermetic_rows: Sequence[Row],
    deterministic_rows: Sequence[Row],
    constants: Mapping[str, Any] = BOUNDARY,
) -> tuple[str, str | None]:
    """Turn a boundary document into a decision, and name what stayed unsure."""
    routes = boundary_doc["routes"]
    availability = float(boundary_doc["availability"])
    unsafe = int(boundary_doc["unsafe_continue_at_declared"])
    min_coverage = float(constants["min_coverage"])
    trusted = [route for route in ROUTES if routes[route]["status"] == "trusted"]
    if (
        availability >= float(constants["min_availability"])
        and unsafe == 0
        and any(routes[route]["coverage"] >= min_coverage for route in trusted)
    ):
        return ("adopt", None)
    if not trusted and float(
        accuracy_summary(hermetic_rows)["routed_accuracy"]
    ) < float(accuracy_summary(deterministic_rows)["routed_accuracy"]):
        return ("reject", None)
    parts = [
        f"insufficient evidence on route {route}"
        for route in ROUTES
        if routes[route]["status"] == "insufficient evidence"
    ]
    if availability < float(constants["min_availability"]):
        parts.append(f"availability {availability * 100:.1f} %")
    if unsafe > 0:
        parts.append(f"unsafe-continue on {unsafe} cells")
    parts.extend(
        f"coverage below {min_coverage * 100:.0f} % on trusted route {route}"
        for route in trusted
        if routes[route]["coverage"] < min_coverage
    )
    return ("continue research", "; ".join(parts))


def _modal_route(rows: Sequence[Row], accept_at: float) -> str:
    """The route most repeats take at a threshold, ties broken by ``ROUTES``."""
    counts = Counter(
        route for route, _ in (route_at(row, accept_at, 0.10) for row in rows)
    )
    return max(ROUTES, key=lambda route: counts[route])


def _frontier_accuracy(rows: Sequence[Row], scenarios: set[str]) -> float | None:
    """Share of routed frontier cells on these scenarios that got the route right."""
    selected = [row for row in rows if str(row["scenario"]) in scenarios]
    if not selected:
        return None
    return sum(1 for row in selected if row["route"] == row["expected"]) / len(selected)


def _f1(precision: float, recall: float) -> float:
    """Harmonic mean of precision and recall, zero when both are zero."""
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _bin_index(probability: float) -> int:
    """Return the calibration bin index of a probability in ``[0, 1]``."""
    return min(int(float(probability) * _BINS), _BINS - 1)


def _brier(row: Row) -> float:
    """Squared error of one row's four-route distribution against its label."""
    distribution = row["distribution"]
    return sum(
        (
            float(distribution.get(route, 0.0))
            - (1.0 if route == row["expected"] else 0.0)
        )
        ** 2
        for route in ROUTES
    )


def _needed(row: Row) -> bool:
    """Whether a person's judgement was the right answer for this row."""
    return row["expected"] == _HUMAN_REVIEW or row["proposal"] != row["expected"]


def _usage(row: Row, field: str) -> int:
    """Read one token count out of a row's frontier usage block."""
    frontier = row["frontier"]
    if frontier is None:
        return 0
    usage = frontier.get("usage") or {}
    return int(usage.get(field) or 0)
