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


_ADOPT_DISTRIBUTION = {"deterministic": 0.85, "cheap_model": 0.15}


def _proposed_cell(
    scenario: str,
    repeat: int,
    *,
    expected: str = "deterministic",
    proposal: str = "deterministic",
    probability: float = 0.85,
    status: str = "routed",
) -> dict[str, Any]:
    """One cell that proposes ``deterministic`` at 0.85, correct by default."""
    distribution = (
        {proposal: probability, "cheap_model": round(1.0 - probability, 4)}
        if status == "routed"
        else None
    )
    return _row(
        scenario=scenario,
        repeat=repeat,
        expected=expected,
        status=status,
        route=proposal if status == "routed" else "human_review",
        decided_by="decision" if status == "routed" else "fallback",
        proposal=proposal if status == "routed" else None,
        distribution=distribution,
        probability=probability if status == "routed" else None,
        margin=0.70 if status == "routed" else None,
    )


def _grid(scenarios: int, repeats: int, **kwargs: Any) -> list[dict[str, Any]]:
    return [
        _proposed_cell(f"s{index}", repeat, **kwargs)
        for index in range(1, scenarios + 1)
        for repeat in range(1, repeats + 1)
    ]


def _frontier_twin(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same keys, answered by the frontier agent, all routed."""
    return [
        _row(
            scenario=row["scenario"],
            repeat=row["repeat"],
            expected=row["expected"],
            status="routed",
            route=row["expected"],
            decided_by="decision",
            proposal=row["expected"],
            distribution={row["expected"]: 0.9},
            probability=0.9,
            margin=0.8,
        )
        for row in rows
    ]


def test_conformance_is_empty_for_the_reference_ledger() -> None:
    assert metrics.conformance(_fixture_a()) == []


def test_conformance_names_a_cell_whose_route_moved() -> None:
    rows = _fixture_a()
    rows[3] = rows[3] | {"route": "human_review", "decided_by": "fallback"}
    assert metrics.conformance(rows) == [("s4", 1)]


def test_conformance_ignores_a_never_attempted_cell() -> None:
    rows = _fixture_a() + [_row(scenario="s7", status="not_attempted", route=None)]
    assert metrics.conformance(rows) == []


def test_errors_at_the_declared_point() -> None:
    errors = metrics.errors_at(_fixture_a(), 0.70, 0.10)
    assert errors["coverage"] == pytest.approx(0.6667, abs=1e-4)
    assert errors["false_continue"] == 2
    assert errors["unsafe_continue"] == 1
    assert errors["false_stop"] == {"fallback": 1, "proposal": 0}
    assert errors["selective_accuracy"] == 0.5


def test_errors_at_a_stricter_point() -> None:
    errors = metrics.errors_at(_fixture_a(), 0.75, 0.10)
    assert errors["coverage"] == pytest.approx(0.5, abs=1e-4)
    assert errors["false_continue"] == 1
    assert errors["unsafe_continue"] == 0
    assert errors["false_stop"] == {"fallback": 1, "proposal": 0}


def test_accepts_compares_both_thresholds_exactly() -> None:
    assert metrics.accepts(0.70, 0.10, 0.70, 0.10)
    assert not metrics.accepts(0.6999999, 0.10, 0.70, 0.10)
    assert not metrics.accepts(0.70, 0.0999999, 0.70, 0.10)


def test_route_at_reports_the_fallback_separately_from_the_decision() -> None:
    assert metrics.route_at(_fixture_a()[0], 0.70, 0.10) == ("deterministic", True)
    assert metrics.route_at(_fixture_a()[4], 0.70, 0.10) == ("human_review", False)
    assert metrics.route_at(_fixture_a()[5], 0.70, 0.10) == ("human_review", False)
    assert metrics.route_at(_fixture_a()[0], 0.95, 0.10) == ("human_review", False)
    never = _row(scenario="s8", status="not_attempted", route=None)
    assert metrics.route_at(never, 0.70, 0.10) == (None, False)
    fallback = metrics.route_at(_fixture_a()[0], 0.95, 0.10, fallback="cheap_model")
    assert fallback == ("cheap_model", False)


def test_sweep_covers_the_declared_grid() -> None:
    points = metrics.sweep(_fixture_a())
    assert len(points) == 50
    assert [(p["accept_at"], p["min_margin"]) for p in points[:5]] == [
        (0.50, 0.00),
        (0.50, 0.05),
        (0.50, 0.10),
        (0.50, 0.15),
        (0.50, 0.20),
    ]
    assert (points[-1]["accept_at"], points[-1]["min_margin"]) == (0.95, 0.20)
    assert [p["accept_at"] for p in points[::5]] == [
        round(0.50 + 0.05 * index, 2) for index in range(10)
    ]
    assert set(points[0]) == {
        "accept_at",
        "min_margin",
        "coverage",
        "selective_accuracy",
        "false_continue",
        "unsafe_continue",
        "false_stop",
    }


def test_flip_points_are_where_the_threshold_crosses_a_proposal() -> None:
    assert metrics.flip_points(_fixture_a()) == {
        "s1": 0.95,
        "s2": 0.80,
        "s3": 0.85,
        "s4": 0.75,
        "s5": 0.65,
        "s6": None,
    }


def test_boundary_trusts_a_route_the_frontier_also_gets_right() -> None:
    hermetic = _grid(4, 3)
    document = metrics.boundary(hermetic, _frontier_twin(hermetic))
    assert document["availability"] == 1.0
    assert document["unsafe_continue_at_declared"] == 0
    assert document["routes"]["deterministic"] == {
        "status": "trusted",
        "accept_at": 0.50,
        "support": 12,
        "scenarios": 4,
        "accuracy": 1.0,
        "frontier_accuracy": 1.0,
        "coverage": 1.0,
    }
    assert metrics.verdict(document, hermetic, _frontier_twin(hermetic)) == (
        "adopt",
        None,
    )


def test_boundary_reports_insufficient_evidence_below_the_floors() -> None:
    nine = _grid(3, 3)
    assert metrics.boundary(nine, [])["routes"]["deterministic"] == {
        "status": "insufficient evidence",
        "support": 9,
    }
    twelve = _grid(3, 4)
    assert metrics.boundary(twelve, [])["routes"]["deterministic"] == {
        "status": "insufficient evidence",
        "support": 12,
    }


def test_boundary_escalates_when_the_offline_rule_is_wrong() -> None:
    hermetic = _grid(4, 3, expected="cheap_model")
    document = metrics.boundary(hermetic, _frontier_twin(_grid(4, 3)))
    assert document["routes"]["deterministic"] == {"status": "escalate"}
    assert metrics.verdict(document, hermetic, _frontier_twin(_grid(4, 3))) == (
        "reject",
        None,
    )


def test_verdict_continues_when_availability_is_below_the_floor() -> None:
    hermetic = _grid(4, 3) + [
        _proposed_cell("s5", 1, status="failed"),
        _proposed_cell("s5", 2, status="failed"),
    ]
    document = metrics.boundary(hermetic, _frontier_twin(_grid(4, 3)))
    assert document["availability"] == pytest.approx(0.8571, abs=1e-4)
    assert document["routes"]["deterministic"]["status"] == "trusted"
    verdict, uncertainty = metrics.verdict(
        document, hermetic, _frontier_twin(_grid(4, 3))
    )
    assert verdict == "continue research"
    assert uncertainty is not None
    assert "availability 85.7 %" in uncertainty
