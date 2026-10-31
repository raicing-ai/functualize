"""Descriptive metrics over a skill-router measurement ledger.

Every function is pure: no I/O, no clock, no network. A row is a ``dict``
carrying the C-8 keys — ``cell repeat scenario expected stratum comparator
status route decided_by proposal distribution probability margin confidence
verdict failure rule_digest latency_seconds input_tokens output_tokens
frontier native started_at``. Rows whose ``status`` is ``not_attempted`` were
never measured: they count as wrong in ``routed_accuracy`` (the denominator is
every cell) and are excluded from every confusion, calibration and latency
figure.

Phase 3's generic functions are imported rather than copied: ``accepts`` is the
gate rule the report must replay, and ``agreement``, ``variance``, ``latency``
and ``cost`` are unchanged because the row keys they read are unchanged. What
is *not* reused is anything that assumes Phase 3's four routes or a price: the
option set here is the five catalog options plus ``escalated``, and native USD
comes from the instrument's own ``native`` block, never from ``cost`` (which
prices nothing, F-15).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from tests.hermetic_eval.metrics import accepts
from tests.skill_router_eval.catalog import NONE, OPTIONS, SKILLS
from tests.skill_router_eval.corpus import DECLARED, VERDICT
from tests.skill_router_eval.selection import ESCALATED

Row = Mapping[str, Any]
Catalog = Mapping[str, Any] | Sequence[Any]

__all__ = [
    "accuracy_summary",
    "calibration",
    "conformance",
    "context_bytes",
    "context_summary",
    "coverage",
    "downstream_summary",
    "errors_at",
    "native_cost",
    "outcome_at",
    "proposed_confusion",
    "routed_confusion",
    "sweep",
    "verdict",
    "wilson",
]

SELECTED = (*OPTIONS, ESCALATED)
"""Every value ``selected`` can take: the five options, plus escalation."""

_FAILED = "failed"
_NOT_ATTEMPTED = "not_attempted"
_BINS = 10
_Z95 = 1.96
_ACCEPT_ATS = tuple(round(0.50 + 0.05 * index, 2) for index in range(10))
_MIN_MARGINS = (0.00, 0.05, 0.10, 0.15, 0.20)

def routed_confusion(rows: Sequence[Row]) -> dict[str, dict[str, int]]:
    """Count expected → selected over measured cells: five rows, six columns."""
    table: dict[str, dict[str, int]] = {
        expected: {selected: 0 for selected in SELECTED} for expected in OPTIONS
    }
    for row in rows:
        if row["status"] == _NOT_ATTEMPTED:
            continue
        table[row["expected"]][_selected(row)] += 1
    return table

def proposed_confusion(rows: Sequence[Row]) -> dict[str, dict[str, int]]:
    """Count expected → proposal, with a ``failed`` column for no proposal."""
    table: dict[str, dict[str, int]] = {
        expected: {**{option: 0 for option in OPTIONS}, _FAILED: 0}
        for expected in OPTIONS
    }
    for row in rows:
        if row["status"] == _NOT_ATTEMPTED:
            continue
        proposal = row["proposal"] if row["proposal"] is not None else _FAILED
        table[row["expected"]][proposal] += 1
    return table

def accuracy_summary(rows: Sequence[Row]) -> dict[str, Any]:
    """Routed accuracy, per-option precision/recall and macro-F1.

    Routed accuracy divides by every cell, so an escalated or failed cell is
    wrong. Precision and recall are scored over the five options only:
    escalation is a refusal to choose, not a sixth class.
    """
    cells = len(rows)
    correct = sum(1 for row in rows if _selected(row) == row["expected"])
    measured = [row for row in rows if row["status"] != _NOT_ATTEMPTED]
    per_option: dict[str, dict[str, Any]] = {}
    for option in OPTIONS:
        taken = [row for row in measured if _selected(row) == option]
        actual = [row for row in measured if row["expected"] == option]
        hits = [
            row
            for row in measured
            if _selected(row) == option and row["expected"] == option
        ]
        per_option[option] = {
            "precision": len(hits) / len(taken) if taken else 0.0,
            "recall": len(hits) / len(actual) if actual else 0.0,
            "support": len(actual),
        }
    return {
        "cells": cells,
        "correct": correct,
        "routed_accuracy": correct / cells if cells else 0.0,
        "macro_f1": _macro_f1(per_option),
        "per_option": per_option,
    }

def outcome_at(
    row: Row,
    accept_at: float = DECLARED["accept_at"],
    min_margin: float = DECLARED["min_margin"],
) -> str:
    """Replay one cell's decision at a threshold pair.

    A failed cell has no distribution to accept and is ``escalated``, which is
    what the walk does with it. A native cell was never gated — its recorded
    route is its outcome at every threshold.
    """
    if row["status"] == _NOT_ATTEMPTED:
        return _NOT_ATTEMPTED
    if row["comparator"] == "native":
        return _selected(row)
    distribution = row["distribution"]
    proposal = row["proposal"]
    if (
        row["status"] != "routed"
        or distribution is None
        or proposal not in distribution
    ):
        return ESCALATED
    probability = float(distribution[proposal])
    others = [float(value) for key, value in distribution.items() if key != proposal]
    margin = probability - max(others, default=0.0)
    return proposal if accepts(probability, margin, accept_at, min_margin) else ESCALATED

def errors_at(
    rows: Sequence[Row],
    accept_at: float = DECLARED["accept_at"],
    min_margin: float = DECLARED["min_margin"],
) -> dict[str, Any]:
    """Count the four B-13 selection errors at one threshold pair.

    ``wrong_skill`` is a skill accepted where a different one was expected;
    ``unsafe_none`` is ``none`` accepted where a skill was expected (blocking);
    ``over_load`` is a skill accepted where ``none`` was expected;
    ``false_escalation`` is escalation where the proposal was already right.
    """
    measured = [row for row in rows if row["status"] != _NOT_ATTEMPTED]
    accepted = wrong_skill = unsafe_none = over_load = false_escalation = 0
    for row in measured:
        outcome = outcome_at(row, accept_at, min_margin)
        expected = row["expected"]
        if outcome in OPTIONS:
            accepted += 1
            if outcome == NONE and expected in SKILLS:
                unsafe_none += 1
            elif outcome in SKILLS and expected == NONE:
                over_load += 1
            elif outcome in SKILLS and expected in SKILLS and outcome != expected:
                wrong_skill += 1
        elif outcome == ESCALATED and row["proposal"] == expected:
            false_escalation += 1
    return {
        "cells": len(measured),
        "accepted": accepted,
        "coverage": accepted / len(measured) if measured else 0.0,
        "selective_accuracy": (
            (accepted - wrong_skill - unsafe_none - over_load) / accepted
            if accepted
            else None
        ),
        "wrong_skill": wrong_skill,
        "unsafe_none": unsafe_none,
        "over_load": over_load,
        "false_escalation": false_escalation,
    }

def coverage(rows: Sequence[Row]) -> dict[str, Any]:
    """B-14: the share of cells accepted, and the accuracy of those cells."""
    measured = [row for row in rows if row["status"] != _NOT_ATTEMPTED]
    accepted = [row for row in measured if _selected(row) in OPTIONS]
    return {
        "cells": len(measured),
        "accepted": len(accepted),
        "coverage": len(accepted) / len(measured) if measured else 0.0,
        "selective_accuracy": (
            sum(1 for row in accepted if _selected(row) == row["expected"])
            / len(accepted)
            if accepted
            else None
        ),
    }

def calibration(rows: Sequence[Row], key: str = "probability") -> dict[str, Any]:
    """Ten-bin calibration and ECE, with a Brier score over the five options.

    The Brier score never reads ``confidence``: it scores the distribution the
    provider produced against the labelled option.
    """
    scored = [
        row
        for row in rows
        if row["status"] != _NOT_ATTEMPTED and row[key] is not None
    ]
    bins: list[dict[str, Any]] = []
    for index in range(_BINS):
        members = [row for row in scored if _bin_index(float(row[key])) == index]
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
            entry["n"] / len(scored) * abs(entry["accuracy"] - entry["mean_p"])
            for entry in bins
            if entry["n"]
        )
        if scored
        else None
    )
    return {"bins": bins, "ece": ece, "brier": _brier(scored), "n": len(scored)}

def sweep(rows: Sequence[Row]) -> list[dict[str, Any]]:
    """Run ``errors_at`` over the declared grid: 10 × 5 points."""
    return [
        {"accept_at": accept_at, "min_margin": min_margin}
        | errors_at(rows, accept_at, min_margin)
        for accept_at in _ACCEPT_ATS
        for min_margin in _MIN_MARGINS
    ]

def conformance(
    rows: Sequence[Row],
    accept_at: float = DECLARED["accept_at"],
    min_margin: float = DECLARED["min_margin"],
) -> list[tuple[str, int]]:
    """List the cells where the offline rule and the recorded outcome disagree."""
    return [
        (str(row["scenario"]), int(row["repeat"]))
        for row in rows
        if (outcome := outcome_at(row, accept_at, min_margin)) != _NOT_ATTEMPTED
        and outcome != _selected(row)
    ]

def context_bytes(row: Row, catalog: Catalog) -> dict[str, int]:
    """B-18: bytes in context before the first turn, for each of the three arms.

    Native sees the four descriptions. Load-everything sees those plus every
    skill file. The router sees its accepted skill's ``SKILL.md`` and
    description, nothing for an accepted ``none``, and the native listing for
    an escalated or failed cell.
    """
    listing, everything, by_name = _catalog_sizes(catalog)
    selected = _selected(row)
    if row["comparator"] == "native" or selected == ESCALATED:
        router = listing
    elif selected == NONE:
        router = 0
    elif selected in by_name:
        skill_md_bytes, description_bytes = by_name[selected]
        router = skill_md_bytes + description_bytes
    else:
        router = listing
    return {"native": listing, "load_everything": everything, "router": router}

def context_summary(rows: Sequence[Row], catalog: Catalog) -> dict[str, dict[str, Any]]:
    """Mean per-cell context bytes and the ratio to native, per comparator."""
    by_comparator: dict[str, list[Row]] = {}
    for row in rows:
        if row["status"] != _NOT_ATTEMPTED:
            by_comparator.setdefault(str(row["comparator"]), []).append(row)
    summary: dict[str, dict[str, Any]] = {}
    for comparator in sorted(by_comparator):
        members = by_comparator[comparator]
        totals = {
            arm: math.fsum(
                float(context_bytes(row, catalog)[arm]) for row in members
            )
            for arm in ("native", "load_everything", "router")
        }
        means = {arm: total / len(members) for arm, total in totals.items()}
        summary[comparator] = {
            "cells": len(members),
            "native": means["native"],
            "load_everything": means["load_everything"],
            "router": means["router"],
            "router_to_native": (
                means["router"] / means["native"] if means["native"] else None
            ),
            "load_everything_to_native": (
                means["load_everything"] / means["native"] if means["native"] else None
            ),
        }
    return summary

def wilson(successes: int, n: int, z: float = _Z95) -> dict[str, float | None]:
    """The 95 % Wilson score interval for a binomial share."""
    if n <= 0:
        return {"p": None, "lo": None, "hi": None}
    p = successes / n
    denominator = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return {"p": p, "lo": max(0.0, centre - half), "hi": min(1.0, centre + half)}

def downstream_summary(results: Mapping[str, Any] | Sequence[Any]) -> dict[str, Any]:
    """B-23: per-arm downstream success, tokens, cost, turns and duration.

    ``results`` is the parsed promptfoo results JSON (or just its run list).
    Each run's provider output is the ``claude_agent`` dict; the arm and the
    observed model come from there, because that is what actually ran.
    """
    by_arm: dict[str, list[Mapping[str, Any]]] = {}
    models: set[str] = set()
    for entry in _runs(results):
        run = _run_record(entry)
        by_arm.setdefault(str(run["arm"]), []).append(run)
        if run["model"]:
            models.add(str(run["model"]))
    arms: dict[str, dict[str, Any]] = {}
    for arm in sorted(by_arm):
        runs = by_arm[arm]
        successes = sum(1 for run in runs if run["success"])
        tokens = [
            float(run["first_turn_input_tokens"])
            for run in runs
            if run.get("first_turn_input_tokens") is not None
        ]
        costs = [float(run["cost_usd"]) for run in runs if run.get("cost_usd") is not None]
        turns = [float(run["num_turns"]) for run in runs if run.get("num_turns")]
        durations = [
            float(run["duration_s"]) for run in runs if run.get("duration_s") is not None
        ]
        arms[arm] = {
            "runs": len(runs),
            "successes": successes,
            "success_rate": wilson(successes, len(runs)),
            "first_turn_input_tokens_mean": _mean(tokens),
            "first_turn_input_tokens_p95": _p95(tokens),
            "cost_usd_mean": _mean(costs),
            "turns_mean": _mean(turns),
            "duration_s_mean": _mean(durations),
        }
    router = arms.get("router", {}).get("success_rate", {})
    native = arms.get("native", {}).get("success_rate", {})
    return {
        "arms": arms,
        "router_minus_native": (
            router["p"] - native["p"]
            if router.get("p") is not None and native.get("p") is not None
            else None
        ),
        "models": sorted(models),
    }

def native_cost(rows: Sequence[Row]) -> dict[str, Any]:
    """Sum the instrument's own USD for native cells.

    A cell the instrument did not price counts as ``unpriced_cells`` and is
    never imputed. Phase 3's ``cost`` is not used here: it prices nothing.
    """
    native = [row for row in rows if row["native"] is not None]
    prices = [
        float(entry["cost_usd"])
        for entry in (row["native"] for row in native)
        if entry.get("cost_usd") is not None
    ]
    return {
        "cells": len(native),
        "priced_cells": len(prices),
        "unpriced_cells": len(native) - len(prices),
        "usd_total": math.fsum(prices),
    }

def verdict(
    hermetic_rows: Sequence[Row],
    deterministic_rows: Sequence[Row],
    *,
    router_context_bytes: float | None,
    native_context_bytes: float | None,
    downstream_router_success: float | None,
    downstream_native_success: float | None,
    accept_at: float = DECLARED["accept_at"],
    min_margin: float = DECLARED["min_margin"],
    min_lead: float = VERDICT["min_lead"],
    max_unsafe_none: int = VERDICT["max_unsafe_none"],
) -> dict[str, Any]:
    """B-24: the verdict, computed by rule at the declared point.

    E2 (the hermetic comparator leads the keyword table by ``min_lead``) gates
    everything: without it the result is negative and nothing is promoted.
    """
    hermetic_accuracy = accuracy_summary(hermetic_rows)["routed_accuracy"]
    deterministic_accuracy = accuracy_summary(deterministic_rows)["routed_accuracy"]
    lead = hermetic_accuracy - deterministic_accuracy
    unsafe_none = errors_at(hermetic_rows, accept_at, min_margin)["unsafe_none"]
    ratio = (
        router_context_bytes / native_context_bytes
        if router_context_bytes is not None and native_context_bytes
        else None
    )
    conditions = {
        "e2": lead >= float(min_lead),
        "unsafe_none": unsafe_none <= int(max_unsafe_none),
        "context": ratio is not None and ratio < 1.0,
        "downstream": (
            downstream_router_success is not None
            and downstream_native_success is not None
            and downstream_router_success >= downstream_native_success
        ),
    }
    detail = {
        "hermetic_accuracy": hermetic_accuracy,
        "deterministic_accuracy": deterministic_accuracy,
        "lead": lead,
        "min_lead": float(min_lead),
        "hermetic_unsafe_none": unsafe_none,
        "max_unsafe_none": int(max_unsafe_none),
        "router_context_bytes": router_context_bytes,
        "native_context_bytes": native_context_bytes,
        "context_ratio": ratio,
        "downstream_router_success": downstream_router_success,
        "downstream_native_success": downstream_native_success,
    }
    if not conditions["e2"]:
        return {"verdict": "negative result", "conditions": conditions, "detail": detail}
    failed = [name for name, held in conditions.items() if not held]
    if not failed:
        return {
            "verdict": "promote to Phase 5",
            "conditions": conditions,
            "detail": detail,
        }
    return {
        "verdict": "continue research",
        "conditions": conditions,
        "failed": failed,
        "detail": detail,
    }

def _selected(row: Row) -> str:
    """The cell's outcome: its recorded route, or ``escalated`` when there is none."""
    route = row["route"]
    return ESCALATED if route is None else str(route)

def _macro_f1(per_option: Mapping[str, Mapping[str, float]]) -> float:
    scores = [
        _f1(entry["precision"], entry["recall"]) for entry in per_option.values()
    ]
    return sum(scores) / len(scores) if scores else 0.0

def _f1(precision: float, recall: float) -> float:
    return (
        2 * precision * recall / (precision + recall) if precision + recall else 0.0
    )

def _bin_index(probability: float) -> int:
    return min(_BINS - 1, max(0, int(probability * _BINS)))

def _brier(rows: Sequence[Row]) -> float | None:
    scored = [row for row in rows if row["distribution"] is not None]
    if not scored:
        return None
    total = 0.0
    for row in scored:
        distribution = row["distribution"]
        total += sum(
            (float(distribution.get(option, 0.0))
             - (1.0 if option == row["expected"] else 0.0)) ** 2
            for option in OPTIONS
        )
    return total / len(scored)

def _catalog_sizes(
    catalog: Catalog,
) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """The frozen catalog's listing bytes, everything bytes and per-skill sizes."""
    source = catalog["skills"] if isinstance(catalog, Mapping) else catalog
    entries = [
        dict(entry)
        if isinstance(entry, Mapping)
        else {
            "name": entry.name,
            "description": entry.description,
            "skill_md_bytes": entry.skill_md_bytes,
            "total_bytes": entry.total_bytes,
        }
        for entry in source
    ]
    listing = sum(len(str(entry["description"]).encode("utf-8")) for entry in entries)
    everything = listing + sum(int(entry["total_bytes"]) for entry in entries)
    by_name = {
        str(entry["name"]): (
            int(entry["skill_md_bytes"]),
            len(str(entry["description"]).encode("utf-8")),
        )
        for entry in entries
    }
    return listing, everything, by_name

def _runs(results: Mapping[str, Any] | Sequence[Any]) -> list[Mapping[str, Any]]:
    """The run list of a promptfoo results file, or the list itself."""
    if isinstance(results, Mapping):
        inner = results.get("results", [])
        if isinstance(inner, Mapping):
            inner = inner.get("results", [])
        return [entry for entry in inner if isinstance(entry, Mapping)]
    return [entry for entry in results if isinstance(entry, Mapping)]

def _output(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    """The provider output of one promptfoo run, parsed if it is JSON text."""
    output = (entry.get("response") or {}).get("output")
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return {}
    return output if isinstance(output, Mapping) else {}

def _run_record(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten one promptfoo run into the numbers B-23 reports.

    The arm and the observed model come from the provider output — what ran —
    while ``success`` and the price sit on the promptfoo run itself.
    """
    output = _output(entry)
    response = entry.get("response") or {}
    cost = response.get("cost")
    return {
        "arm": output.get("arm") or _vars(entry).get("arm") or "unknown",
        "success": entry.get("success") is True,
        "first_turn_input_tokens": output.get("first_turn_input_tokens"),
        "cost_usd": cost if cost is not None else output.get("cost_usd"),
        "num_turns": output.get("num_turns"),
        "duration_s": output.get("duration_s"),
        "model": output.get("model"),
    }

def _vars(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    variables = entry.get("vars")
    return variables if isinstance(variables, Mapping) else {}

def _mean(values: Sequence[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None

def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]
