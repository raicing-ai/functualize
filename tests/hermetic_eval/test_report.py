"""Offline tests for the report command.

The three ledgers come from ``replay.main`` driven by the fake comparators in
``test_replay``, so the rows are produced by the real router and the real
decision gate. Nothing here spawns a process (spec B-28).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.hermetic_eval import corpus, replay, report
from tests.hermetic_eval.test_replay import (
    _COMMIT,
    Fakes,
    argv,
    install_offline,
    ledger,
    write_corpus,
)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this module runs with no way to spawn a process."""
    install_offline(monkeypatch)


@pytest.fixture(scope="module")
def scenarios(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The frozen corpus's scenario file, the digest the reports must carry."""
    root = write_corpus(tmp_path_factory.mktemp("corpus") / "corpus")
    return root / "v1" / "scenarios.jsonl"


@pytest.fixture(scope="module")
def runs(scenarios: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """One complete run directory per comparator, over one frozen corpus.

    Module scoped: the three runs take forty-five cells, and no test here
    writes to a ledger it shares — the one that doctors a row copies it first.
    A module-scoped fixture is built before any function-scoped autouse patch,
    so the offline guard is installed around the runs themselves: otherwise the
    header writer would spawn the one process these tests promise not to.
    """
    patcher = pytest.MonkeyPatch()
    install_offline(patcher)
    try:
        root = scenarios.parents[1]
        scratch = tmp_path_factory.mktemp("runs")
        fakes = Fakes()
        assert (
            replay.main(
                ["--freeze", "--corpus", "v1", "--corpus-root", str(root)],
                factories=fakes.factories(),
            )
            == 0
        )
        directories: dict[str, Path] = {}
        for comparator in replay.COMPARATORS:
            run_dir = scratch / f"run-{comparator}"
            assert (
                replay.main(
                    argv(root, run_dir, comparator=comparator),
                    factories=fakes.factories(),
                )
                == 0
            )
            assert len(ledger(run_dir)) == 15
            directories[comparator] = run_dir
        return directories
    finally:
        patcher.undo()


def _args(directories: dict[str, Path]) -> list[str]:
    """The three ``--run-dir`` flags, in the comparators' declared order."""
    arguments: list[str] = []
    for comparator in replay.COMPARATORS:
        arguments += ["--run-dir", str(directories[comparator])]
    return arguments


def _read(directory: Path) -> dict[str, bytes]:
    return {name: (directory / name).read_bytes() for name in sorted(report.DOCUMENTS)}


def _rows_of(run_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (run_dir / "cells.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def test_the_four_documents_render_reproducibly(
    runs: dict[str, Path], tmp_path: Path
) -> None:
    """The same ledgers render the same bytes, twice."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert report.main([*_args(runs), "--out", str(first)]) == 0
    assert report.main([*_args(runs), "--out", str(second)]) == 0
    assert sorted(path.name for path in first.iterdir()) == sorted(report.DOCUMENTS)
    assert _read(first) == _read(second)


def test_check_accepts_the_documents_and_notices_one_byte(
    runs: dict[str, Path], tmp_path: Path
) -> None:
    """``--check`` compares byte for byte against what it renders."""
    out = tmp_path / "out"
    assert report.main([*_args(runs), "--out", str(out)]) == 0
    assert report.main([*_args(runs), "--check", str(out)]) == 0
    benchmark = out / "benchmark.md"
    rendered = benchmark.read_text(encoding="utf-8")
    assert rendered.endswith("\n")
    benchmark.write_text(rendered[:-1] + "x", encoding="utf-8")
    assert report.main([*_args(runs), "--check", str(out)]) == 1


def test_every_document_carries_the_corpus_digest(
    runs: dict[str, Path], scenarios: Path, tmp_path: Path
) -> None:
    """A report names the frozen corpus it measured."""
    out = tmp_path / "out"
    assert report.main([*_args(runs), "--out", str(out)]) == 0
    digest = corpus.corpus_sha256(scenarios)
    for name in report.DOCUMENTS:
        assert digest in (out / name).read_text(encoding="utf-8")


def test_every_document_carries_the_run_provenance(
    runs: dict[str, Path], tmp_path: Path
) -> None:
    """B-23: each artifact alone names its runs, identities, ledgers, commit."""
    out = tmp_path / "out"
    assert report.main([*_args(runs), "--out", str(out)]) == 0
    for name in report.DOCUMENTS:
        text = (out / name).read_text(encoding="utf-8")
        for comparator in replay.COMPARATORS:
            header = json.loads(
                (runs[comparator] / "run.json").read_text(encoding="utf-8")
            )
            ledger_sha = hashlib.sha256(
                (runs[comparator] / "cells.jsonl").read_bytes()
            ).hexdigest()
            assert header["run_id"] in text
            assert header["identity_sha256"] in text
            assert ledger_sha in text
        assert _COMMIT in text


def test_a_row_that_contradicts_the_rule_refuses_to_report(
    runs: dict[str, Path], tmp_path: Path
) -> None:
    """A ledger route the declared rule cannot produce is a refusal, not a report."""
    doctored = tmp_path / "doctored"
    shutil.copytree(runs["hermetic"], doctored)
    rows = _rows_of(doctored)
    rows[0]["route"] = "human_review"
    (doctored / "cells.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    directories = {**runs, "hermetic": doctored}
    assert report.main([*_args(directories), "--out", str(tmp_path / "out")]) == 4


def test_two_runs_of_one_comparator_are_refused(
    runs: dict[str, Path], tmp_path: Path
) -> None:
    """Two ledgers claiming the same comparator are ambiguous."""
    arguments = [*_args(runs), "--run-dir", str(runs["hermetic"])]
    assert report.main([*arguments, "--out", str(tmp_path / "out")]) == 2


def test_a_missing_comparator_is_refused(runs: dict[str, Path], tmp_path: Path) -> None:
    """A report needs all three comparators before it means anything."""
    arguments = [
        "--run-dir",
        str(runs["hermetic"]),
        "--run-dir",
        str(runs["frontier"]),
        "--out",
        str(tmp_path / "out"),
    ]
    assert report.main(arguments) == 2


def test_neither_out_nor_check_is_a_usage_error(runs: dict[str, Path]) -> None:
    """Without a destination the command has nothing to do."""
    assert report.main(_args(runs)) == 2
