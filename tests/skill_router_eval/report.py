"""The report command: four ledgers, one evidence artifact.

Nothing here measures anything. The four run directories were written by
:mod:`tests.skill_router_eval.replay`, the selections by
:mod:`tests.skill_router_eval.select` and the downstream runs by promptfoo;
this module reads them and asks them whether they still describe one
measurement. When they disagree — a different corpus, catalog, rule digest,
instrument or observed model — the answer is exit 2 and no report, because a
report over two questions is worse than no report at all.

The one number this module computes on its own is conformance: at the declared
thresholds, the offline rule must reproduce every gated cell's recorded
outcome, or the walk and the rule have drifted apart and the report exits 4.

Every file carries the same provenance block, and every float is rounded the
same way, so two runs over the same inputs are byte-identical (B-26).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.hermetic_eval import metrics as phase3
from tests.hermetic_eval.replay import ledger_rows
from tests.skill_router_eval import metrics, replay
from tests.skill_router_eval.catalog import derive_catalog
from tests.skill_router_eval.corpus import DECLARED, VERDICT

__all__ = [
    "COMPARATORS",
    "GATED",
    "ReportError",
    "build",
    "conformance_failures",
    "main",
    "provenance",
]

#: The four comparators, in the order the tables read them.
COMPARATORS: tuple[str, ...] = replay.COMPARATORS

#: The gated ones: their rows carry a distribution a rule can decide.
GATED: tuple[str, ...] = replay.GATED

_RUN_JSON = "run.json"
_CELLS = "cells.jsonl"
_NOT_ATTEMPTED = "not_attempted"
_NATIVE = "native"
_ROUTER = "router"
_LOAD_EVERYTHING = "load-everything"
_DECLARED = DECLARED
_CONSTANTS = VERDICT
_PLACES = 4
_DASH = "—"

#: The header and selections fields every input must agree on.
_AGREED = (
    "corpus",
    "scenarios_sha256",
    "catalog_sha256",
    "rule_digest",
    "instrument_sha256",
    "repo_commit",
)


class ReportError(Exception):
    """The inputs do not describe one measurement: exit 2, write nothing."""


class ConformanceError(ReportError):
    """The offline rule does not reproduce a gated cell's outcome: exit 4."""


def _sha256(path: Path) -> str:
    """The SHA-256 of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    """Read one JSON file, refusing anything that is not an object."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ReportError(f"{path} is not a JSON object")
    return payload


def _load_run(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One run directory's header and rows."""
    directory = Path(run_dir)
    if not (directory / _RUN_JSON).exists():
        raise ReportError(f"{directory} holds no {_RUN_JSON}")
    if not (directory / _CELLS).exists():
        raise ReportError(f"{directory} holds no {_CELLS}")
    header = dict(_read_json(directory / _RUN_JSON))
    rows = [dict(row) for row in ledger_rows(directory / _CELLS)]
    return header, rows


def _by_comparator(
    runs: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
) -> dict[str, tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Group the runs by comparator, refusing a missing or a duplicated one."""
    grouped: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for header, rows in runs:
        name = str(header.get("comparator"))
        if name not in COMPARATORS:
            raise ReportError(f"unknown comparator {name!r} in a run directory")
        if name in grouped:
            raise ReportError(f"two run directories both hold {name}")
        grouped[name] = (header, rows)
    missing = [name for name in COMPARATORS if name not in grouped]
    if missing:
        raise ReportError(f"no run directory for {', '.join(missing)}")
    return grouped


def _agree(
    grouped: Mapping[str, tuple[dict[str, Any], list[dict[str, Any]]]],
    selections: Mapping[str, Any],
) -> dict[str, Any]:
    """Check that every input names the same corpus, catalog, rule and instrument."""
    headers = {name: header for name, (header, _rows) in grouped.items()}
    first_name = COMPARATORS[0]
    reference = headers[first_name]
    for field in _AGREED:
        for name, header in headers.items():
            if header.get(field) != reference.get(field):
                raise ReportError(
                    f"{name} holds {field} {header.get(field)!r}, "
                    f"{first_name} holds {reference.get(field)!r}"
                )
        if field in selections and selections.get(field) != reference.get(field):
            raise ReportError(
                f"the selections hold {field} {selections.get(field)!r}, "
                f"the runs hold {reference.get(field)!r}"
            )
    chosen = str(selections.get("comparator"))
    if chosen not in grouped:
        raise ReportError(f"the selections were made by {chosen!r}, which has no run")
    if selections.get("identity_sha256") != headers[chosen].get("identity_sha256"):
        raise ReportError("the selections' identity digest is not the run's")
    return reference


def _check_ledgers(
    grouped: Mapping[str, tuple[dict[str, Any], list[dict[str, Any]]]],
    reference: Mapping[str, Any],
) -> None:
    """A gated ledger may only carry the lock's rule digest; native only one model."""
    for name in GATED:
        _header, rows = grouped[name]
        for row in rows:
            if row.get("status") == _NOT_ATTEMPTED:
                continue
            if row.get("rule_digest") != reference.get("rule_digest"):
                raise ReportError(
                    f"{name} cell {row.get('cell')} ({row.get('scenario')}) holds "
                    f"rule digest {row.get('rule_digest')!r}, the lock holds "
                    f"{reference.get('rule_digest')!r}"
                )
    models = {
        str((row.get("native") or {}).get("model"))
        for row in grouped[_NATIVE][1]
        if row.get("native") is not None and (row.get("native") or {}).get("model")
    }
    if len(models) > 1:
        raise ReportError(
            f"the native ledger shows {len(models)} models: {', '.join(sorted(models))}"
        )


def _check_downstream(downstream: Mapping[str, Any]) -> dict[str, Any]:
    """Summarise the downstream runs, refusing more than one observed model."""
    summary = metrics.downstream_summary(downstream)
    models = list(summary.get("models") or ())
    if len(models) > 1:
        raise ReportError(
            f"the downstream results show {len(models)} models: {', '.join(models)}"
        )
    return summary


def conformance_failures(
    rows: Sequence[Mapping[str, Any]],
    *,
    accept_at: float = _DECLARED["accept_at"],
    min_margin: float = _DECLARED["min_margin"],
) -> list[tuple[str, int]]:
    """The gated cells whose recorded outcome the offline rule does not reproduce."""
    return metrics.conformance(rows, accept_at, min_margin)


def provenance(
    grouped: Mapping[str, tuple[dict[str, Any], list[dict[str, Any]]]],
    *,
    run_dirs: Mapping[str, Path],
    reference: Mapping[str, Any],
    selections_sha256: str,
    downstream_sha256: str,
) -> dict[str, Any]:
    """B-25's block: what the report was computed from, by digest."""
    return {
        "corpus": {
            "version": reference.get("corpus"),
            "sha256": reference.get("scenarios_sha256"),
        },
        "catalog_sha256": reference.get("catalog_sha256"),
        "rule_digest": reference.get("rule_digest"),
        "instrument_sha256": reference.get("instrument_sha256"),
        "repo_commit": reference.get("repo_commit"),
        "identities": {
            name: grouped[name][0].get("identity_sha256") for name in COMPARATORS
        },
        "ledgers": {
            name: _sha256(Path(run_dirs[name]) / _CELLS) for name in COMPARATORS
        },
        "selections_sha256": selections_sha256,
        "downstream_sha256": downstream_sha256,
    }


def _rounded(value: Any) -> Any:
    """Round every float to four places, so two runs print the same bytes."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, _PLACES)
    if isinstance(value, Mapping):
        return {str(key): _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    return value


def _json(payload: Any) -> str:
    """One report file's JSON text: sorted keys, four places, one trailing newline."""
    return json.dumps(_rounded(payload), indent=2, sort_keys=True) + "\n"


def _num(value: Any, places: int = _PLACES) -> str:
    """A number for a table cell, or a dash when there is none."""
    if value is None:
        return _DASH
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return str(value)


def _ratio(pair: Sequence[Any] | None) -> str:
    """Successes over runs, or a dash when the arm did not run."""
    if not pair:
        return _DASH
    successes, runs = pair
    return f"{successes}/{runs}"


def _interval(pair: Sequence[Any] | None) -> str:
    """A Wilson interval for a table cell."""
    if not pair or pair[0] is None or pair[1] is None:
        return _DASH
    return f"{pair[0]:.4f}–{pair[1]:.4f}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """A Markdown table."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(_num(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def _provenance_lines(block: Mapping[str, Any]) -> str:
    """The provenance block as a bullet list."""
    corpus_block = block.get("corpus") or {}
    lines = [
        f"- corpus: `{corpus_block.get('version')}` `{corpus_block.get('sha256')}`",
        f"- catalog: `{block.get('catalog_sha256')}`",
        f"- rule digest: `{block.get('rule_digest')}`",
        f"- instrument: `{block.get('instrument_sha256')}`",
        f"- repository commit: `{block.get('repo_commit')}`",
    ]
    lines.extend(
        f"- identity, {name}: `{digest}`"
        for name, digest in (block.get("identities") or {}).items()
    )
    lines.extend(
        f"- ledger, {name}: `{digest}`"
        for name, digest in (block.get("ledgers") or {}).items()
    )
    lines.append(f"- selections: `{block.get('selections_sha256')}`")
    lines.append(f"- downstream: `{block.get('downstream_sha256')}`")
    return "\n".join(lines)


def _e2(
    hermetic_rows: Sequence[Mapping[str, Any]],
    deterministic_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """E2: the hermetic comparator leads the keyword table by ``min_lead``."""
    hermetic = metrics.accuracy_summary(hermetic_rows)["routed_accuracy"]
    deterministic = metrics.accuracy_summary(deterministic_rows)["routed_accuracy"]
    lead = hermetic - deterministic
    unsafe_none = metrics.errors_at(hermetic_rows)["unsafe_none"]
    return {
        "hermetic_accuracy": hermetic,
        "deterministic_accuracy": deterministic,
        "lead": lead,
        "holds": lead >= float(_CONSTANTS["min_lead"]),
        "unsafe_none": unsafe_none,
    }


def _e3(
    context: Mapping[str, Mapping[str, Any]],
    downstream: Mapping[str, Any],
) -> dict[str, Any]:
    """E3: the router's context is below native's, on the corpus and downstream."""
    router = context.get("hermetic", {})
    arms = downstream.get("arms") or {}
    tokens = {
        arm: (arms.get(arm) or {}).get("first_turn_input_tokens_mean")
        for arm in (_LOAD_EVERYTHING, _NATIVE, _ROUTER)
    }
    ratio = router.get("router_to_native")
    return {
        "router_over_native_bytes": ratio,
        "load_everything_over_native_bytes": router.get("load_everything_to_native"),
        "first_turn_tokens": tokens,
        "holds": ratio is not None and ratio < 1.0,
    }


def _e4(downstream: Mapping[str, Any]) -> dict[str, Any]:
    """E4: the router is no worse than native downstream."""
    arms = downstream.get("arms") or {}
    success = {
        arm: [
            int((arms.get(arm) or {}).get("successes") or 0),
            int((arms.get(arm) or {}).get("runs") or 0),
        ]
        for arm in (_LOAD_EVERYTHING, _NATIVE, _ROUTER)
    }
    intervals = {
        arm: [
            ((arms.get(arm) or {}).get("success_rate") or {}).get("lo"),
            ((arms.get(arm) or {}).get("success_rate") or {}).get("hi"),
        ]
        for arm in (_NATIVE, _ROUTER)
    }
    native_p = ((arms.get(_NATIVE) or {}).get("success_rate") or {}).get("p")
    router_p = ((arms.get(_ROUTER) or {}).get("success_rate") or {}).get("p")
    return {
        "success": success,
        "wilson95": intervals,
        "holds": (
            native_p is not None and router_p is not None and router_p >= native_p
        ),
    }


def _benchmark(
    grouped: Mapping[str, tuple[dict[str, Any], list[dict[str, Any]]]],
    *,
    context: Mapping[str, Mapping[str, Any]],
    native: Mapping[str, Any],
    downstream: Mapping[str, Any],
    failures: Sequence[tuple[str, int]],
    block: Mapping[str, Any],
) -> str:
    """B-25's tables, in the order the evidence row reads them."""
    accuracy = {
        name: metrics.accuracy_summary(grouped[name][1]) for name in COMPARATORS
    }
    routing = [
        (
            name,
            accuracy[name]["cells"],
            accuracy[name]["correct"],
            accuracy[name]["routed_accuracy"],
            accuracy[name]["macro_f1"],
            native["usd_total"] if name == _NATIVE else None,
        )
        for name in COMPARATORS
    ]
    counted = {name: metrics.errors_at(grouped[name][1]) for name in GATED}
    errors = [
        (
            name,
            *(
                counted[name][key]
                for key in (
                    "cells",
                    "accepted",
                    "coverage",
                    "selective_accuracy",
                    "wrong_skill",
                    "unsafe_none",
                    "over_load",
                    "false_escalation",
                )
            ),
        )
        for name in GATED
    ]
    sweep = [
        (
            point["accept_at"],
            point["accepted"],
            point["coverage"],
            point["selective_accuracy"],
            point["wrong_skill"],
            point["unsafe_none"],
            point["over_load"],
            point["false_escalation"],
        )
        for point in metrics.sweep(grouped["hermetic"][1])
        if point["min_margin"] == _DECLARED["min_margin"]
    ]
    context_rows = [
        (
            name,
            context.get(name, {}).get("native"),
            context.get(name, {}).get("load_everything"),
            context.get(name, {}).get("router"),
            context.get(name, {}).get("router_to_native"),
            context.get(name, {}).get("load_everything_to_native"),
        )
        for name in COMPARATORS
        if name in context
    ]
    arms = downstream.get("arms") or {}
    downstream_rows = [
        (
            arm,
            record["runs"],
            record["successes"],
            (record["success_rate"] or {}).get("p"),
            (record["success_rate"] or {}).get("lo"),
            (record["success_rate"] or {}).get("hi"),
            record["first_turn_input_tokens_mean"],
            record["first_turn_input_tokens_p95"],
            record["cost_usd_mean"],
            record["turns_mean"],
            record["duration_s_mean"],
            record["skills_loaded_mean"],
            ", ".join(record["models"]) or None,
        )
        for arm, record in sorted(arms.items())
    ]
    sections = [
        "## Routing",
        _table(
            (
                "comparator",
                "cells",
                "correct",
                "routed accuracy",
                "macro F1",
                "USD total (native only)",
            ),
            routing,
        ),
        "",
        "The native row is accuracy-only: it was never gated, so it has no "
        "proposal distribution to threshold. Its USD is the instrument's own "
        "`native_cost.usd_total`, never a token cost.",
        "",
        "## The four errors at the declared point",
        _table(
            (
                "comparator",
                "cells",
                "accepted",
                "coverage",
                "selective accuracy",
                "wrong skill",
                "unsafe none",
                "over load",
                "false escalation",
            ),
            errors,
        ),
        "",
        "## Threshold sweep at min_margin = 0.10",
        _table(
            (
                "accept_at",
                "accepted",
                "coverage",
                "selective accuracy",
                "wrong skill",
                "unsafe none",
                "over load",
                "false escalation",
            ),
            sweep,
        ),
        "",
        "## Context before the first turn",
        _table(
            (
                "comparator",
                "native bytes",
                "load-everything bytes",
                "router bytes",
                "router / native",
                "load-everything / native",
            ),
            context_rows,
        ),
        "",
        "The headline is the router's ratio to native. Load-everything is shown "
        "beside it and is never the headline.",
        "",
        "## Downstream",
        _table(
            (
                "arm",
                "runs",
                "successes",
                "success rate",
                "Wilson 95% low",
                "Wilson 95% high",
                "first-turn tokens (mean)",
                "first-turn tokens (p95)",
                "cost USD (mean)",
                "turns (mean)",
                "duration s (mean)",
                "skills loaded",
                "model",
            ),
            downstream_rows,
        ),
        "",
        "## Conformance",
        (
            "The offline rule reproduces every gated cell's recorded outcome at "
            f"({_DECLARED['accept_at']:.2f}, {_DECLARED['min_margin']:.2f})."
            if not failures
            else "Cells the offline rule does not reproduce: "
            + ", ".join(f"`{name}` repeat {repeat}" for name, repeat in failures)
        ),
        "",
        "## Provenance",
        _provenance_lines(block),
        "",
    ]
    return "\n".join(sections)


def _finding(
    verdict: Mapping[str, Any],
    *,
    e2: Mapping[str, Any],
    e3: Mapping[str, Any],
    e4: Mapping[str, Any],
    native: Mapping[str, Any],
    downstream: Mapping[str, Any],
    block: Mapping[str, Any],
) -> str:
    """The verdict, what failed, what this measurement does not cover."""
    models = ", ".join(downstream.get("models") or ()) or "none observed"
    failed = list(verdict.get("failed_conditions") or ())
    conditions = verdict.get("conditions") or {}
    lines = [
        f"# {verdict['verdict']}",
        "",
        f"Verdict: **{verdict['verdict']}**.",
        "",
    ]
    if failed:
        lines.extend(
            [
                "Failed conditions: " + ", ".join(f"`{name}`" for name in failed) + ".",
                "",
            ]
        )
    else:
        lines.extend(["Every condition held.", ""])
    lines.extend(
        [
            "## Conditions",
            _table(
                ("condition", "held"),
                sorted(conditions.items()),
            ),
            "",
            "## The numbers the verdict rests on",
            _table(
                ("quantity", "value"),
                (
                    ("E2 hermetic accuracy", e2["hermetic_accuracy"]),
                    ("E2 deterministic accuracy", e2["deterministic_accuracy"]),
                    ("E2 lead", e2["lead"]),
                    ("E2 unsafe `none`", e2["unsafe_none"]),
                    ("E3 router / native bytes", e3["router_over_native_bytes"]),
                    (
                        "E3 load-everything / native bytes",
                        e3["load_everything_over_native_bytes"],
                    ),
                    (
                        "E3 first-turn tokens, router",
                        e3["first_turn_tokens"].get(_ROUTER),
                    ),
                    (
                        "E3 first-turn tokens, native",
                        e3["first_turn_tokens"].get(_NATIVE),
                    ),
                    (
                        "E3 first-turn tokens, load everything",
                        e3["first_turn_tokens"].get(_LOAD_EVERYTHING),
                    ),
                    ("E4 router success", _ratio(e4["success"].get(_ROUTER))),
                    ("E4 native success", _ratio(e4["success"].get(_NATIVE))),
                    (
                        "E4 router Wilson 95%",
                        _interval(e4["wilson95"].get(_ROUTER)),
                    ),
                    (
                        "E4 native Wilson 95%",
                        _interval(e4["wilson95"].get(_NATIVE)),
                    ),
                ),
            ),
            "",
            "## Cost",
            "",
            f"Native cells priced by the instrument: {_num(native['priced_cells'])} "
            f"of {_num(native['cells'])}; USD total {_num(native['usd_total'])}, "
            f"per priced cell {_num(native['usd_per_cell'])}, per correct answer "
            f"{_num(native['usd_per_correct'])}.",
            "",
            "## Gaps",
            "",
            "- `functualize-cli` and `none` have no downstream task: B-19's five "
            "cases cover `functualize`, `functualize-app` and `functualize-skill` "
            "only, so E4 says nothing about the two options it never runs.",
            "- The label set is single-skill: a request that genuinely needs two "
            "skills is listed in `TWO_SKILL.md`, not labelled, and is out of this "
            "corpus's scope.",
            "",
            "## Deviations",
            "",
            f"- Downstream observed model(s): {models}.",
            "",
            "## Provenance",
            _provenance_lines(block),
            "",
        ]
    )
    return "\n".join(lines)


def _verdict_document(
    *,
    verdict: Mapping[str, Any],
    e2: Mapping[str, Any],
    e3: Mapping[str, Any],
    e4: Mapping[str, Any],
    block: Mapping[str, Any],
) -> dict[str, Any]:
    """C-9's ``verdict.json``: the rule's answer and everything it was given."""
    conditions = verdict.get("conditions") or {}
    failed = list(verdict.get("failed") or ()) or [
        name for name, held in sorted(conditions.items()) if not held
    ]
    return {
        "corpus": block["corpus"],
        "catalog_sha256": block["catalog_sha256"],
        "declared": dict(_DECLARED),
        "constants": dict(_CONSTANTS),
        "e2": dict(e2),
        "e3": dict(e3),
        "e4": dict(e4),
        "verdict": verdict["verdict"],
        "conditions": dict(conditions),
        "failed_conditions": failed,
        "provenance": dict(block),
    }


def _metrics_document(
    grouped: Mapping[str, tuple[dict[str, Any], list[dict[str, Any]]]],
    *,
    context: Mapping[str, Mapping[str, Any]],
    costs: Mapping[str, Any],
    native: Mapping[str, Any],
    downstream: Mapping[str, Any],
    failures: Sequence[tuple[str, int]],
    block: Mapping[str, Any],
) -> dict[str, Any]:
    """``metrics.json``: per comparator the metrics, with native's own cost."""
    comparators: dict[str, Any] = {}
    for name in COMPARATORS:
        rows = grouped[name][1]
        entry: dict[str, Any] = {
            "accuracy": metrics.accuracy_summary(rows),
            "coverage": metrics.coverage(rows),
            "cost": costs[name],
            "context": context.get(name),
        }
        if name in GATED:
            entry["errors"] = metrics.errors_at(rows)
        else:
            entry["native_cost"] = native
        comparators[name] = entry
    return {
        "corpus": block["corpus"],
        "catalog_sha256": block["catalog_sha256"],
        "declared": dict(_DECLARED),
        "comparators": comparators,
        "sweep": metrics.sweep(grouped["hermetic"][1]),
        "conformance": [
            {"scenario": name, "repeat": repeat} for name, repeat in failures
        ],
        "downstream": downstream,
        "provenance": block,
    }


def build(
    run_dirs: Sequence[Path],
    *,
    selections: Path,
    downstream_path: Path,
    catalog: Any = None,
) -> dict[str, str]:
    """Compute the four files, or raise :class:`ReportError` saying why not."""
    if len(run_dirs) != len(COMPARATORS):
        raise ReportError(
            f"expected {len(COMPARATORS)} run directories, got {len(run_dirs)}"
        )
    chosen = _read_json(selections)
    downstream_raw = _read_json(downstream_path)
    runs = [_load_run(Path(directory)) for directory in run_dirs]
    grouped = _by_comparator(runs)
    reference = _agree(grouped, chosen)
    _check_ledgers(grouped, reference)
    downstream = _check_downstream(downstream_raw)

    gated_rows = [row for name in GATED for row in grouped[name][1]]
    failures = conformance_failures(gated_rows)
    if failures:
        raise ConformanceError(
            "the offline rule does not reproduce "
            + ", ".join(f"{name} (repeat {repeat})" for name, repeat in failures)
        )

    block = provenance(
        grouped,
        run_dirs={
            name: Path(directory)
            for name, directory in zip(COMPARATORS, run_dirs, strict=True)
        },
        reference=reference,
        selections_sha256=_sha256(selections),
        downstream_sha256=_sha256(downstream_path),
    )
    catalog = catalog if catalog is not None else derive_catalog()
    all_rows = [row for name in COMPARATORS for row in grouped[name][1]]
    context = metrics.context_summary(all_rows, catalog)
    costs = {name: phase3.cost(grouped[name][1]) for name in COMPARATORS}
    native = metrics.native_cost(grouped[_NATIVE][1])
    e2 = _e2(grouped["hermetic"][1], grouped["deterministic"][1])
    e3 = _e3(context, downstream)
    e4 = _e4(downstream)
    arms = downstream.get("arms") or {}
    rule = metrics.verdict(
        grouped["hermetic"][1],
        grouped["deterministic"][1],
        router_context_bytes=context.get("hermetic", {}).get("router"),
        native_context_bytes=(
            context.get(_NATIVE, {}).get(_NATIVE)
            or context.get("hermetic", {}).get(_NATIVE)
        ),
        downstream_router_success=(
            (arms.get(_ROUTER) or {}).get("success_rate") or {}
        ).get("p"),
        downstream_native_success=(
            (arms.get(_NATIVE) or {}).get("success_rate") or {}
        ).get("p"),
    )
    answer = _verdict_document(verdict=rule, e2=e2, e3=e3, e4=e4, block=block)
    return {
        "benchmark.md": _benchmark(
            grouped,
            context=context,
            native=native,
            downstream=downstream,
            failures=failures,
            block=block,
        ),
        "finding.md": _finding(
            answer,
            e2=e2,
            e3=e3,
            e4=e4,
            native=native,
            downstream=downstream,
            block=block,
        ),
        "metrics.json": _json(
            _metrics_document(
                grouped,
                context=context,
                costs=costs,
                native=native,
                downstream=downstream,
                failures=failures,
                block=block,
            )
        ),
        "verdict.json": _json(answer),
    }


def _parser() -> argparse.ArgumentParser:
    """The C-9 command line."""
    parser = argparse.ArgumentParser(prog="tests.skill_router_eval.report")
    parser.add_argument("--run-dir", action="append", default=[], required=True)
    parser.add_argument("--selections", required=True)
    parser.add_argument("--downstream", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--check", default=None)
    return parser


def main(argv: list[str] | None = None, *, catalog: Any = None) -> int:
    """Write the report, or compare it with ``--check``."""
    args = _parser().parse_args(argv)
    out = Path(args.out)
    try:
        files = build(
            [Path(directory) for directory in args.run_dir],
            selections=Path(args.selections),
            downstream_path=Path(args.downstream),
            catalog=catalog,
        )
    except ConformanceError as error:
        print(error)
        return 4
    except (ReportError, OSError, ValueError) as error:
        print(error)
        return 2
    if args.check is not None:
        reference = Path(args.check)
        differences = [
            name
            for name, text in sorted(files.items())
            if not (reference / name).exists()
            or (reference / name).read_text(encoding="utf-8") != text
        ]
        if differences:
            print("differs: " + ", ".join(differences))
            return 1
        print(f"{reference} is identical")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    for name, text in sorted(files.items()):
        (out / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(files)} files to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
