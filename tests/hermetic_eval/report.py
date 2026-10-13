"""The report command: turn three ledgers into the benchmark documents.

    main → metrics.<summary> → boundary/verdict → metrics.json, boundary.json,
    benchmark.md, finding.md

The report is a pure function of the three run directories it is pointed at:
every number comes from a ledger line, every paragraph from those numbers, and
nothing carries the report's own wall-clock time, so two invocations over the
same ledgers are byte-identical. It never rewrites a ledger and never runs a
comparator — reading a measurement and producing a measurement stayed separate
commands on purpose.

Exit codes are C-8's: 0 for written or `--check` identical, 1 for a `--check`
difference, 2 when the runs are not one per comparator over one corpus, and 4
when the offline rule at the declared point disagrees with a recorded route —
that last one means the ledger is not self-consistent, so no report is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.hermetic_eval import corpus, metrics, replay

__all__ = ["main"]

#: The four documents, in the order they are written and checked.
DOCUMENTS: tuple[str, ...] = (
    "benchmark.md",
    "boundary.json",
    "finding.md",
    "metrics.json",
)

_CONSTANT_KEYS: tuple[str, ...] = (
    "min_support",
    "min_distinct_scenarios",
    "max_accuracy_gap",
    "min_coverage",
    "min_availability",
)

_ROW = "expected \\ "

#: Constant columns of a proposed-route matrix: the proposal, or a failed call.
_PROPOSED_COLUMNS: tuple[str, ...] = (*corpus.ROUTES, "failed")

_SEPARATOR = "---"

Row = Mapping[str, Any]


class ReportError(ValueError):
    """The run directories cannot be reported on as given."""


def _sha256_file(path: Path) -> str:
    """The SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_rows(path: Path) -> list[dict[str, Any]]:
    """Read a ledger's lines; a missing ledger is an empty one."""
    return replay.ledger_rows(path)


def _load_runs(paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    """Group the run directories by comparator, refusing duplicates."""
    runs: dict[str, dict[str, Any]] = {}
    for path in paths:
        header = json.loads((path / "run.json").read_text(encoding="utf-8"))
        if not isinstance(header, dict):
            raise ReportError(f"{path / 'run.json'} is not a JSON object")
        comparator = header.get("comparator")
        if comparator in runs:
            raise ReportError(f"two runs claim comparator {comparator}")
        runs[str(comparator)] = {
            "run_dir": path,
            "header": header,
            "rows": _load_rows(path / "cells.jsonl"),
        }
    missing = sorted(set(replay.COMPARATORS) - set(runs))
    if missing:
        raise ReportError(f"no run for {', '.join(missing)}")
    digests = {run["header"].get("scenarios_sha256") for run in runs.values()}
    if len(digests) != 1:
        raise ReportError("the runs measured different corpora")
    return runs


def _rounded(value: Any) -> Any:
    """Round every float to four places, leaving counts and text alone."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, Mapping):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    return value


def _json(document: Any) -> str:
    """Render a document the way C-8 requires: sorted, indented, rounded."""
    return json.dumps(_rounded(document), indent=2, sort_keys=True) + "\n"


def _text(value: Any) -> str:
    """One table cell: four decimals for a float, an em dash for nothing."""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{round(value, 4):.4f}"
    return str(value)


def _usd(value: Any) -> str:
    """The cost column: priced in dollars, or the subscription note."""
    if isinstance(value, float):
        return f"${round(value, 4):.4f}"
    return "*subscription, unpriced*"


def _block(rows: Sequence[Row]) -> dict[str, Any]:
    """One S-3 block: every T2 summary, over the rows it was given."""
    declared = corpus.BOUNDARY
    confidence = (
        metrics.calibration(rows, "confidence")
        if any(row.get("confidence") is not None for row in rows)
        else None
    )
    return {
        **metrics.accuracy_summary(rows),
        "confusion_routed": metrics.routed_confusion(rows),
        "confusion_proposed": metrics.proposed_confusion(rows),
        "calibration": metrics.calibration(rows),
        "calibration_confidence": confidence,
        "escalation": metrics.escalation(rows),
        "latency": metrics.latency(rows),
        "cost": metrics.cost(rows),
        "variance": metrics.variance(rows),
        "errors": metrics.errors_at(
            rows,
            float(declared["declared_accept_at"]),
            float(declared["declared_min_margin"]),
        ),
    }


def _comparator_document(rows: Sequence[Row]) -> dict[str, Any]:
    """One comparator's S-3 entry: the three blocks, the sweep, the flips."""
    return {
        "overall": _block(rows),
        "clear": _block([row for row in rows if row["stratum"] == "clear"]),
        "borderline": _block([row for row in rows if row["stratum"] == "borderline"]),
        "sweep": metrics.sweep(rows),
        "flip_points": metrics.flip_points(rows),
    }


def _provenance(runs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The B-23 block every artifact carries, so each stands alone.

    Corpus version and digest, each run's id, identity digest and ledger
    digest, and the repository commit the runs measured from.
    """
    commits = {run["header"].get("repo_commit") for run in runs.values()}
    return {
        "corpus": {
            "version": runs["hermetic"]["header"].get("corpus"),
            "sha256": runs["hermetic"]["header"].get("scenarios_sha256"),
        },
        "runs": {
            comparator: {
                "run_id": runs[comparator]["header"].get("run_id"),
                "identity_sha256": runs[comparator]["header"].get("identity_sha256"),
                "ledger_sha256": _sha256_file(
                    runs[comparator]["run_dir"] / "cells.jsonl"
                ),
                "started_at": runs[comparator]["header"].get("started_at"),
                "cells": len(runs[comparator]["rows"]),
            }
            for comparator in replay.COMPARATORS
        },
        "repo_commit": commits.pop() if len(commits) == 1 else "mixed",
    }


def _provenance_lines(runs: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The B-23 block as markdown, for the two prose documents."""
    provenance = _provenance(runs)
    lines = ["## Provenance", ""]
    for comparator in sorted(replay.COMPARATORS):
        entry = provenance["runs"][comparator]
        lines.append(
            f"- **{comparator}** — run `{entry['run_id']}`, identity "
            f"`{entry['identity_sha256']}`, ledger `{entry['ledger_sha256']}`, "
            f"{entry['cells']} cells."
        )
    lines.append(f"- Repository commit `{provenance['repo_commit']}`.")
    return lines


def _metrics_document(
    runs: Mapping[str, Mapping[str, Any]],
    comparators: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """The whole of S-3."""
    return {
        "provenance": _provenance(runs),
        "comparators": {
            comparator: comparators[comparator] for comparator in replay.COMPARATORS
        },
        "agreement": {
            f"{left}|{right}": metrics.agreement(
                runs[left]["rows"], runs[right]["rows"]
            )
            for index, left in enumerate(replay.COMPARATORS)
            for right in replay.COMPARATORS[index + 1 :]
        },
    }


def _boundary_document(
    runs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """The whole of C-9, verdict and uncertainty included."""
    header = runs["hermetic"]["header"]
    document: dict[str, Any] = {
        "provenance": _provenance(runs),
        "corpus": {
            "version": header.get("corpus"),
            "sha256": header.get("scenarios_sha256"),
        },
        "declared": {
            "accept_at": corpus.BOUNDARY["declared_accept_at"],
            "min_margin": corpus.BOUNDARY["declared_min_margin"],
        },
        "constants": {key: corpus.BOUNDARY[key] for key in _CONSTANT_KEYS},
        **metrics.boundary(runs["hermetic"]["rows"], runs["frontier"]["rows"]),
    }
    document["verdict"], document["uncertainty"] = metrics.verdict(
        document,
        runs["hermetic"]["rows"],
        runs["deterministic"]["rows"],
    )
    return document


def _table(head: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    """A markdown table, columns padded to a fixed separator width."""
    separator = "|" + "|".join(_SEPARATOR for _ in head) + "|"
    lines = ["| " + " | ".join(head) + " |", separator]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _matrix(
    corner: str, table: Mapping[str, Mapping[str, int]], columns: Sequence[str]
) -> list[str]:
    """One confusion matrix, expected down, recorded or proposed across."""
    rows = [
        [expected] + [str(table.get(expected, {}).get(column, 0)) for column in columns]
        for expected in corpus.ROUTES
    ]
    return _table([corner, *columns], rows)


def _benchmark(
    runs: Mapping[str, Mapping[str, Any]],
    comparators: Mapping[str, Mapping[str, Any]],
) -> str:
    """C-8's benchmark: one summary row per comparator, then the detail."""
    lines = [
        "# Hermetic routing benchmark",
        "",
        f"Corpus `{runs['hermetic']['header'].get('corpus')}`, "
        f"sha256 `{runs['hermetic']['header'].get('scenarios_sha256')}`.",
        "",
        *_provenance_lines(runs),
        "",
        "## Summary",
        "",
    ]
    head = [
        "comparator",
        "availability",
        "routed accuracy",
        "macro-F1",
        "coverage",
        "selective accuracy",
        "ECE",
        "Brier",
        "escalation precision",
        "escalation recall",
        "false continue",
        "unsafe continue",
        "false stop",
        "p50 latency",
        "p95 latency",
        "cost per run",
        "tokens per correct route",
        "flips",
    ]
    rows: list[list[str]] = []
    for comparator in sorted(replay.COMPARATORS):
        block = comparators[comparator]["overall"]
        escalation = block["escalation"]
        errors = block["errors"]
        cost = block["cost"]
        stale = errors["false_stop"]
        rows.append(
            [
                comparator,
                _text(block["availability"]),
                _text(block["routed_accuracy"]),
                _text(block["macro_f1"]),
                _text(escalation["coverage"]),
                _text(escalation["selective_accuracy"]),
                _text(block["calibration"]["ece"]),
                _text(block["calibration"]["brier"]),
                _text(escalation["precision"]),
                _text(escalation["recall"]),
                _text(errors["false_continue"]),
                _text(errors["unsafe_continue"]),
                f"{stale['fallback']}/{stale['proposal']}",
                _text(block["latency"]["p50"]),
                _text(block["latency"]["p95"]),
                _usd(cost["usd_total"]),
                _text(cost["tokens_per_correct_route"]),
                _text(block["variance"]["flips"]),
            ]
        )
    lines.extend(_table(head, rows))
    lines.extend(["", "## Confusion matrices", ""])
    for comparator in sorted(replay.COMPARATORS):
        rows_taken = runs[comparator]["rows"]
        lines.append(f"Recorded route — `{comparator}`.")
        lines.append("")
        lines.extend(
            _matrix(
                _ROW + "route",
                metrics.routed_confusion(rows_taken),
                corpus.ROUTES,
            )
        )
        lines.append("")
        lines.append(f"Proposed route — `{comparator}`.")
        lines.append("")
        lines.extend(
            _matrix(
                _ROW + "proposed",
                metrics.proposed_confusion(rows_taken),
                _PROPOSED_COLUMNS,
            )
        )
        lines.append("")
    margin = float(corpus.BOUNDARY["declared_min_margin"])
    lines.extend(
        [
            f"## Threshold sweep at min_margin = {margin:.2f}",
            "",
        ]
    )
    sweep_head = [
        "comparator",
        "accept_at",
        "coverage",
        "selective accuracy",
        "false continue",
        "unsafe continue",
        "false stop",
    ]
    sweep_rows: list[list[str]] = []
    for comparator in sorted(replay.COMPARATORS):
        for point in metrics.sweep(runs[comparator]["rows"]):
            if float(point["min_margin"]) != margin:
                continue
            sweep_rows.append(
                [
                    comparator,
                    _text(point["accept_at"]),
                    _text(point["coverage"]),
                    _text(point["selective_accuracy"]),
                    _text(point["false_continue"]),
                    _text(point["unsafe_continue"]),
                    _text(point["false_stop"]),
                ]
            )
    lines.extend(_table(sweep_head, sweep_rows))
    lines.append("")
    return "\n".join(lines)


def _route_sentence(route: str, entry: Mapping[str, Any]) -> str:
    """One route of the boundary, in words."""
    status = entry["status"]
    if status == "trusted":
        return (
            f"- **{route}** — trusted to replace the frontier decision for proposals "
            f"of `{route}` at p ≥ {float(entry['accept_at']):.2f} "
            f"(support {entry['support']} over {entry['scenarios']} scenarios; "
            f"accuracy {float(entry['accuracy']):.4f} against the frontier's "
            f"{float(entry['frontier_accuracy']):.4f}; coverage "
            f"{float(entry['coverage']):.4f})."
        )
    if status == "insufficient evidence":
        return (
            f"- **{route}** — insufficient evidence "
            f"(support {entry['support']}, below the bar)."
        )
    return f"- **{route}** — escalation still required."


def _deviations(runs: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """What departed from a clean run, each named with its count."""
    notes: list[str] = []
    commits = {
        comparator: run["header"].get("repo_commit") for comparator, run in runs.items()
    }
    if len(set(commits.values())) > 1:
        named = ", ".join(f"{c} at {k}" for c, k in sorted(commits.items()))
        notes.append(f"the runs came from different commits: {named}.")
    cli_versions = {
        str((row["frontier"] or {}).get("cli_version"))
        for row in runs["frontier"]["rows"]
        if isinstance(row["frontier"], dict)
        and (row["frontier"] or {}).get("cli_version")
    }
    if len(cli_versions) > 1:
        notes.append(
            f"more than one CLI version answered: {', '.join(sorted(cli_versions))}."
        )
    for comparator in sorted(replay.COMPARATORS):
        rows = runs[comparator]["rows"]
        skipped = sum(1 for row in rows if row["status"] == "not_attempted")
        if skipped:
            notes.append(f"{comparator}: {skipped} cells not attempted.")
        kinds: dict[str, int] = {}
        for row in rows:
            failure = row["failure"]
            if row["status"] == "failed" and isinstance(failure, dict):
                kind = str(failure.get("kind"))
                kinds[kind] = kinds.get(kind, 0) + 1
        for kind, count in sorted(kinds.items()):
            notes.append(f"{comparator}: {count} cells failed with {kind}.")
        mismatched = sum(
            1
            for row in rows
            if isinstance(row["frontier"], dict)
            and row["frontier"].get("model_mismatch")
        )
        if mismatched:
            notes.append(
                f"{comparator}: {mismatched} cells answered with another model."
            )
    return notes


def _finding(
    runs: Mapping[str, Mapping[str, Any]], boundary_doc: Mapping[str, Any]
) -> str:
    """C-8's finding: what the boundary says, in words, and what was odd."""
    header = runs["hermetic"]["header"]
    routes = boundary_doc["routes"]
    lines = [
        "# Finding",
        "",
        f"Corpus `{header.get('corpus')}`, "
        f"scenarios sha256 `{header.get('scenarios_sha256')}`.",
        "",
        *_provenance_lines(runs),
        "",
        "## Boundary",
        "",
    ]
    lines.extend(_route_sentence(route, routes[route]) for route in corpus.ROUTES)
    lines.extend(
        [
            "",
            f"Availability at the declared point: "
            f"{float(boundary_doc['availability']):.4f}; unsafe-continue "
            f"{boundary_doc['unsafe_continue_at_declared']} cells.",
            "",
            "## Verdict",
            "",
            f"**{boundary_doc['verdict']}**.",
        ]
    )
    if boundary_doc["uncertainty"]:
        lines.append("")
        lines.append(str(boundary_doc["uncertainty"]))
    lines.extend(["", "## Deviations", ""])
    notes = _deviations(runs)
    lines.extend(f"- {note}" for note in notes)
    if not notes:
        lines.append("- none.")
    lines.append("")
    return "\n".join(lines)


def _render(runs: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """Render the four documents, in :data:`DOCUMENTS` order."""
    boundary_doc = _boundary_document(runs)
    comparators = {
        comparator: _comparator_document(runs[comparator]["rows"])
        for comparator in replay.COMPARATORS
    }
    rendered = {
        "benchmark.md": _benchmark(runs, comparators),
        "boundary.json": _json(boundary_doc),
        "finding.md": _finding(runs, boundary_doc),
        "metrics.json": _json(_metrics_document(runs, comparators)),
    }
    return {name: rendered[name] for name in DOCUMENTS}


def _parser() -> argparse.ArgumentParser:
    """The C-8 command line."""
    parser = argparse.ArgumentParser(prog="tests.hermetic_eval.report")
    parser.add_argument("--run-dir", action="append", default=[], required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--check", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Write the benchmark documents, or check that they still hold."""
    args = _parser().parse_args(argv)
    if args.out is None and args.check is None:
        print("one of --out or --check is required")
        return 2
    try:
        runs = _load_runs([Path(path) for path in args.run_dir])
        declared_at = float(corpus.BOUNDARY["declared_accept_at"])
        declared_margin = float(corpus.BOUNDARY["declared_min_margin"])
        for comparator in replay.COMPARATORS:
            for scenario, repeat in metrics.conformance(
                runs[comparator]["rows"], declared_at, declared_margin
            ):
                print(
                    f"{comparator}: cell ({scenario}, repeat {repeat}) disagrees "
                    "with the declared rule"
                )
                return 4
        documents = _render(runs)
    except (ReportError, OSError, ValueError) as error:
        print(error)
        return 2

    if args.out is not None:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name in DOCUMENTS:
            (out / name).write_text(documents[name], encoding="utf-8")
    if args.check is not None:
        checked = Path(args.check)
        for name in DOCUMENTS:
            path = checked / name
            try:
                existing = path.read_text(encoding="utf-8")
            except OSError as error:
                print(error)
                return 1
            if existing != documents[name]:
                print(f"{path} differs")
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
