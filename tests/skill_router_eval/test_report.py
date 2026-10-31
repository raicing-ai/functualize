"""The report command's contract: one measurement in, one evidence artifact out.

The fixtures write the four files the three commands before this one write —
``run.json`` and ``cells.jsonl`` per comparator, ``selections.json`` and a
promptfoo results file — so every assertion here runs the real report over
inputs shaped exactly like the ones it will read in Phase 4. No process is
spawned and nothing is measured: the rows are built to land on a branch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.skill_router_eval import report

OPTIONS = (
    "functualize",
    "functualize-app",
    "functualize-cli",
    "functualize-skill",
    "none",
)
NONE = "none"
CATALOG_SHA256 = "1" * 64
SCENARIOS_SHA256 = "2" * 64
RULE_DIGEST = "3" * 64
INSTRUMENT_SHA256 = "4" * 64
REPO_COMMIT = "5" * 40
OTHER_RULE_DIGEST = "6" * 64
MODEL = "claude-sonnet-4-5-20250929"
OTHER_MODEL = "claude-haiku-4-5-20251001"
IDENTITIES = {
    "hermetic": "a" * 64,
    "frontier": "b" * 64,
    "deterministic": "c" * 64,
    "native": "d" * 64,
}

#: Four 100-byte descriptions; a skill's own ``SKILL.md`` is 900 bytes, so a
#: skill-accepted cell carries 1000 bytes against native's 400-byte listing.
CATALOG: dict[str, Any] = {
    "skills": [
        {
            "name": skill,
            "description": skill[0] * 100,
            "skill_md_bytes": 900,
            "total_bytes": 1000,
        }
        for skill in OPTIONS[:-1]
    ]
}

_ROWS_KEY = (
    "cell",
    "repeat",
    "scenario",
    "expected",
    "stratum",
    "comparator",
    "status",
    "route",
    "decided_by",
    "proposal",
    "distribution",
    "probability",
    "margin",
    "confidence",
    "verdict",
    "failure",
    "rule_digest",
    "latency_seconds",
    "input_tokens",
    "output_tokens",
    "frontier",
    "native",
    "started_at",
)
"""The C-8 keys every row carries; the report may not need all of them."""


def _distribution(top: str, probability: float) -> dict[str, float]:
    """A distribution whose most likely option is ``top`` at ``probability``."""
    rest = (1.0 - probability) / (len(OPTIONS) - 1)
    return {option: (probability if option == top else rest) for option in OPTIONS}


def _accepted(top: str, probability: float) -> bool:
    """Whether the gate would accept ``top`` at the declared thresholds."""
    rest = (1.0 - probability) / (len(OPTIONS) - 1)
    return probability >= 0.70 and probability - rest >= 0.10


def _gated(
    *,
    scenario: str,
    expected: str,
    top: str,
    comparator: str = "hermetic",
    probability: float = 0.90,
    route: str | None | object = ...,
    rule_digest: str = RULE_DIGEST,
    repeat: int = 0,
) -> dict[str, Any]:
    """One gated row whose recorded route is what the rule would decide."""
    rest = (1.0 - probability) / (len(OPTIONS) - 1)
    decided = top if _accepted(top, probability) else None
    recorded = decided if route is ... else route
    row = {
        "cell": f"{comparator}-{scenario}",
        "repeat": repeat,
        "scenario": scenario,
        "expected": expected,
        "stratum": "clear",
        "comparator": comparator,
        "status": "routed",
        "route": recorded,
        "decided_by": comparator,
        "proposal": top,
        "distribution": _distribution(top, probability),
        "probability": max(probability, rest),
        "margin": probability - rest,
        "confidence": probability,
        "verdict": "accepted" if recorded else "escalated",
        "failure": None,
        "rule_digest": rule_digest,
        "latency_seconds": 1.0,
        "input_tokens": 10,
        "output_tokens": 5,
        "frontier": None,
        "native": None,
        "started_at": "2026-01-01T00:00:00+00:00",
    }
    assert set(row) == set(_ROWS_KEY)
    return row


def _native(
    *,
    scenario: str,
    expected: str,
    selected: str,
    cost_usd: float = 0.004,
    model: str = MODEL,
    repeat: int = 0,
) -> dict[str, Any]:
    """One native row: the instrument chose, no rule ran."""
    return {
        "cell": f"native-{scenario}",
        "repeat": repeat,
        "scenario": scenario,
        "expected": expected,
        "stratum": "clear",
        "comparator": "native",
        "status": "routed",
        "route": selected,
        "decided_by": "native",
        "proposal": None,
        "distribution": None,
        "probability": None,
        "margin": None,
        "confidence": None,
        "verdict": None,
        "failure": None,
        "rule_digest": None,
        "latency_seconds": 2.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "frontier": None,
        "native": {
            "selected": selected,
            "error": None,
            "model": model,
            "cost_usd": cost_usd,
        },
        "started_at": "2026-01-01T00:00:00+00:00",
    }


def _mixed(comparator: str, pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Rows for one gated comparator, one per ``(expected, proposal)`` pair."""
    return [
        _gated(
            scenario=f"k{index:02d}",
            expected=expected,
            top=top,
            comparator=comparator,
        )
        for index, (expected, top) in enumerate(pairs, start=1)
    ]


def _native_rows(pairs: list[tuple[str, str]], **kwargs: Any) -> list[dict[str, Any]]:
    """Native rows, one per ``(expected, selected)`` pair."""
    return [
        _native(
            scenario=f"k{index:02d}", expected=expected, selected=selected, **kwargs
        )
        for index, (expected, selected) in enumerate(pairs, start=1)
    ]


def _downstream(
    *,
    native_successes: int = 12,
    router_successes: int = 12,
    load_everything_successes: int = 12,
    runs: int = 15,
    router_model: str = MODEL,
) -> dict[str, Any]:
    """A promptfoo results file with three arms of ``runs`` cases each."""
    entries = []
    for arm, successes, model in (
        ("load-everything", load_everything_successes, MODEL),
        ("native", native_successes, MODEL),
        ("router", router_successes, router_model),
    ):
        for index in range(runs):
            output = {
                "arm": arm,
                "model": model,
                "first_turn_input_tokens": 400 + index,
                "num_turns": 5,
                "duration_s": 12.0,
                "skills_loaded": 1,
            }
            entries.append(
                {
                    "success": index < successes,
                    "response": {"cost": 0.01, "output": json.dumps(output)},
                    "vars": {},
                }
            )
    return {"results": {"results": entries}}


def _write(
    root: Path,
    name: str,
    rows: list[dict[str, Any]],
    *,
    rule_digest: str = RULE_DIGEST,
    identity_sha256: str | None = None,
) -> Path:
    """Write one run directory: a header and a ledger."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    header = {
        "run_id": f"run-{name}",
        "comparator": name,
        "identity": {"comparator": "native" if name == "native" else "recording"},
        "identity_sha256": identity_sha256 or IDENTITIES[name],
        "corpus": "v1",
        "scenarios_sha256": SCENARIOS_SHA256,
        "catalog_sha256": CATALOG_SHA256,
        "rule_digest": rule_digest,
        "instrument_sha256": INSTRUMENT_SHA256,
        "seed": 0,
        "repeats": 1,
        "repo_commit": REPO_COMMIT,
        "started_at": "2026-01-01T00:00:00+00:00",
    }
    (directory / "run.json").write_text(
        json.dumps(header, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (directory / "cells.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    return directory


@pytest.fixture()
def promote(tmp_path: Path) -> dict[str, Any]:
    """Inputs that land on ``promote to Phase 5``."""
    root = tmp_path / "inputs"
    root.mkdir()
    hermetic = _mixed(
        "hermetic",
        [(NONE, NONE)] * 16 + [("functualize", "functualize")] * 4,
    )
    deterministic = _mixed(
        "deterministic",
        [(NONE, NONE)] * 14 + [("functualize-app", NONE)] * 6,
    )
    frontier = _mixed("frontier", [(NONE, NONE)] * 20)
    native = _native_rows([(NONE, NONE)] * 20)
    run_dirs = [
        _write(root, "hermetic", hermetic),
        _write(root, "frontier", frontier),
        _write(root, "deterministic", deterministic),
        _write(root, "native", native),
    ]
    selections = root / "selections.json"
    selections.write_text(
        json.dumps(
            {
                "catalog_sha256": CATALOG_SHA256,
                "comparator": "hermetic",
                "identity_sha256": IDENTITIES["hermetic"],
                "repo_commit": REPO_COMMIT,
                "rule_digest": RULE_DIGEST,
                "instrument_sha256": INSTRUMENT_SHA256,
                "cases": {},
            }
        ),
        encoding="utf-8",
    )
    downstream = root / "results.json"
    downstream.write_text(json.dumps(_downstream()), encoding="utf-8")
    return {
        "run_dirs": run_dirs,
        "selections": selections,
        "downstream": downstream,
        "root": root,
        "hermetic": hermetic,
        "deterministic": deterministic,
        "native": native,
    }


def _run(inputs: dict[str, Any], out: Path, *extra: str) -> int:
    """Run the command line over the fixture's inputs."""
    arguments = [
        "--selections",
        str(inputs["selections"]),
        "--downstream",
        str(inputs["downstream"]),
        "--out",
        str(out),
        *extra,
    ]
    for directory in inputs["run_dirs"]:
        arguments.extend(["--run-dir", str(directory)])
    return report.main(arguments, catalog=CATALOG)


def test_promote_branch(promote: dict[str, Any], tmp_path: Path) -> None:
    """Every condition holds, including the router's context below native's."""
    out = tmp_path / "report"
    assert _run(promote, out) == 0
    answer = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    assert answer["verdict"] == "promote to Phase 5"
    assert answer["failed_conditions"] == []
    assert answer["e2"] == {
        "hermetic_accuracy": 1.0,
        "deterministic_accuracy": 0.7,
        "lead": pytest.approx(0.3),
        "holds": True,
        "unsafe_none": 0,
    }
    assert answer["e3"]["router_over_native_bytes"] == pytest.approx(0.5)
    assert answer["e3"]["holds"] is True
    assert answer["e4"]["success"]["router"] == [12, 15]
    assert answer["e4"]["success"]["native"] == [12, 15]
    assert answer["e4"]["holds"] is True
    finding = (out / "finding.md").read_text(encoding="utf-8")
    assert "promote to Phase 5" in finding
    assert "Every condition held." in finding
    assert "| e2 | yes |" in finding
    assert "| context | yes |" in finding
    assert "| downstream | yes |" in finding
    assert "| E4 router success | 12/15 |" in finding
    assert "0.5481–0.9295" in finding


def test_negative_result_when_the_lead_does_not_hold(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """No lead over the keyword table: nothing is promoted, whatever else holds."""
    promote["run_dirs"][2] = _write(
        promote["root"],
        "deterministic",
        _mixed("deterministic", [(NONE, NONE)] * 20),
    )
    out = tmp_path / "report"
    assert _run(promote, out) == 0
    answer = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    assert answer["verdict"] == "negative result"
    assert "e2" in answer["failed_conditions"]


def test_continue_research_names_every_failed_condition(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """E2 holds but context and downstream do not: both are named."""
    promote["run_dirs"][0] = _write(
        promote["root"],
        "hermetic",
        _mixed(
            "hermetic",
            [(NONE, NONE)] + [("functualize", "functualize")] * 19,
        ),
    )
    promote["downstream"].write_text(
        json.dumps(
            _downstream(native_successes=12, router_successes=10),
        ),
        encoding="utf-8",
    )
    out = tmp_path / "report"
    assert _run(promote, out) == 0
    answer = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    assert answer["verdict"] == "continue research"
    assert answer["failed_conditions"] == ["context", "downstream"]
    finding = (out / "finding.md").read_text(encoding="utf-8")
    assert "`context`" in finding
    assert "`downstream`" in finding
    assert answer["e3"]["router_over_native_bytes"] == pytest.approx(2.375)
    assert answer["e3"]["holds"] is False


def test_one_unsafe_none_blocks_the_promotion(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """A single accepted ``none`` where a skill was expected is enough."""
    promote["run_dirs"][0] = _write(
        promote["root"],
        "hermetic",
        _mixed(
            "hermetic",
            [(NONE, NONE)] * 18
            + [("functualize", NONE)]
            + [("functualize", "functualize")],
        ),
    )
    out = tmp_path / "report"
    assert _run(promote, out) == 0
    answer = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    assert answer["e2"]["unsafe_none"] == 1
    assert answer["verdict"] == "continue research"
    assert answer["failed_conditions"] == ["unsafe_none"]
    finding = (out / "finding.md").read_text(encoding="utf-8")
    assert "`unsafe_none`" in finding


def test_wilson_interval_for_twelve_of_fifteen(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """12/15 is the hand-computed [0.5481, 0.9295] in both files."""
    out = tmp_path / "report"
    assert _run(promote, out) == 0
    answer = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    assert answer["e4"]["wilson95"]["native"] == [0.5481, 0.9295]
    benchmark = (out / "benchmark.md").read_text(encoding="utf-8")
    assert "0.5481" in benchmark
    assert "0.9295" in benchmark


def test_native_cost_is_the_instruments_own_dollars(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """The native block is priced by the instrument, in both artifacts."""
    out = tmp_path / "report"
    assert _run(promote, out) == 0
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    native = metrics["comparators"]["native"]["native_cost"]
    assert native["usd_total"] == pytest.approx(20 * 0.004)
    assert native["usd_per_cell"] == pytest.approx(0.004)
    assert native["usd_per_correct"] == pytest.approx(0.004)
    assert native["priced_cells"] == 20
    assert native["unpriced_cells"] == 0
    benchmark = (out / "benchmark.md").read_text(encoding="utf-8")
    assert "0.0800" in benchmark
    assert "USD total (native only)" in benchmark


def test_provenance_carries_every_digest(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """B-25: the artifacts name what they were computed from, by digest."""
    out = tmp_path / "report"
    assert _run(promote, out) == 0
    block = json.loads((out / "metrics.json").read_text(encoding="utf-8"))["provenance"]
    assert block["corpus"] == {"version": "v1", "sha256": SCENARIOS_SHA256}
    assert block["catalog_sha256"] == CATALOG_SHA256
    assert block["rule_digest"] == RULE_DIGEST
    assert block["instrument_sha256"] == INSTRUMENT_SHA256
    assert block["repo_commit"] == REPO_COMMIT
    assert block["identities"] == IDENTITIES
    assert set(block["ledgers"]) == set(report.COMPARATORS)
    assert block["selections_sha256"]
    assert block["downstream_sha256"]
    benchmark = (out / "benchmark.md").read_text(encoding="utf-8")
    for digest in (SCENARIOS_SHA256, CATALOG_SHA256, RULE_DIGEST, REPO_COMMIT):
        assert digest in benchmark
    assert block["selections_sha256"] in benchmark
    assert block["downstream_sha256"] in benchmark


def test_a_doctored_ledger_exits_four(promote: dict[str, Any], tmp_path: Path) -> None:
    """AC-9: a recorded outcome the rule would not produce stops the report."""
    doctored = [dict(row) for row in promote["hermetic"]]
    doctored[0] = {**doctored[0], "route": None}
    promote["run_dirs"][0] = _write(promote["root"], "hermetic", doctored)
    out = tmp_path / "report"
    assert _run(promote, out) == 4
    assert not (out / "benchmark.md").exists()


def test_two_rule_digests_in_one_ledger_exits_two(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """A cell measured under another rule is not this measurement."""
    ledger = [dict(row) for row in promote["hermetic"]]
    ledger[3] = {**ledger[3], "rule_digest": OTHER_RULE_DIGEST}
    promote["run_dirs"][0] = _write(promote["root"], "hermetic", ledger)
    out = tmp_path / "report"
    assert _run(promote, out) == 2
    assert not (out / "verdict.json").exists()


def test_two_native_models_exit_two(promote: dict[str, Any], tmp_path: Path) -> None:
    """Four ledgers may only describe one router."""
    rows = [dict(row) for row in promote["native"]]
    rows[1] = {**rows[1], "native": {**rows[1]["native"], "model": OTHER_MODEL}}
    promote["run_dirs"][3] = _write(promote["root"], "native", rows)
    out = tmp_path / "report"
    assert _run(promote, out) == 2
    assert not (out / "verdict.json").exists()


def test_two_downstream_models_exit_two(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """A downstream file with two models is two experiments."""
    promote["downstream"].write_text(
        json.dumps(_downstream(router_model=OTHER_MODEL)), encoding="utf-8"
    )
    out = tmp_path / "report"
    assert _run(promote, out) == 2
    assert not (out / "verdict.json").exists()


def test_a_missing_comparator_exits_two(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """Three ledgers are not four."""
    out = tmp_path / "report"
    arguments = [
        "--run-dir",
        str(promote["run_dirs"][0]),
        "--run-dir",
        str(promote["run_dirs"][1]),
        "--run-dir",
        str(promote["run_dirs"][2]),
        "--selections",
        str(promote["selections"]),
        "--downstream",
        str(promote["downstream"]),
        "--out",
        str(out),
    ]
    assert report.main(arguments, catalog=CATALOG) == 2
    assert not (out / "verdict.json").exists()


def test_two_runs_of_one_comparator_exit_two(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """The same comparator twice is a duplicate, not a repeat."""
    out = tmp_path / "report"
    arguments = [
        "--run-dir",
        str(promote["run_dirs"][0]),
        "--run-dir",
        str(promote["run_dirs"][0]),
        "--run-dir",
        str(promote["run_dirs"][1]),
        "--run-dir",
        str(promote["run_dirs"][2]),
        "--selections",
        str(promote["selections"]),
        "--downstream",
        str(promote["downstream"]),
        "--out",
        str(out),
    ]
    assert report.main(arguments, catalog=CATALOG) == 2


def test_the_report_is_byte_identical_and_check_compares(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """AC-13: same inputs, same bytes; ``--check`` exits 1 on any difference."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert _run(promote, first) == 0
    assert _run(promote, second) == 0
    for name in ("benchmark.md", "finding.md", "metrics.json", "verdict.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert _run(promote, tmp_path / "ignored", "--check", str(first)) == 0
    (second / "verdict.json").write_text("{}", encoding="utf-8")
    assert _run(promote, tmp_path / "ignored", "--check", str(second)) == 1


def test_the_evidence_is_recomputed_from_the_files(
    promote: dict[str, Any], tmp_path: Path
) -> None:
    """The tables come from the ledgers, not from a hand-typed summary."""
    out = tmp_path / "report"
    assert _run(promote, out) == 0
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["corpus"] == {"version": "v1", "sha256": SCENARIOS_SHA256}
    assert metrics["comparators"]["hermetic"]["accuracy"]["routed_accuracy"] == 1.0
    assert metrics["comparators"]["deterministic"]["accuracy"]["routed_accuracy"] == 0.7
    assert metrics["comparators"]["native"]["native_cost"]["cells"] == 20
    assert len(metrics["sweep"]) == 50
    assert metrics["conformance"] == []
    assert metrics["downstream"]["arms"]["router"]["successes"] == 12
    assert metrics["comparators"]["hermetic"]["context"]["router_to_native"] == 0.5
