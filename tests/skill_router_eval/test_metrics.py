"""The corpus metrics, against hand-computed fixtures.

Every expectation here is arithmetic done by hand on a ledger whose numbers the
test states, so a change in a metric is a change in the expectation rather than
a re-recorded snapshot.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.hermetic_eval.metrics import (
    agreement as phase3_agreement,
)
from tests.hermetic_eval.metrics import (
    cost as phase3_cost,
)
from tests.hermetic_eval.metrics import (
    variance as phase3_variance,
)
from tests.skill_router_eval.metrics import (
    accuracy_summary,
    calibration,
    conformance,
    context_bytes,
    context_summary,
    coverage,
    downstream_summary,
    errors_at,
    native_cost,
    outcome_at,
    proposed_confusion,
    routed_confusion,
    sweep,
    verdict,
    wilson,
)
from tests.skill_router_eval.selection import ESCALATED

SKILLS = ("functualize", "functualize-app", "functualize-cli", "functualize-skill")
UNIFORM = {"functualize": 0.2, "functualize-app": 0.2, "functualize-cli": 0.2,
           "functualize-skill": 0.2, "none": 0.2}
CONFIDENT = {"functualize": 0.01, "functualize-app": 0.01, "functualize-cli": 0.96,
             "functualize-skill": 0.01, "none": 0.01}

def row(**overrides: Any) -> dict[str, Any]:
    """One C-8 row, correct unless the test says otherwise."""
    cell = {
        "cell": "c0",
        "repeat": 0,
        "scenario": "k01",
        "expected": "functualize-cli",
        "stratum": "clear",
        "comparator": "deterministic",
        "status": "routed",
        "route": "functualize-cli",
        "decided_by": "decision",
        "proposal": "functualize-cli",
        "distribution": CONFIDENT,
        "probability": 0.96,
        "margin": 0.95,
        "confidence": 0.96,
        "verdict": "ok",
        "failure": None,
        "rule_digest": "d",
        "latency_seconds": 0.1,
        "input_tokens": 10,
        "output_tokens": 2,
        "frontier": None,
        "native": None,
        "started_at": "2026-10-31T00:00:00Z",
    }
    cell.update(overrides)
    return cell

def test_routed_confusion_is_five_by_six() -> None:
    rows = [
        row(),
        row(expected="none", route=ESCALATED, proposal="none"),
        row(expected="functualize-app", status="not_attempted", route=None),
    ]
    table = routed_confusion(rows)
    assert list(table) == list(SKILLS) + ["none"]
    assert list(table["functualize"]) == [*SKILLS, "none", ESCALATED]
    assert table["functualize-cli"]["functualize-cli"] == 1
    assert table["none"][ESCALATED] == 1
    assert table["functualize-app"][ESCALATED] == 0

def test_proposed_confusion_names_failed() -> None:
    rows = [
        row(proposal="none"),
        row(scenario="k02", status="failed", route=ESCALATED, proposal=None),
    ]
    table = proposed_confusion(rows)
    assert table["functualize-cli"]["none"] == 1
    assert table["functualize-cli"]["failed"] == 1
    assert table["none"]["failed"] == 0

def test_accuracy_counts_escalation_as_wrong() -> None:
    rows = [row(scenario=f"k0{index}") for index in range(3)]
    rows.append(
        row(
            scenario="k04",
            expected="functualize-app",
            route=ESCALATED,
            proposal="functualize-app",
        )
    )
    summary = accuracy_summary(rows)
    assert summary["cells"] == 4
    assert summary["correct"] == 3
    assert summary["routed_accuracy"] == 0.75
    assert summary["per_option"]["functualize-cli"] == {
        "precision": 1.0,
        "recall": 1.0,
        "support": 3,
    }
    assert summary["per_option"]["functualize-app"] == {
        "precision": 0.0,
        "recall": 0.0,
        "support": 1,
    }
    assert summary["macro_f1"] == pytest.approx(0.2)

def test_errors_at_counts_each_of_the_four_errors() -> None:
    rows = [
        row(scenario="k01"),
        row(
            scenario="k02",
            expected="functualize-app",
            route="functualize-cli",
        ),
        row(
            scenario="k03",
            expected="functualize-cli",
            route="none",
            proposal="none",
            distribution={"functualize-cli": 0.01, "none": 0.97},
            probability=0.97,
            margin=0.96,
        ),
        row(
            scenario="k04",
            expected="none",
            route="functualize-app",
            proposal="functualize-app",
            distribution={"functualize-app": 0.9, "none": 0.05},
            probability=0.9,
            margin=0.85,
        ),
        row(
            scenario="k05",
            expected="functualize-cli",
            route=ESCALATED,
            distribution=UNIFORM,
            probability=0.6,
            margin=0.4,
        ),
        row(
            scenario="k06",
            status="failed",
            route=ESCALATED,
            proposal=None,
            distribution=None,
            probability=None,
            margin=None,
        ),
    ]
    counts = errors_at(rows, 0.70, 0.10)
    assert counts["cells"] == 6
    assert counts["accepted"] == 4
    assert counts["wrong_skill"] == 1
    assert counts["unsafe_none"] == 1
    assert counts["over_load"] == 1
    assert counts["false_escalation"] == 1
    assert counts["coverage"] == pytest.approx(4 / 6)
    assert counts["selective_accuracy"] == pytest.approx(1 / 4)

def test_outcome_at_replays_the_gate() -> None:
    assert outcome_at(row()) == "functualize-cli"
    assert outcome_at(row(distribution=UNIFORM, probability=0.60)) == ESCALATED
    assert outcome_at(row(status="failed", distribution=None)) == ESCALATED
    assert outcome_at(row(status="not_attempted", route=None)) == "not_attempted"
    assert outcome_at(row(comparator="native", distribution=None)) == "functualize-cli"

def test_sweep_covers_the_whole_grid() -> None:
    points = sweep([row()])
    assert len(points) == 50
    assert points[0]["accept_at"] == 0.5
    assert points[0]["min_margin"] == 0.0
    assert points[-1]["accept_at"] == pytest.approx(0.95)
    assert points[-1]["min_margin"] == 0.20
    assert all(point["accepted"] == 1 for point in points)

def test_conformance_is_silent_until_the_ledger_is_doctored() -> None:
    rows = [
        row(),
        row(
            scenario="k02",
            distribution={"functualize-cli": 0.8, "none": 0.2},
            probability=0.8,
            margin=0.6,
        ),
    ]
    assert conformance(rows) == []
    doctored = [row(route="functualize-app"), *rows[1:]]
    assert conformance(doctored) == [("k01", 0)]

def test_deterministic_ledger_has_zero_flips() -> None:
    rows = [
        row(scenario=f"k{index:02d}", repeat=repeat)
        for index in range(1, 5)
        for repeat in range(5)
    ]
    measured = phase3_variance(rows)
    assert measured["flips"] == 0
    assert measured["mean_modal_agreement"] == 1.0
    assert phase3_agreement(rows, rows)["kappa"] == 1.0

def test_brier_scores_the_five_option_distribution() -> None:
    distribution = {
        "functualize": 0.5,
        "functualize-app": 0.25,
        "functualize-cli": 0.125,
        "functualize-skill": 0.0625,
        "none": 0.0625,
    }
    scored = calibration(
        [
            row(
                expected="functualize",
                proposal="functualize",
                distribution=distribution,
                probability=0.5,
                margin=0.25,
            )
        ]
    )
    assert scored["n"] == 1
    assert scored["brier"] == pytest.approx(0.3359375)
    assert scored["ece"] == pytest.approx(0.5)
    assert scored["bins"][5]["n"] == 1
    assert scored["bins"][5]["accuracy"] == 1.0
    assert calibration([row(distribution=None, probability=None)])["brier"] is None

def test_coverage_is_the_share_accepting_a_choice() -> None:
    rows = [
        row(scenario="k01"),
        row(scenario="k02", expected="functualize-app", route=ESCALATED),
        row(scenario="k03", status="not_attempted", route=None),
    ]
    measured = coverage(rows)
    assert measured["cells"] == 2
    assert measured["accepted"] == 1
    assert measured["coverage"] == 0.5
    assert measured["selective_accuracy"] == 1.0

def test_native_cost_reads_the_instrument_not_phase_three() -> None:
    rows = [
        row(
            comparator="native",
            distribution=None,
            native={"selected": "functualize", "error": None,
                    "model": "claude-sonnet-5", "cost_usd": 0.0421},
        ),
        row(
            scenario="k02",
            comparator="native",
            distribution=None,
            native={"selected": "functualize", "error": None,
                    "model": "claude-sonnet-5", "cost_usd": 0.0187},
        ),
        row(
            scenario="k03",
            comparator="native",
            distribution=None,
            native={"selected": "functualize", "error": None,
                    "model": "claude-sonnet-5", "cost_usd": None},
        ),
    ]
    priced = native_cost(rows)
    assert priced["cells"] == 3
    assert priced["priced_cells"] == 2
    assert priced["unpriced_cells"] == 1
    assert priced["usd_total"] == 0.0608
    # Why it is not used: Phase 3 prices nothing, so the native arm's own USD
    # would vanish into a confident zero.
    assert phase3_cost(rows)["usd_total"] == 0.0

def test_wilson_interval_brackets_the_share() -> None:
    perfect = wilson(15, 15)
    assert perfect["p"] == 1.0
    assert perfect["hi"] == 1.0
    assert perfect["lo"] == pytest.approx(0.7961, abs=1e-4)
    none = wilson(0, 15)
    assert none["p"] == 0.0
    assert none["lo"] == 0.0
    assert none["hi"] == pytest.approx(0.2039, abs=1e-4)
    assert wilson(0, 0) == {"p": None, "lo": None, "hi": None}

CATALOG = [
    {
        "name": "functualize",
        "description": "abc",
        "sha256": "0",
        "skill_md_bytes": 10,
        "total_bytes": 100,
    },
    {
        "name": "functualize-app",
        "description": "de",
        "sha256": "1",
        "skill_md_bytes": 20,
        "total_bytes": 50,
    },
]

def test_context_bytes_matches_the_hand_computed_sizes() -> None:
    listing = 3 + 2
    assert context_bytes(row(route="functualize"), CATALOG) == {
        "native": listing,
        "load_everything": listing + 150,
        "router": 10 + 3,
    }
    assert context_bytes(row(expected="none", route="none"), CATALOG)["router"] == 0
    escalated = context_bytes(
        row(expected="none", route=ESCALATED, status="failed", distribution=None),
        CATALOG,
    )
    assert escalated["router"] == listing
    native_row = row(comparator="native", route="functualize")
    assert context_bytes(native_row, CATALOG)["router"] == listing

def test_context_summary_ratios_to_native() -> None:
    rows = [
        row(scenario="k01", route="functualize"),
        row(scenario="k02", expected="none", route="none"),
        row(scenario="k03", expected="none", route=ESCALATED),
    ]
    summary = context_summary(rows, CATALOG)
    assert list(summary) == ["deterministic"]
    entry = summary["deterministic"]
    assert entry["cells"] == 3
    assert entry["native"] == 5
    assert entry["router"] == pytest.approx((13 + 0 + 5) / 3)
    assert entry["router_to_native"] == pytest.approx((13 + 0 + 5) / 3 / 5)
    assert entry["load_everything"] == 155
    assert entry["load_everything_to_native"] == pytest.approx(31.0)

def promptfoo_run(arm: str, success: bool, tokens: int | None, cost: float) -> dict[str, Any]:
    return {
        "provider": {"id": "file://evals/providers/claude_agent.py"},
        "vars": {"case": "d1"},
        "success": success,
        "response": {
            "output": {
                "arm": arm,
                "model": "claude-sonnet-5",
                "first_turn_input_tokens": tokens,
                "num_turns": 4,
                "duration_s": 30.0,
            },
            "cost": cost,
        },
    }

def test_downstream_summary_reports_each_arm_and_the_gap() -> None:
    results = {
        "results": {
            "results": [
                promptfoo_run("router", True, 100, 0.10),
                promptfoo_run("router", True, 300, 0.14),
                promptfoo_run("router", False, None, 0.12),
                promptfoo_run("native", True, 1000, 0.30),
                promptfoo_run("native", True, 1200, 0.32),
                promptfoo_run("native", True, 1400, 0.34),
            ]
        }
    }
    summary = downstream_summary(results)
    assert set(summary["arms"]) == {"native", "router"}
    router = summary["arms"]["router"]
    assert router["runs"] == 3
    assert router["success_rate"]["p"] == pytest.approx(2 / 3)
    assert router["success_rate"]["lo"] < router["success_rate"]["p"] < 1.0
    assert router["first_turn_input_tokens_mean"] == 200
    assert router["first_turn_input_tokens_p95"] == 300
    assert router["cost_usd_mean"] == pytest.approx(0.12)
    assert router["turns_mean"] == 4.0
    assert router["duration_s_mean"] == 30.0
    assert summary["router_minus_native"] == pytest.approx(2 / 3 - 1)
    assert summary["models"] == ["claude-sonnet-5"]

def test_downstream_summary_reads_a_bare_run_list() -> None:
    summary = downstream_summary([promptfoo_run("native", True, 10, 0.01)])
    assert summary["arms"]["native"]["successes"] == 1
    assert summary["router_minus_native"] is None

def test_verdict_promotes_when_every_condition_holds() -> None:
    hermetic = [row(scenario=f"k{index:02d}") for index in range(1, 21)]
    deterministic = [
        *hermetic[:10],
        *[
            row(scenario=f"k{index:02d}", route="functualize-app")
            for index in range(11, 21)
        ],
    ]
    result = verdict(
        hermetic,
        deterministic,
        router_context_bytes=600.0,
        native_context_bytes=2000.0,
        downstream_router_success=0.9,
        downstream_native_success=0.8,
    )
    assert result["verdict"] == "promote to Phase 5"
    assert result["detail"]["lead"] == pytest.approx(0.5)
    assert result["conditions"] == {
        "e2": True,
        "unsafe_none": True,
        "context": True,
        "downstream": True,
    }

def test_verdict_is_negative_without_the_lead() -> None:
    hermetic = [
        *[row(scenario=f"k{index:02d}") for index in range(1, 11)],
        *[
            row(scenario=f"k{index:02d}", route=ESCALATED)
            for index in range(11, 21)
        ],
    ]
    deterministic = [
        *hermetic[:10],
        *[
            row(scenario=f"k{index:02d}", route="functualize-app")
            for index in range(11, 21)
        ],
    ]
    result = verdict(
        hermetic,
        deterministic,
        router_context_bytes=600.0,
        native_context_bytes=2000.0,
        downstream_router_success=0.9,
        downstream_native_success=0.8,
    )
    assert result["verdict"] == "negative result"
    assert result["detail"]["lead"] == 0.0

def test_verdict_names_every_failed_condition() -> None:
    hermetic = [row(scenario=f"k{index:02d}") for index in range(1, 21)]
    deterministic = [
        *hermetic[:10],
        *[
            row(scenario=f"k{index:02d}", route="functualize-app")
            for index in range(11, 21)
        ],
    ]
    result = verdict(
        hermetic,
        deterministic,
        router_context_bytes=2500.0,
        native_context_bytes=2000.0,
        downstream_router_success=0.8,
        downstream_native_success=0.9,
    )
    assert result["verdict"] == "continue research"
    assert result["failed"] == ["context", "downstream"]

def test_one_unsafe_none_stops_promotion() -> None:
    hermetic = [
        *[row(scenario=f"k{index:02d}") for index in range(2, 21)],
        row(
            scenario="k01",
            route="none",
            proposal="none",
            distribution={"functualize-cli": 0.01, "none": 0.97},
            probability=0.97,
            margin=0.96,
        ),
    ]
    deterministic = [
        *hermetic[:10],
        *[
            row(scenario=f"k{index:02d}", route="functualize-app")
            for index in range(11, 21)
        ],
    ]
    result = verdict(
        hermetic,
        deterministic,
        router_context_bytes=600.0,
        native_context_bytes=2000.0,
        downstream_router_success=0.9,
        downstream_native_success=0.8,
    )
    assert result["detail"]["hermetic_unsafe_none"] == 1
    assert result["verdict"] == "continue research"
    assert result["failed"] == ["unsafe_none"]
