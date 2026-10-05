"""Offline tests for the replay command.

``test_report.py`` reuses this module's ``SCENARIOS``, ``write_corpus``,
``Fakes``, ``argv``, ``rows`` and ``install_offline``: the corpus, the fakes
and the no-subprocess guard are shared between the two command tests.

Each test drives the real router with a fake comparator: the app, the example
router, the decision gate and the ledger are the production path, and the
provider is the only thing replaced. Nothing here spawns a process (spec B-28),
which is why ``replay._repo_commit`` and the ``subprocess`` module it uses are
both replaced before any test runs.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from functualize.plugin import (
    ChoiceRequest,
    DecisionFailure,
    DecisionProvenance,
    DecisionProvider,
    DecisionResult,
    DecisionUnavailableError,
)
from tests.hermetic_eval import replay
from tests.hermetic_eval._router import load_router
from tests.hermetic_eval.comparators import FrontierCall

#: The fixture corpus: one scenario per route the router can propose, with
#: texts that share no substring with an id, a stratum or a rationale.
SCENARIOS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "s01",
        "What are your opening hours on Sunday?",
        "deterministic",
        "clear",
        "a lookup answers it",
    ),
    (
        "s02",
        "Summarise this paragraph in one sentence.",
        "cheap_model",
        "clear",
        "one short text task",
    ),
    (
        "s03",
        "I was charged twice and want my money back.",
        "human_review",
        "borderline",
        "a refund needs a person",
    ),
)

_COMMIT = "0" * 40


class FakeProvider:
    """A comparator that answers from a script and records what it was asked."""

    def __init__(
        self, name: str, *, mismatch: bool = False, fail_at: int | None = None
    ) -> None:
        self.name = name
        self.mismatch = mismatch
        self.fail_at = fail_at
        self.requests: list[ChoiceRequest] = []
        self.calls: list[FrontierCall] = []

    def choose(self, request: ChoiceRequest) -> DecisionResult[str]:
        """Answer the gate, or fail the call the script says to fail."""
        self.requests.append(request)
        if self.fail_at is not None and len(self.requests) == self.fail_at:
            raise DecisionUnavailableError(
                kind=DecisionFailure.RATE_LIMITED,
                provider="fake",
                status=429,
                retry_after=19014.0,
                detail="Rate limit exceeded",
            )
        self.calls.append(
            FrontierCall(
                cli_version="codex-cli 0.156.1",
                model="gpt-6-astra-fast" if self.mismatch else "gpt-6-astra",
                model_mismatch=self.mismatch,
                usage={"input_tokens": 10, "output_tokens": 2},
            )
        )
        return DecisionResult(
            value="cheap_model",
            provider=self.name,
            model="fake-1",
            provenance=DecisionProvenance(
                requested_model="fake-1",
                latency_seconds=0.001,
                input_tokens=10,
                output_tokens=2,
            ),
            distribution={"cheap_model": 0.9, "human_review": 0.1},
            confidence=0.9,
        )


class Fakes:
    """The three injected comparators, rebuilt on every factory call."""

    def __init__(self, *, mismatch: bool = False, fail_at: int | None = None) -> None:
        self.mismatch = mismatch
        self.fail_at = fail_at
        self.providers: dict[str, FakeProvider] = {}

    def _factory(self, name: str) -> Callable[[Path], tuple[DecisionProvider, Any]]:
        def build(_run_dir: Path) -> tuple[DecisionProvider, Any]:
            provider = FakeProvider(name, mismatch=self.mismatch, fail_at=self.fail_at)
            self.providers[name] = provider
            return (provider, {"comparator": name, "fake": True})

        return build

    def factories(self) -> dict[str, Callable[[Path], tuple[DecisionProvider, Any]]]:
        """Every comparator's factory, so a freeze can identity all three."""
        return {name: self._factory(name) for name in replay.COMPARATORS}

    def provider(self, name: str = "hermetic") -> FakeProvider:
        """The fake the last factory call built for ``name``."""
        return self.providers[name]


class BudgetClock:
    """A monotonic clock that trips after a set number of cells."""

    def __init__(self, cells: int) -> None:
        self.cells = cells
        self.ticks = 0

    def __call__(self) -> float:
        self.ticks += 1
        return 0.0 if self.ticks <= self.cells + 1 else 1000.0


def install_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the one process the command can spawn, and forbid any other.

    ``subprocess`` is imported here, not at module level, so this module does
    not join ``comparators.py`` in the import surface the spec pins (B-28).
    """
    import subprocess

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("these tests must not spawn a process")

    monkeypatch.setattr(replay, "_repo_commit", lambda: _COMMIT)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


def write_corpus(root: Path) -> Path:
    """Write the three-scenario version 1 corpus under ``root``, unfrozen."""
    version = root / "v1"
    version.mkdir(parents=True)
    lines = []
    for scenario_id, state, expected, stratum, rationale in SCENARIOS:
        lines.append(
            json.dumps(
                {
                    "id": scenario_id,
                    "state": state,
                    "expected": expected,
                    "stratum": stratum,
                    "rationale": rationale,
                }
            )
        )
    (version / "scenarios.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def ledger(run_dir: Path) -> list[dict[str, Any]]:
    """The ledger rows a run directory holds."""
    return replay.ledger_rows(run_dir / "cells.jsonl")


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this module runs with no way to spawn a process."""
    install_offline(monkeypatch)


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    """A three-scenario version 1 corpus directory, not yet frozen."""
    return write_corpus(tmp_path / "corpus")


@pytest.fixture
def frozen(corpus_root: Path, fakes: Fakes) -> Path:
    """The corpus root, frozen against the fake comparators' identities."""
    code = replay.main(
        [
            "--freeze",
            "--corpus",
            "v1",
            "--corpus-root",
            str(corpus_root),
        ],
        factories=fakes.factories(),
    )
    assert code == 0
    return corpus_root


@pytest.fixture
def fakes() -> Fakes:
    """The default fake set: all three scripts answer the same way."""
    return Fakes()


def argv(corpus_root: Path, run_dir: Path, comparator: str = "hermetic") -> list[str]:
    return [
        "--corpus",
        "v1",
        "--comparator",
        comparator,
        "--run-dir",
        str(run_dir),
        "--corpus-root",
        str(corpus_root),
    ]


def test_a_full_run_writes_one_row_per_cell(
    frozen: Path, tmp_path: Path, fakes: Fakes
) -> None:
    """Every ordered cell is attempted once, in the lock's order."""
    run_dir = tmp_path / "run"
    code = replay.main(argv(frozen, run_dir), factories=fakes.factories())
    assert code == 0
    rows = ledger(run_dir)
    assert len(rows) == len(SCENARIOS) * 5
    assert [row["cell"] for row in rows] == list(range(1, len(rows) + 1))
    assert {row["status"] for row in rows} == {"routed"}
    header = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert header["comparator"] == "hermetic"
    assert header["repo_commit"] == _COMMIT
    assert header["corpus"] == "v1"


def test_requests_carry_only_the_scenario_state(
    frozen: Path, tmp_path: Path, fakes: Fakes
) -> None:
    """AC-3: the gate sees the scenario's text and the router's own question."""
    run_dir = tmp_path / "run"
    assert replay.main(argv(frozen, run_dir), factories=fakes.factories()) == 0
    router = load_router().ROUTER
    requests = fakes.provider().requests
    assert requests
    states = {scenario[1] for scenario in SCENARIOS}
    for request in requests:
        assert request.state in states
        assert request.instructions == router.instructions
        assert dict(request.options) == dict(router.options)
        printed = repr(request)
        for scenario_id, _state, _expected, stratum, rationale in SCENARIOS:
            assert scenario_id not in printed
            assert stratum not in printed
            assert rationale not in printed
        assert "expected" not in printed


def test_a_changed_scenario_file_refuses_before_writing_anything(
    frozen: Path, tmp_path: Path, fakes: Fakes
) -> None:
    """AC-2: a scenario byte that no longer matches the lock refuses, early."""
    scenarios = frozen / "v1" / "scenarios.jsonl"
    scenarios.write_text(
        scenarios.read_text(encoding="utf-8").replace("Sunday", "Sundae"),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    assert replay.main(argv(frozen, run_dir), factories=fakes.factories()) == 2
    assert not run_dir.exists()


def test_a_deleted_lock_refuses_before_writing_anything(
    frozen: Path, tmp_path: Path, fakes: Fakes
) -> None:
    """AC-2: an unfrozen version directory refuses, early."""
    (frozen / "v1" / "corpus.lock.json").unlink()
    run_dir = tmp_path / "run"
    assert replay.main(argv(frozen, run_dir), factories=fakes.factories()) == 2
    assert not run_dir.exists()


def test_a_different_comparator_in_the_run_directory_refuses(
    frozen: Path, tmp_path: Path, fakes: Fakes
) -> None:
    """A run directory belongs to the comparator that opened it."""
    run_dir = tmp_path / "run"
    assert replay.main(argv(frozen, run_dir), factories=fakes.factories()) == 0
    code = replay.main(
        argv(frozen, run_dir, comparator="frontier"), factories=fakes.factories()
    )
    assert code == 2
    assert len(ledger(run_dir)) == len(SCENARIOS) * 5


def test_one_rule_digest_across_every_row(
    frozen: Path, tmp_path: Path, fakes: Fakes
) -> None:
    """S-3: the gate declaration is digested once, and never moves."""
    run_dir = tmp_path / "run"
    assert replay.main(argv(frozen, run_dir), factories=fakes.factories()) == 0
    digests = {row["rule_digest"] for row in ledger(run_dir)}
    assert len(digests) == 1
    assert None not in digests


def test_a_rate_limited_cell_pauses_and_resumes(
    frozen: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-6: the second call fails, the run pauses, and the resume skips it."""
    run_dir = tmp_path / "run"
    failing = Fakes(fail_at=2)

    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the replay command must never sleep")

    monkeypatch.setattr(time, "sleep", explode)
    first = replay.main(argv(frozen, run_dir), factories=failing.factories())
    assert first == 0
    assert "resume after" in capsys.readouterr().out
    rows = ledger(run_dir)
    assert len(rows) == 2
    assert rows[1]["status"] == "failed"
    assert rows[1]["failure"]["kind"] == "rate_limited"
    assert rows[1]["route"] == "human_review"
    assert rows[0]["status"] == "routed"

    resumed = Fakes()
    seconded = replay.main(argv(frozen, run_dir), factories=resumed.factories())
    assert seconded == 0
    after = ledger(run_dir)
    assert len(after) == len(SCENARIOS) * 5
    assert after[:2] == rows
    assert resumed.provider().requests
    assert len(resumed.provider().requests) == len(after) - 2


def test_a_budget_stop_resumes_into_the_same_ledger(
    frozen: Path, tmp_path: Path
) -> None:
    """AC-7: a stopped run and its resume equal one uninterrupted run."""
    split = tmp_path / "split"
    clock = BudgetClock(2)
    assert (
        replay.main(argv(frozen, split), factories=Fakes().factories(), clock=clock)
        == 0
    )
    assert len(ledger(split)) == 2
    assert (
        replay.main(
            argv(frozen, split), factories=Fakes().factories(), clock=lambda: 0.0
        )
        == 0
    )
    whole = tmp_path / "whole"
    assert (
        replay.main(
            argv(frozen, whole), factories=Fakes().factories(), clock=lambda: 0.0
        )
        == 0
    )

    def comparable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stripped = []
        for row in rows:
            kept = dict(row)
            kept.pop("started_at")
            kept.pop("latency_seconds")
            stripped.append(kept)
        return stripped

    assert comparable(ledger(split)) == comparable(ledger(whole))


def test_the_time_box_closes_the_run(
    frozen: Path, tmp_path: Path, fakes: Fakes
) -> None:
    """B-9: past the box, the remaining cells are recorded as not attempted."""
    run_dir = tmp_path / "run"
    started = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    assert (
        replay.main(
            argv(frozen, run_dir),
            factories=fakes.factories(),
            clock=BudgetClock(3),
            now=lambda: started,
        )
        == 0
    )
    assert len(ledger(run_dir)) == 3

    later = started + timedelta(hours=73)
    assert (
        replay.main(
            argv(frozen, run_dir),
            factories=fakes.factories(),
            now=lambda: later,
        )
        == 0
    )
    rows = ledger(run_dir)
    assert len(rows) == len(SCENARIOS) * 5
    assert [row["status"] for row in rows[3:]] == ["not_attempted"] * (len(rows) - 3)
    assert [row["cell"] for row in rows] == list(range(1, len(rows) + 1))


def test_a_frontier_model_mismatch_stops_the_run(
    frozen: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """B-7: an answer from another model stops the run and is recorded."""
    run_dir = tmp_path / "run"
    mismatched = Fakes(mismatch=True)
    code = replay.main(
        argv(frozen, run_dir, comparator="frontier"), factories=mismatched.factories()
    )
    assert code == 3
    assert "invalid_model" in capsys.readouterr().out
    rows = ledger(run_dir)
    assert len(rows) == 1
    assert rows[0]["status"] == "invalid_model"
    assert rows[0]["frontier"]["model_mismatch"] is True
