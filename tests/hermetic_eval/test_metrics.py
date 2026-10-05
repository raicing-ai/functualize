"""Offline tests for the descriptive routing metrics."""

from __future__ import annotations

from typing import Any

import pytest

from tests.hermetic_eval import metrics
from tests.hermetic_eval.corpus import ROUTES


def _row(**overrides: Any) -> dict[str, Any]:
    """Build a ledger row, defaulting to one correct deterministic cell."""
    row: dict[str, Any] = {
        "scenario": "s1",
        "repeat": 1,
        "expected": "deterministic",
        "stratum": "clear",
        "status": "routed",
        "route": "deterministic",
        "decided_by": "decision",
        "proposal": "deterministic",
        "distribution": {"deterministic": 0.9, "cheap_model": 0.1},
        "probability": 0.9,
        "margin": 0.8,
        "confidence": None,
        "latency_seconds": 1.0,
        "input_tokens": None,
        "output_tokens": None,
        "frontier": None,
    }
    row.update(overrides)
    return row


def _fixture_a() -> list[dict[str, Any]]:
    """The six-row mixed ledger from the task description."""
    return [
        _row(scenario="s1"),
        _row(
            scenario="s2",
            expected="cheap_model",
            route="cheap_model",
            proposal="cheap_model",
            distribution={"cheap_model": 0.75, "deterministic": 0.25},
            probability=0.75,
            margin=0.5,
            latency_seconds=2.0,
        ),
        _row(
            scenario="s3",
            expected="frontier_agent",
            route="cheap_model",
            proposal="cheap_model",
            distribution={"cheap_model": 0.8, "frontier_agent": 0.2},
            probability=0.8,
            margin=0.6,
            latency_seconds=3.0,
        ),
        _row(
            scenario="s4",
            expected="human_review",
            route="deterministic",
            proposal="deterministic",
            distribution={"deterministic": 0.72, "human_review": 0.28},
            probability=0.72,
            margin=0.44,
            latency_seconds=4.0,
        ),
        _row(
            scenario="s5",
            route="human_review",
            decided_by="fallback",
            distribution={"deterministic": 0.6, "cheap_model": 0.4},
            probability=0.6,
            margin=0.2,
            latency_seconds=5.0,
        ),
        _row(
            scenario="s6",
            expected="human_review",
            status="failed",
            route="human_review",
            decided_by="fallback",
            proposal=None,
            distribution=None,
            probability=None,
            margin=None,
            latency_seconds=0.1,
        ),
    ]


def test_routed_confusion_counts_expected_by_route() -> None:
    table = metrics.routed_confusion(_fixture_a())
    assert table["human_review"] == {
        "deterministic": 1,
        "human_review": 1,
        "cheap_model": 0,
        "frontier_agent": 0,
    }
    assert set(table) == set(ROUTES)
    assert table["deterministic"]["deterministic"] == 1
    assert sum(sum(bucket.values()) for bucket in table.values()) == 6


def test_proposed_confusion_marks_missing_proposals_failed() -> None:
    table = metrics.proposed_confusion(_fixture_a())
    assert table["human_review"] == {"deterministic": 1, "failed": 1}
    assert table["frontier_agent"] == {"cheap_model": 1}


def test_accuracy_summary_reports_the_hand_computed_values() -> None:
    summary = metrics.accuracy_summary(_fixture_a())
    assert summary["cells"] == 6
    assert summary["availability"] == pytest.approx(0.8333, abs=1e-4)
    assert summary["routed_accuracy"] == pytest.approx(0.5, abs=1e-4)
    assert summary["macro_f1"] == pytest.approx(0.4167, abs=1e-4)
    assert summary["per_route"]["cheap_model"]["precision"] == pytest.approx(
        0.5, abs=1e-4
    )
    assert summary["per_route"]["cheap_model"]["recall"] == pytest.approx(1.0, abs=1e-4)
    assert summary["per_route"]["cheap_model"]["support"] == 1


def test_calibration_reports_the_hand_computed_values() -> None:
    summary = metrics.calibration(_fixture_a())
    assert summary["ece"] == pytest.approx(0.354, abs=1e-4)
    assert summary["brier"] == pytest.approx(0.5564, abs=1e-4)
    bin_7 = summary["bins"][7]
    assert (bin_7["lo"], bin_7["hi"], bin_7["n"]) == (0.7, 0.8, 2)
    assert bin_7["mean_p"] == pytest.approx(0.735, abs=1e-4)
    assert bin_7["accuracy"] == pytest.approx(0.5, abs=1e-4)


def test_calibration_without_probabilities_has_no_brier() -> None:
    summary = metrics.calibration(_fixture_a(), key="margin")
    assert summary["brier"] is None
    assert len(summary["bins"]) == 10


def test_escalation_reports_the_hand_computed_values() -> None:
    summary = metrics.escalation(_fixture_a())
    assert summary["coverage"] == pytest.approx(0.6667, abs=1e-4)
    assert summary["selective_accuracy"] == pytest.approx(0.5, abs=1e-4)
    assert summary["precision"] == pytest.approx(0.5, abs=1e-4)
    assert summary["recall"] == pytest.approx(0.3333, abs=1e-4)
    assert summary["by_cause"] == {"fallback": 2, "proposal": 0}


def test_latency_uses_nearest_rank() -> None:
    summary = metrics.latency(_fixture_a())
    assert summary["p50"] == pytest.approx(2.0, abs=1e-4)
    assert summary["p95"] == pytest.approx(5.0, abs=1e-4)
    assert summary["max"] == pytest.approx(5.0, abs=1e-4)


def test_agreement_matches_cohens_kappa() -> None:
    routes_a = ["deterministic", "cheap_model", "human_review", "human_review"]
    routes_b = ["deterministic", "cheap_model", "human_review", "deterministic"]
    rows_a = [
        _row(scenario=f"s{index}", route=route) for index, route in enumerate(routes_a)
    ]
    rows_b = [
        _row(scenario=f"s{index}", route=route) for index, route in enumerate(routes_b)
    ]
    summary = metrics.agreement(rows_a, rows_b)
    assert summary["rate"] == pytest.approx(0.75, abs=1e-4)
    assert summary["kappa"] == pytest.approx(0.6364, abs=1e-4)


def test_cost_sums_tokens_and_never_invents_a_price() -> None:
    frontier_rows = [
        _row(
            scenario="s1",
            input_tokens=300,
            output_tokens=40,
            frontier={
                "cost_usd": 0.0,
                "usage": {"cached_input_tokens": 100, "reasoning_output_tokens": 20},
            },
        ),
        _row(
            scenario="s2",
            expected="cheap_model",
            route="deterministic",
            input_tokens=500,
            output_tokens=60,
            frontier={
                "cost_usd": 0.0,
                "usage": {"cached_input_tokens": 0, "reasoning_output_tokens": 30},
            },
        ),
    ]
    summary = metrics.cost(frontier_rows)
    assert summary["input_tokens"] == 800
    assert summary["output_tokens"] == 100
    assert summary["cached_input_tokens"] == 100
    assert summary["reasoning_output_tokens"] == 50
    assert summary["tokens_per_correct_route"] == pytest.approx(900, abs=1e-4)
    assert summary["usd_total"] is None

    priced = metrics.cost([_row(), _row(scenario="s2", route="cheap_model")])
    assert priced["usd_total"] == 0.0
    assert priced["tokens_per_correct_route"] == pytest.approx(0.0, abs=1e-4)


def test_not_attempted_rows_are_excluded_but_count_as_wrong() -> None:
    rows = [
        _row(),
        _row(
            scenario="s2",
            status="not_attempted",
            route=None,
            proposal=None,
            distribution=None,
            probability=None,
            margin=None,
            latency_seconds=99.0,
        ),
    ]
    assert metrics.latency(rows)["p50"] == pytest.approx(1.0, abs=1e-4)
    table = metrics.routed_confusion(rows)
    assert sum(sum(bucket.values()) for bucket in table.values()) == 1
    assert metrics.accuracy_summary(rows)["routed_accuracy"] == pytest.approx(
        0.5, abs=1e-4
    )


def test_variance_reports_flips_and_probability_spread() -> None:
    rows = [
        _row(scenario="a", repeat=1, probability=0.8),
        _row(scenario="a", repeat=2, probability=0.7),
        _row(scenario="a", repeat=3, route="human_review", probability=0.6),
        _row(
            scenario="b",
            repeat=1,
            expected="cheap_model",
            route="cheap_model",
            probability=0.9,
        ),
        _row(
            scenario="b",
            repeat=2,
            expected="cheap_model",
            route="cheap_model",
            probability=0.9,
        ),
        _row(
            scenario="b",
            repeat=3,
            expected="cheap_model",
            route="cheap_model",
            probability=0.9,
        ),
    ]
    summary = metrics.variance(rows)
    assert summary["mean_modal_agreement"] == pytest.approx(0.8333, abs=1e-4)
    assert summary["flips"] == 1
    assert summary["flipped"] == ["a"]
    assert summary["mean_probability_sd"] == pytest.approx(0.0408, abs=1e-4)


def test_variance_is_zero_on_a_deterministic_ledger() -> None:
    rows = [_row(scenario="a", repeat=index, probability=1.0) for index in (1, 2, 3)]
    summary = metrics.variance(rows)
    assert summary["flips"] == 0
    assert summary["mean_probability_sd"] == pytest.approx(0.0, abs=1e-4)
