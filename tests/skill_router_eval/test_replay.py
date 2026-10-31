"""The replay, freeze and select commands: what a run may and may not do.

Every test here drives the real command surface — :func:`replay.main` and
:func:`select.main` — with injected comparator factories, so the workflow, the
gate and the ledger are the same code a measurement uses. Only the providers
are fakes, and the ones that misbehave are fakes on purpose: a rate limit, a
catalog that moved, a rule that changed between cells. The refusals are the
point of the module. A measurement that silently rebases itself onto a new
corpus, a reworded instruction or an edited provider is worse than no
measurement, and each test below pins one of those doors shut.

The clock and the "now" are seams, so the budget, the resume and the time box
are exercised without sleeping. ``subprocess`` never appears at module scope: a
hermetic test run may not spawn anything, and the header's commit lookup is the
one call that does — replaced here by a stub.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from functualize.plugin import (
    DecisionFailure,
    DecisionProvenance,
    DecisionProvider,
    DecisionResult,
    DecisionUnavailableError,
)
from tests.skill_router_eval import corpus, metrics, replay, select
from tests.skill_router_eval import selection as _selection_module
from tests.skill_router_eval.catalog import (
    OPTIONS,
    SKILLS,
    derive_catalog,
    option_meanings,
)
from tests.skill_router_eval.comparators import ESCALATED as NATIVE_ESCALATED
from tests.skill_router_eval.comparators import NativeCell
from tests.skill_router_eval.selection import select_decision

_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_NOW = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
_REPEATS = 1

_SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "id": "s1",
        "state": "func: command not found after the install script ran",
        "expected": "functualize-cli",
        "stratum": "clear",
        "rationale": "LABELING.md §2 — a CLI failure is a cli request.",
        "origin": "new",
    },
    {
        "id": "s2",
        "state": "write an agent skill with a SKILL.md and a frontmatter block",
        "expected": "functualize-skill",
        "stratum": "clear",
        "rationale": "LABELING.md §5 — authoring a skill is a skill request.",
        "origin": "new",
    },
    {
        "id": "s3",
        "state": "scaffold a new project and add a job to it",
        "expected": "functualize-app",
        "stratum": "borderline",
        "rationale": "LABELING.md §4 — both halves are app work.",
        "origin": "new",
    },
)


class Clock:
    """A ``now`` the test moves by hand."""

    def __init__(self, base: datetime = _NOW) -> None:
        self.base = base
        self.offset = timedelta(0)

    def __call__(self) -> datetime:
        return self.base + self.offset


class Ticker:
    """A monotonic clock that jumps once the run has started measuring."""

    def __init__(self, jump_after: int = 1, jump: float = 1000.0) -> None:
        self.calls = 0
        self.jump_after = jump_after
        self.jump = jump

    def __call__(self) -> float:
        self.calls += 1
        return 0.0 if self.calls <= self.jump_after else self.jump


class RecordingProvider(DecisionProvider):
    """A provider that proposes a scripted option per call and records requests."""

    name = "recording"

    def __init__(self, script: Callable[[int], DecisionResult[str] | None]) -> None:
        self.script = script
        self.calls: list[Any] = []

    def choose(self, request: Any) -> DecisionResult[str]:
        self.calls.append(request)
        decided = self.script(len(self.calls))
        if decided is None:
            raise DecisionUnavailableError(
                kind=DecisionFailure.RATE_LIMITED,
                provider=self.name,
                detail="the free window is spent",
                status=429,
                retry_after=120.0,
            )
        return decided

    def identity(self) -> dict[str, object]:
        return {"comparator": self.name}


class FakeNative:
    """The native comparator, without a provider call."""

    name = "native"

    def __init__(self, cells: list[NativeCell]) -> None:
        self.cells = cells
        self.seen: list[str] = []

    def select(self, state: str) -> NativeCell:
        self.seen.append(state)
        return self.cells[len(self.seen) - 1]

    def identity(self) -> dict[str, object]:
        return {"comparator": self.name}


def _answer(
    value: str = "functualize-cli",
    probability: float = 0.90,
    *,
    input_tokens: int = 938,
    output_tokens: int = 72,
) -> DecisionResult[str]:
    """One provider answer: ``value`` at ``probability``, the rest spread evenly."""
    rest = (1.0 - probability) / (len(OPTIONS) - 1)
    distribution = {option: rest for option in OPTIONS}
    distribution[value] = probability
    return DecisionResult(
        value=value,
        provider="recording",
        model="fake-1",
        provenance=DecisionProvenance(
            "fake-1",
            latency_seconds=0.0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
        distribution=distribution,
    )


#: What the default provider proposes per scenario: two accepted, one under the
#: threshold, keyed by id so the measurement order cannot change the answers.
_ANSWERS: dict[str, tuple[str, float]] = {
    "s1": ("functualize-cli", 0.90),
    "s2": ("functualize-skill", 0.55),
    "s3": ("functualize-app", 0.90),
}


def _scenario_at(index: int) -> dict[str, str]:
    """The scenario the ``index``-th cell measures, in the lock's order."""
    by_id = {scenario["id"]: scenario for scenario in _SCENARIOS}
    return by_id[_ordered()[index - 1][1]]


def _default_script(index: int) -> DecisionResult[str]:
    """The cell's own answer: two accepted, the second under the threshold."""
    option, probability = _ANSWERS[_scenario_at(index)["id"]]
    return _answer(option, probability)


def _factories(
    script: Callable[[int], DecisionResult[str] | None] = _default_script,
    *,
    native: FakeNative | None = None,
) -> dict[str, replay.Factory]:
    """Injected factories for the four comparators, each with a stable identity."""
    provider = RecordingProvider(script)
    native_arm = native if native is not None else _native_arm()

    def gated(_run_dir: Path) -> tuple[Any, dict[str, object]]:
        return provider, {"comparator": "recording"}

    return {
        "hermetic": gated,
        "frontier": gated,
        "deterministic": gated,
        "native": lambda _run_dir: (native_arm, {"comparator": "native"}),
    }


def _identities() -> dict[str, replay.Factory]:
    """The factories a freeze needs, built to answer the same identities."""

    def gated(_run_dir: Path) -> tuple[Any, dict[str, object]]:
        return object(), {"comparator": "recording"}

    def native(_run_dir: Path) -> tuple[Any, dict[str, object]]:
        return object(), {"comparator": "native"}

    return {
        "hermetic": gated,
        "frontier": gated,
        "deterministic": gated,
        "native": native,
    }


def _native_arm() -> FakeNative:
    """Three native cells: two answers and one timeout."""
    return FakeNative(
        [
            NativeCell(
                route="functualize-cli",
                failed=None,
                selected="functualize-cli",
                error=None,
                model="claude-sonnet-5",
                cost_usd=0.0421,
                latency_seconds=11.5,
            ),
            NativeCell(
                route=NATIVE_ESCALATED,
                failed={"kind": "timeout", "message": "timeout after 180s"},
                selected="functualize",
                error="timeout after 180s",
                model="claude-sonnet-5",
                cost_usd=0.0187,
                latency_seconds=180.0,
            ),
            NativeCell(
                route="functualize-app",
                failed=None,
                selected="functualize-app",
                error=None,
                model="claude-sonnet-5",
                cost_usd=0.0301,
                latency_seconds=9.0,
            ),
        ]
    )


def _write_corpus(version_dir: Path) -> Path:
    """A three-scenario corpus, frozen shape aside, in ``version_dir``."""
    version_dir.mkdir(parents=True, exist_ok=True)
    path = version_dir / "scenarios.jsonl"
    path.write_text(
        "\n".join(json.dumps(scenario) for scenario in _SCENARIOS) + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _one_repeat(monkeypatch: pytest.MonkeyPatch) -> None:
    """One repeat, so a test measures three cells rather than fifteen."""
    monkeypatch.setattr(corpus, "REPEATS", _REPEATS)
    monkeypatch.setattr(replay, "_repo_commit", lambda *_args, **_kwargs: _COMMIT)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """No command may sleep: a pause is a printed time, not a blocked run."""

    def refuse(_seconds: float) -> None:
        raise AssertionError("the replay slept")

    monkeypatch.setattr(time, "sleep", refuse)


@pytest.fixture
def version_dir(tmp_path: Path) -> Path:
    """A frozen version directory built by the real ``--freeze`` path."""
    _write_corpus(tmp_path / "v1")
    assert replay.main(_freeze_args(tmp_path), factories=_identities()) == 0
    return tmp_path / "v1"


def _freeze_args(root: Path) -> list[str]:
    return ["--freeze", "--corpus-root", str(root), "--corpus", "v1"]


def _run_args(
    root: Path,
    run_dir: Path,
    *,
    comparator: str = "hermetic",
    extra: list[str] | None = None,
) -> list[str]:
    args = [
        "--corpus-root",
        str(root),
        "--corpus",
        "v1",
        "--comparator",
        comparator,
        "--run-dir",
        str(run_dir),
    ]
    return args + list(extra or [])


def _rows(run_dir: Path) -> list[dict[str, Any]]:
    """The ledger as rows, in the order they were written."""
    path = run_dir / "cells.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _ordered() -> list[tuple[int, str]]:
    """The measurement order: the lock's seed and this module's repeat count."""
    return corpus.ordered_cells(
        [scenario["id"] for scenario in _SCENARIOS],
        seed=corpus.SEED,
        repeats=corpus.REPEATS,
    )


def _select_args(out: Path, tasks: Path) -> list[str]:
    """The C-7 command line for one selections file."""
    return ["--tasks", str(tasks), "--out", str(out)]


def _changed_copy(source: Path, destination: Path, name: str) -> Path:
    """Copy ``source`` to ``destination`` and change one byte in ``name``."""
    shutil.copytree(source, destination)
    target = destination / name
    data = bytearray(target.read_bytes())
    data[0] = ord("x") if data[0] != ord("x") else ord("y")
    target.write_bytes(bytes(data))
    return destination


def test_a_full_run_writes_one_row_per_ordered_cell(
    tmp_path: Path, version_dir: Path
) -> None:
    run_dir = tmp_path / "run"
    clock = Clock()
    assert (
        replay.main(
            _run_args(tmp_path, run_dir),
            factories=_factories(),
            clock=Ticker(jump_after=100),
            now=clock,
        )
        == 0
    )
    rows = _rows(run_dir)
    assert [(row["cell"], row["scenario"]) for row in rows] == [
        (index, scenario) for index, (_, scenario) in enumerate(_ordered(), 1)
    ]
    assert [row["status"] for row in rows] == ["routed"] * 3
    assert list(rows[0]) == [
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
    ]
    by_scenario = {row["scenario"]: row for row in rows}
    assert by_scenario["s1"]["route"] == "functualize-cli"
    assert by_scenario["s2"]["route"] == "escalated"
    assert by_scenario["s2"]["decided_by"] is None
    assert by_scenario["s2"]["probability"] == pytest.approx(0.55)
    assert by_scenario["s3"]["route"] == "functualize-app"
    assert by_scenario["s1"]["input_tokens"] == 938
    assert all(row["rule_digest"] for row in rows)
    assert len({row["rule_digest"] for row in rows}) == 1
    assert all(row["native"] is None for row in rows)
    header = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert header["comparator"] == "hermetic"
    assert header["run_id"].startswith("hermetic-")
    assert header["rule_digest"] == rows[0]["rule_digest"]
    assert header["repo_commit"] == _COMMIT
    assert (run_dir / "project" / ".functualize").is_dir()


def test_the_ledger_reproduces_the_offline_rule(
    tmp_path: Path, version_dir: Path
) -> None:
    """AC-9's fixture: every row a real walk wrote agrees with the rule."""
    run_dir = tmp_path / "run"
    assert replay.main(_run_args(tmp_path, run_dir), factories=_factories()) == 0
    rows = _rows(run_dir)
    assert len(rows) == 3
    assert [metrics.outcome_at(row) for row in rows] == [row["route"] for row in rows]


def test_no_request_carries_the_corpus(tmp_path: Path) -> None:
    """AC-5: the provider sees the state and the option meanings, nothing else."""
    _write_corpus(tmp_path / "v1")
    assert replay.main(_freeze_args(tmp_path), factories=_identities()) == 0
    provider = RecordingProvider(_default_script)
    factories = _factories()
    factories["hermetic"] = lambda _run_dir: (
        provider,
        {"comparator": "recording"},
    )
    assert (
        replay.main(
            _run_args(tmp_path, tmp_path / "run"),
            factories=factories,
            now=Clock(),
        )
        == 0
    )
    states = {scenario["id"]: scenario["state"] for scenario in _SCENARIOS}
    assert [call.state for call in provider.calls] == [
        states[scenario] for _, scenario in _ordered()
    ]
    meanings = option_meanings(derive_catalog())
    for call in provider.calls:
        assert list(call.options) == list(OPTIONS)
        assert dict(call.options) == meanings
        dumped = json.dumps(
            {
                "state": call.state,
                "instructions": call.instructions,
                "options": dict(call.options),
                "model": call.model,
            }
        )
        for scenario in _SCENARIOS:
            assert scenario["id"] not in dumped
            assert scenario["rationale"] not in dumped
        assert "stratum" not in dumped


def test_a_rate_limit_pauses_and_the_resume_continues(
    tmp_path: Path, version_dir: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """AC-7: cell 2 is attempted and recorded, then the run asks for a reopen."""
    run_dir = tmp_path / "run"
    script = lambda index: None if index == 2 else _default_script(index)  # noqa: E731
    assert replay.main(_run_args(tmp_path, run_dir), factories=_factories(script)) == 0
    rows = _rows(run_dir)
    assert len(rows) == 2
    assert rows[1]["status"] == "failed"
    assert rows[1]["route"] == "escalated"
    assert rows[1]["failure"]["kind"] == "rate_limited"
    printed = capfd.readouterr().out
    assert "resume after " in printed
    assert "resume after unknown" not in printed
    assert replay.main(_run_args(tmp_path, run_dir), factories=_factories()) == 0
    rows = _rows(run_dir)
    assert len(rows) == 3
    assert rows[2]["cell"] == 3
    assert [row["cell"] for row in rows] == [1, 2, 3]


def test_a_rate_limit_without_a_retry_after_still_pauses(
    tmp_path: Path, version_dir: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "run"

    def script(index: int) -> DecisionResult[str]:
        if index == 1:
            raise DecisionUnavailableError(
                kind=DecisionFailure.RATE_LIMITED,
                provider="recording",
                detail="spent, no reset header",
            )
        return _default_script(index)

    assert replay.main(_run_args(tmp_path, run_dir), factories=_factories(script)) == 0
    assert len(_rows(run_dir)) == 1
    assert "resume after unknown" in capfd.readouterr().out


def test_a_budgeted_run_and_its_resume_equal_an_uninterrupted_one(
    tmp_path: Path, version_dir: Path
) -> None:
    """AC-7: stopping early and resuming cannot change what is measured."""
    whole = tmp_path / "whole"
    assert (
        replay.main(
            _run_args(tmp_path, whole),
            factories=_factories(),
            clock=Ticker(jump_after=100),
            now=Clock(),
        )
        == 0
    )
    split = tmp_path / "split"
    assert (
        replay.main(
            _run_args(tmp_path, split, extra=["--budget-seconds", "0"]),
            factories=_factories(),
            clock=Ticker(jump_after=100),
            now=Clock(),
        )
        == 0
    )
    assert _rows(split) == []
    assert (
        replay.main(_run_args(tmp_path, split), factories=_factories(), now=Clock()) == 0
    )
    assert _comparable(_rows(split)) == _comparable(_rows(whole))
    assert len(_rows(whole)) == 3


def _comparable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows without the two fields a resume cannot reproduce."""
    return [
        {key: value for key, value in row.items() if key not in {"started_at", "latency_seconds"}}
        for row in rows
    ]


def test_the_budget_stops_between_cells(
    tmp_path: Path, version_dir: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "run"
    ticker = Ticker(jump_after=2, jump=10_000.0)
    assert (
        replay.main(
            _run_args(tmp_path, run_dir, extra=["--budget-seconds", "1"]),
            factories=_factories(),
            clock=ticker,
        )
        == 0
    )
    assert len(_rows(run_dir)) == 1
    assert "budget reached; next cell 2" in capfd.readouterr().out


def test_the_time_box_records_the_rest_as_not_attempted(
    tmp_path: Path, version_dir: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "run"
    clock = Clock()
    assert (
        replay.main(
            _run_args(tmp_path, run_dir, extra=["--budget-seconds", "0"]),
            factories=_factories(),
            clock=Ticker(jump_after=0),
            now=clock,
        )
        == 0
    )
    clock.offset = timedelta(hours=corpus.TIME_BOX_HOURS + 1)
    assert replay.main(_run_args(tmp_path, run_dir), factories=_factories(), now=clock) == 0
    rows = _rows(run_dir)
    assert [row["status"] for row in rows] == ["not_attempted"] * 3
    assert [row["route"] for row in rows] == [None] * 3
    assert "run complete" in capfd.readouterr().out


def test_the_header_is_written_once(tmp_path: Path, version_dir: Path) -> None:
    run_dir = tmp_path / "run"
    args = _run_args(tmp_path, run_dir, extra=["--budget-seconds", "0"])
    assert (
        replay.main(args, factories=_factories(), clock=Ticker(jump_after=0), now=Clock())
        == 0
    )
    first = (run_dir / "run.json").read_text(encoding="utf-8")
    assert replay.main(_run_args(tmp_path, run_dir), factories=_factories()) == 0
    assert (run_dir / "run.json").read_text(encoding="utf-8") == first


def test_a_resume_with_another_comparator_is_refused(
    tmp_path: Path, version_dir: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "run"
    assert (
        replay.main(
            _run_args(tmp_path, run_dir, extra=["--budget-seconds", "0"]),
            factories=_factories(),
            clock=Ticker(jump_after=0),
        )
        == 0
    )
    assert (
        replay.main(
            _run_args(tmp_path, run_dir, comparator="deterministic"),
            factories=_factories(),
        )
        == 2
    )
    assert "holds hermetic" in capfd.readouterr().out
    assert _rows(run_dir) == []


def test_a_missing_lock_refuses_and_writes_nothing(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    _write_corpus(tmp_path / "v1")
    run_dir = tmp_path / "run"
    assert replay.main(_run_args(tmp_path, run_dir), factories=_factories()) == 2
    assert not run_dir.exists()
    assert "missing lock file" in capfd.readouterr().out


def test_a_changed_scenario_refuses(tmp_path: Path, version_dir: Path) -> None:
    path = version_dir / "scenarios.jsonl"
    data = bytearray(path.read_bytes())
    data[0] = ord("x") if data[0] != ord("x") else ord("y")
    path.write_bytes(bytes(data))
    run_dir = tmp_path / "run"
    assert replay.main(_run_args(tmp_path, run_dir), factories=_factories()) == 2
    assert not run_dir.exists()


def test_a_changed_catalog_byte_refuses(tmp_path: Path, version_dir: Path) -> None:
    scratch_skills = _changed_copy(
        replay.REPO_ROOT / "skills", tmp_path / "skills", f"{SKILLS[0]}/SKILL.md"
    )
    run_dir = tmp_path / "run"
    args = _run_args(tmp_path, run_dir) + ["--skills-root", str(scratch_skills)]
    assert replay.main(args, factories=_factories()) == 2
    assert not run_dir.exists()


def test_a_changed_instruction_refuses(
    tmp_path: Path, version_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reworded instruction moves the probe's rule digest, so the lock refuses."""
    original = _selection_module.SELECT_INSTRUCTIONS
    monkeypatch.setattr(_selection_module, "SELECT_INSTRUCTIONS", original + " ")
    run_dir = tmp_path / "run"
    assert replay.main(_run_args(tmp_path, run_dir), factories=_factories()) == 2
    assert not run_dir.exists()


def test_a_changed_instrument_byte_refuses(
    tmp_path: Path, version_dir: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    scratch_repo = tmp_path / "repo"
    for name in sorted(corpus.INSTRUMENT_FILES):
        target = scratch_repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(replay.REPO_ROOT / name, target)
    changed = scratch_repo / "tests/skill_router_eval/selection.py"
    data = bytearray(changed.read_bytes())
    data[0] = ord("x") if data[0] != ord("x") else ord("y")
    changed.write_bytes(bytes(data))
    run_dir = tmp_path / "run"
    assert (
        replay.main(
            _run_args(tmp_path, run_dir),
            factories=_factories(),
            repo_root=scratch_repo,
        )
        == 2
    )
    assert "instrument" in capfd.readouterr().out
    assert not run_dir.exists()


def test_freeze_refuses_an_existing_lock(
    tmp_path: Path, version_dir: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    assert replay.main(_freeze_args(tmp_path), factories=_identities()) == 2
    assert "already exists" in capfd.readouterr().out


def test_a_cell_whose_rule_moved_is_not_appended(
    tmp_path: Path,
    version_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """The declaration changed under a running measurement: refuse, append nothing."""
    original = select_decision
    calls = {"count": 0}

    def drifting(entries: Any) -> Any:
        calls["count"] += 1
        decided = original(entries)
        # The probe is call 1 and cell 1 is call 2, so cell 2 is the first
        # walk that can observe the moved threshold.
        if calls["count"] >= 3:
            return replace(decided, min_margin=0.5)
        return decided

    monkeypatch.setattr(_selection_module, "select_decision", drifting)
    run_dir = tmp_path / "run"
    assert replay.main(_run_args(tmp_path, run_dir), factories=_factories()) == 2
    rows = _rows(run_dir)
    assert len(rows) == 1
    assert rows[0]["cell"] == 1
    assert "selection rule changed at cell 2" in capfd.readouterr().out


def test_a_native_run_records_the_cell_verbatim(
    tmp_path: Path, version_dir: Path
) -> None:
    run_dir = tmp_path / "run"
    arm = _native_arm()
    assert (
        replay.main(
            _run_args(tmp_path, run_dir, comparator="native"),
            factories=_factories(native=arm),
        )
        == 0
    )
    rows = _rows(run_dir)
    assert [row["status"] for row in rows] == ["routed", "failed", "routed"]
    assert all(row["comparator"] == "native" for row in rows)
    assert all(row["rule_digest"] is None for row in rows)
    assert all(row["decided_by"] == "native" for row in rows)
    assert all(
        list(row["native"]) == ["selected", "error", "model", "cost_usd"]
        for row in rows
    )
    assert rows[1]["route"] == "escalated"
    assert rows[1]["failure"] == {"kind": "timeout", "message": "timeout after 180s"}
    assert rows[1]["native"]["cost_usd"] == pytest.approx(0.0187)
    assert rows[0]["latency_seconds"] == pytest.approx(11.5)
    assert rows[0]["input_tokens"] is None
    states = {scenario["id"]: scenario["state"] for scenario in _SCENARIOS}
    assert arm.seen == [states[scenario] for _, scenario in _ordered()]


@pytest.mark.parametrize(
    ("name", "value"), [("FZ_EVAL_MODEL", "claude-other"), ("FZ_EVAL_SANDBOX", "docker")]
)
def test_a_native_override_is_refused_before_anything_is_written(
    tmp_path: Path,
    version_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    run_dir = tmp_path / "run"
    assert replay.main(_run_args(tmp_path, run_dir, comparator="native")) == 2
    assert not run_dir.exists()


def test_select_writes_the_selections(tmp_path: Path, version_dir: Path) -> None:
    out = tmp_path / "selections.json"
    tasks = replay.REPO_ROOT / "evals/suites/skill-router.yaml"
    provider = RecordingProvider(lambda _index: _answer("functualize", 0.90))
    factories = _factories()
    factories["hermetic"] = lambda _run_dir: (
        provider,
        {"comparator": "recording"},
    )
    assert (
        select.main(
            _select_args(out, tasks) + ["--corpus-root", str(tmp_path)],
            factories=factories,
        )
        == 0
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert list(payload) == [
        "catalog_sha256",
        "comparator",
        "identity_sha256",
        "repo_commit",
        "rule_digest",
        "instrument_sha256",
        "cases",
    ]
    assert payload["comparator"] == "hermetic"
    assert payload["repo_commit"] == _COMMIT
    assert list(payload["cases"]) == ["d1", "d2", "d3", "d4", "d5"]
    case = payload["cases"]["d1"]
    assert list(case) == [
        "outcome",
        "expected",
        "decided_by",
        "latency_seconds",
        "evidence",
    ]
    assert case["outcome"] == "functualize"
    assert case["decided_by"] == "decision"
    assert case["evidence"]["schema"] == "decision-evidence/1"
    assert payload["rule_digest"].startswith("sha256:")


def test_select_refuses_to_write_inside_the_repository(
    tmp_path: Path, version_dir: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    inside = replay.REPO_ROOT / "selections-should-not-exist.json"
    tasks = replay.REPO_ROOT / "evals/suites/skill-router.yaml"
    assert (
        select.main(
            _select_args(inside, tasks) + ["--corpus-root", str(tmp_path)],
            factories=_factories(),
        )
        == 2
    )
    assert not inside.exists()
    assert "inside the repository" in capfd.readouterr().out


def test_select_refuses_a_moved_lock(
    tmp_path: Path, version_dir: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    path = version_dir / "scenarios.jsonl"
    data = bytearray(path.read_bytes())
    data[0] = ord("x") if data[0] != ord("x") else ord("y")
    path.write_bytes(bytes(data))
    out = tmp_path / "selections.json"
    tasks = replay.REPO_ROOT / "evals/suites/skill-router.yaml"
    assert (
        select.main(
            _select_args(out, tasks) + ["--corpus-root", str(tmp_path)],
            factories=_factories(),
        )
        == 2
    )
    assert not out.exists()
    assert "changed since the freeze" in capfd.readouterr().out
